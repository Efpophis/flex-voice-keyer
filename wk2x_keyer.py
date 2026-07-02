#!/usr/bin/env python3

import socket
import time
import sys
import subprocess
import os
import json
#from FlexRadio import *
import FreeSimpleGUI as sg
import threading
#from WKAudio import *
from PGAudio import *
from TCIAudio import *
from wkicon import icon_b64
import traceback
import version

audio = None
LABEL_MAX=13

def get_socket_path():
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    if not runtime_dir:
        runtime_dir = f"/run/user/{os.getuid()}"
    return os.path.join(runtime_dir, "wk2x_voicekeyer.sock")

def create_ipc_socket():
    SOCKET_PATH = get_socket_path()
    
    # Remove stale socket from previous crash
    try:
        os.unlink(SOCKET_PATH)
    except FileNotFoundError:
        pass

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(SOCKET_PATH)
    server.listen(5)

    return server

def ipc_listener(window):
    s = create_ipc_socket()
    while True:
        conn, _ = s.accept()

        try:
            data = conn.recv(1024)

            if not data:
                continue

            cmd = data.decode().strip()

            if cmd.startswith("Play::"):
                window.write_event_value(cmd, cmd[6:])

        except Exception as e:
            print(f"IPC error: {e}")
            raise
        finally:
            conn.close()

def _voice_keyer(device, file):
    try:
        _, txing = audio.Status()
        if txing == "TX":
            audio.StopAudio()
        else:
            audio.SendAudio(device, file)

    except Exception as e:
        print(f"Error executing keyer: {e}")
        raise

def build_layout(settings):
    menu_def = [
        ['&File', ['E&xit']],  ['&Settings', ['&Macros','---', '&Audio', '---', '&Rig']],
        ['&Help', ['A&bout']]
    ]

    buttons = [sg.Push()]
    buttons.append(sg.Button('STOP', button_color=("black","red"), tooltip=" ESC ", key="Stop"))

    for i in range(1,LABEL_MAX):
        buttons.append(sg.Button(settings[f'F{i}-label'], tooltip=f" F{i} ", key=f'Play::F{i}', visible=settings[f'F{i}-enabled']))

    buttons.append(sg.Push())

    button_row= [buttons]

    layout = [
        [sg.Menu(menu_def)],
        [sg.Frame("Status", [
            [ sg.Text("Rig:"),
              sg.Text("DISCONNECTED", justification="center", text_color="black", background_color="red", key="Rig::Status"),
              sg.Text("RX", background_color="green", justification="center", text_color="black", key="Rig::State"),
            ],
            [sg.Text("Audio:"), sg.Text("NO DEVICE", text_color="black", background_color="red",
                                        justification="center",key="Audio::Status"),
                                sg.Text(settings['audio-dev'],justification="center", key="Audio::Dev")],
            [sg.Text("Backend:"), sg.Text(settings['audio-backend'], justification="center", key="Audio::Backend")]
        ],expand_x=True, expand_y=True)],
        [sg.Text("")],
        [sg.pin(sg.Text("Output Volume:  0", visible=(audio.BackendName() == "SmartSDR (DAX)"), key="Vol::lbl")),
         sg.pin(sg.Slider((1,110), orientation='horizontal', disable_number_display=True, visible=(audio.BackendName() == "SmartSDR (DAX)"),
                    key="Volume", enable_events=True, default_value=settings['volume']*110, expand_x=True)),
        sg.pin(sg.Text("11", visible=(audio.BackendName() == "SmartSDR (DAX)"), key="Vol::lbl1"))],
        [sg.Frame('Macro Buttons', button_row, expand_y=True, expand_x=True)],
        [sg.Text("")],
        [sg.Push(), sg.Button('Exit')]
    ]

    window = sg.Window(f"WK2X Flex Voice Keyer v{version.VERSION}-{version.COMMIT}", layout, icon=icon_b64, finalize=True)

    # key bindings
    for i in range(1,LABEL_MAX):
        window.bind(f'<F{i}>', f'Play::F{i}')
    window.bind('<Escape>', 'Stop')

    return layout, window

def about_box():
    sg.popup_ok(f"WK2X Flex Voice Keyer v{version.VERSION}-{version.COMMIT}",
                f"Build: {version.GIT_BRANCH}-{version.BUILD_TIME}",
                "",
                "A simple voice keyer for Flex Radios",
                "by Epophis@gitub https://github.com/Efpophis")

def get_file(settings, keyp):
    filemap = {}

    for i in range(1,LABEL_MAX):
        filemap[f'F{i}'] = settings[f'F{i}-audio']

    return filemap[keyp]

def audio_menu(settings):
    audio.StopAudio()
    devices = audio.list_devices()
    devChoice = sg.Combo(key='Dev::Name',
                         values=[d['name'] for d in devices],
                         default_value=settings['audio-dev'],
                         visible=(settings['audio-backend'] == "SmartSDR (DAX)")
                        )
    beChoice = sg.Combo(key='Dev::Backend', values=['SmartSDR (DAX)', 'TCI'], enable_events=True, default_value=settings['audio-backend'])

    settings_layout = [
        [sg.Text("Audio Backend: "), beChoice],
        [sg.pin(sg.Text("Device: ", key="Dev::PGl", visible=(settings['audio-backend'] == "SmartSDR (DAX)"))),sg.pin(devChoice)],
        [sg.pin(sg.Checkbox("Link AetherSDR TX to PC Audio Input (use only on Linux/pipewire and AetherSDR < v26.6.x)", 
                     key="hackcheck", default=settings['audio-hack'], visible=audio.BackendName() == "SmartSDR (DAX)"))],
        [sg.pin(sg.Text("TCI Host:", key="Dev::TCIhl", visible=(settings['audio-backend'] == "TCI"))),
         sg.pin(sg.Input(key='TCI::Host', default_text=settings['tci-host'], visible=(settings['audio-backend'] == "TCI")))
         ],
        [sg.pin(sg.Text("TCI Port:", key="Dev::TCIpl", visible=(settings['audio-backend'] == "TCI"))),
         sg.pin(sg.Input(key='TCI::Port', default_text=settings['tci-port'], visible=(settings['audio-backend'] == "TCI")))
        ]
    ]

    settings_layout.append([sg.Push(), sg.Button("Save"), sg.Button("Cancel")])
    window = sg.Window(f"WK2X Keyer v{version.VERSION} - Audio Configuration", settings_layout, modal=True, finalize=True)

    while True:
        event, values = window.Read()

        if event == sg.WIN_CLOSED or event == 'Cancel':
            window.close()
            return settings, False
        elif event == "Dev::Backend":
            audio_be = get_audio_backend(values[event])
            devices = audio_be.list_devices()
            be_name = audio_be.BackendName()

            window['Dev::PGl'].update(visible=(be_name == "SmartSDR (DAX)"))
            window['Dev::Name'].update(values=[d['name'] for d in devices], visible=(be_name == "SmartSDR (DAX)"), value=" ")
            window['hackcheck'].update(visible=(audio_be.BackendName() == "SmartSDR (DAX)"))
            window['Dev::TCIhl'].update(visible=(be_name == "TCI"))
            window['TCI::Host'].update(visible=(be_name == "TCI"))
            window['Dev::TCIpl'].update(visible=(be_name == "TCI"))
            window['TCI::Port'].update(visible=(be_name == "TCI"))

        elif event == 'Save':
            window.close()
            return save_audio_settings(settings, values), True

def EnsureAudioPath(source, target, enabled):
    links = subprocess.run(
            ["pw-link", "-l"],
            capture_output=True,
            text=True
        ).stdout
    if enabled:
        #print(f"links: {links}")
        if source in links and target in links:
            return

        subprocess.run(["pw-link", source, target], check=False)
    else:
        if source in links and target in links:
            subprocess.run(["pw-link", "-d", source, target], check=False)

def macros_menu(settings):
    settings_layout = [[sg.Push(), sg.Text("Macro Configuration"), sg.Push()]]
    for i in range(1,LABEL_MAX):
        settings_layout.append([sg.Push(),
                                sg.Checkbox("Enabled", key=f'F{i}-enabled', default=settings[f'F{i}-enabled']),
                                sg.Text(f"F{i} Label:"),sg.Push(),
                                sg.Input(key=f'F{i}-label', default_text=settings[f'F{i}-label']),
                                sg.Text('Audio:'),sg.Push(),
                                sg.Input(key=f'F{i}-audio', default_text=settings[f'F{i}-audio']),
                                sg.FileBrowse(key=f'F{i}-file'), sg.Push()])

    settings_layout.append([sg.Push(), sg.Button("Save"), sg.Button("Cancel")])

    window = sg.Window(f"WK2X Keyer v{version.VERSION} - Macro Configuration", settings_layout, modal=True, finalize=True)

    while True:
        event, values = window.Read()

        if event == sg.WIN_CLOSED or event == 'Cancel':
            window.close()
            return settings, False

        elif event == 'Save':
            window.close()
            return save_macros(settings, values), True

def rig_menu(settings):
    settings_layout = [[sg.Push(), sg.Text("Rig Settings"), sg.Push()],
                       [sg.Text("Pre-TX Delay: "), sg.Push(),sg.Input(key='Rig::PreTXD', default_text=str(settings['rig-txpre-delay']))],
                       [sg.Text("Post-Tx Delay:"), sg.Push(),sg.Input(key='Rig::PosTXD', default_text=str(settings['rig-txpost-delay']))]
    ]

    settings_layout.append([sg.Push(), sg.Button("Save"), sg.Button("Cancel")])

    window = sg.Window(f"WK2X Keyer v{version.VERSION} - Rig Settings", settings_layout, modal=True, finalize=True)

    while True:
        event, values = window.Read()

        if event == sg.WIN_CLOSED or event == 'Cancel':
            window.close()
            return settings, False

        elif event == 'Save':
            window.close()
            return save_rig_settings(settings, values), True

def save_rig_settings(settings, values):
    audio.txd_pre  = settings['rig-txpre-delay'] = float(values["Rig::PreTXD"])
    audio.txd_post = settings['rig-txpost-delay'] = float(values["Rig::PosTXD"])

    return settings

def get_audio_backend(backend_name):
    audio = None
    match backend_name:
        case "TCI":
            audio = TCIAudio()
        case "SmartSDR (DAX)":
            audio = PGAudio()
    return audio

def save_audio_settings(settings, values):
    global audio

    settings['audio-backend'] = values['Dev::Backend']
    settings['audio-dev'] = values['Dev::Name']
    settings['audio-hack'] = values['hackcheck']

    if settings['tci-host'] != values['TCI::Host'] or settings['tci-port'] != int(values['TCI::Port']):
        settings['tci-host'] = values['TCI::Host']
        settings['tci-port'] = int(values['TCI::Port'])
        tci_url_latch = True;
    else:
        tci_url_latch = False;


    if values['Dev::Backend'] != audio.BackendName():
        if audio is not None:
            audio.Terminate()
        audio = get_audio_backend(values['Dev::Backend'])
        match audio.BackendName():
            case "TCI":
                audio.Initialize(settings['tci-host'], settings['tci-port'])
                settings['audio-dev'] = audio.list_devices()[0]['name']
            case "SmartSDR (DAX)":
                audio.Initialize(None, None)
    
    if audio.BackendName() == "SmartSDR (DAX)" and settings['audio-dev'] == "AetherSDR TX":
        EnsureAudioPath("aethersdr-tx:monitor_MONO", "AetherSDR:input_AUX0", settings['audio-hack'])
    else:
        EnsureAudioPath("aethersdr-tx:monitor_MONO", "AetherSDR:input_AUX0", False)

    if tci_url_latch:
        audio.Terminate()
        audio.Initialize(settings['tci-host'], settings['tci-port'])

    return settings

def save_macros(settings, values):

    for i in range(1,LABEL_MAX):
        settings[f'F{i}-label'] = values[f'F{i}-label']
        settings[f'F{i}-audio'] = values[f'F{i}-audio']
        settings[f'F{i}-enabled'] = values[f'F{i}-enabled']

    return settings

def update_status_indicators(window, flex_status, audio_status, state):
    # flex status: {OFFLINE (red), DISCOVERY (gold), CONNECTED (green)}
    # audio status: {READY (green), NO DEVICE (red)}
    # state: {TX (gold), READY (green)}
    STATUS_COLORS = {
        "OFFLINE":      "#FF0000",
        "DISCONNECTED": "#FF0000",
        "NO DEVICE":    "#FF0000",
        "DISCOVERY":    "#FFA500",
        "CONNECTED":    "#FFD700",
        "CONNECTING":   "#00BFFF",
        "STANDBY":      "#FFD700",
        "RX":           "#00FF00",
        "READY":        "#00FF00",
        "TX":           "#00BFFF",
        "ERROR":        "#FF0000",
    }
    color = STATUS_COLORS[flex_status]
    state_color = STATUS_COLORS[state]
    match flex_status:
        case "DISCONNECTED":
            window["Rig::State"].update(visible=False)
        case "DISCOVERY":
            window["Rig::State"].update(visible=False)
        case "CONNECTED":
            window["Rig::State"].update(visible=True)

    window['Rig::Status'].update(flex_status, background_color=STATUS_COLORS[flex_status])
    window["Rig::State"].update(state, visible=(flex_status == "READY"), background_color=STATUS_COLORS[state])
    window["Audio::Status"].update(audio_status,background_color=STATUS_COLORS[audio_status])

def run_gui(settings, layout, window):
    device = settings['audio-dev']
    #print(f"audio device {device}")
    audio_status = audio.ValidateAudioDevice(device)
    counter = 0
    
    if audio.BackendName() == "SmartSDR (DAX)":
        EnsureAudioPath("aethersdr-tx:monitor_MONO", "AetherSDR:input_AUX0", settings['audio-hack'])
    else:
        EnsureAudioPath("aethersdr-tx:monitor_MONO", "AetherSDR:input_AUX0", False)


    while True:
        # see if audio has finished, and we need to un-key the rig
        if audio.PollAudio() == True:
            #time.sleep(0.1)
            audio.StopAudio()

        flex_status, state = audio.Status()

        if counter >= 20:
            prev = audio_status
            audio_status = audio.ValidateAudioDevice(device)
            window["Audio::Dev"].update(device, visible=(audio_status == "READY"))
            if prev != audio_status and audio_status == "READY":
                if audio.BackendName() == "SmartSDR (DAX)" and audio.device == "AetherSDR TX":
                    EnsureAudioPath("aethersdr-tx:monitor_MONO", "AetherSDR:input_AUX0", settings['audio-hack'])
                else:
                    EnsureAudioPath("aethersdr-tx:monitor_MONO", "AetherSDR:input_AUX0", False)
            counter = 0
        else:
            counter += 1

        update_status_indicators(window, flex_status, audio_status, state)

        event, values = window.read(timeout=50)

        if event == sg.WIN_CLOSED or event == "Exit":
            break
        else:
            if "Play::" in event:
                keyp = event[6:]
                file = get_file(settings, keyp)
                if file and audio_status == "READY":
                    _voice_keyer(device, file)
                else:
                    print(f"not keying because file = {file}, audio_status = {audio_status}")

            elif event == "Stop":
                audio.StopAudio()

            elif event == "About":
                about_box()

            elif event == "Rig":
                audio.StopAudio()
                settings, updated = rig_menu(settings)
                if updated == True:
                    audio.txd_pre = settings['rig-txpre-delay']
                    audio.txd_post = settings['rig-txpost-delay']

            elif event == "Volume":
                # normalise to 0..1.0
                vol = values["Volume"] / 110.0
                settings['volume'] = vol
                audio.SetVolume(vol)

            elif event == "Audio":
                audio.StopAudio()
                settings, updated = audio_menu(settings)
                if updated == True:
                    device = settings['audio-dev']
                    audio_status = audio.ValidateAudioDevice(device)
                    #audio.Initialize()
                    window["Audio::Backend"].update(settings['audio-backend'])
                    newbe = settings['audio-backend']
                    window['Vol::lbl'].update(visible=(newbe == "SmartSDR (DAX)"))
                    window['Volume'].update(visible=(newbe == "SmartSDR (DAX)"))
                    window['Vol::lbl1'].update(visible=(newbe == "SmartSDR (DAX)"))

            elif event == "Macros":
                audio.StopAudio()
                settings, updated = macros_menu(settings)
                if updated == True:
                    for i in range(1,LABEL_MAX):
                        window[f'Play::F{i}'].update(settings[f'F{i}-label'], visible=settings[f'F{i}-enabled'])
            elif event == "__TIMEOUT__":
                continue
            else:
                print(event)

def _init_settings():
    config_dir = os.path.join(os.path.expanduser("~"), ".config", "wk2x-voice-keyer")
    settings = sg.UserSettings('voice-keyer.conf', config_dir)
    if settings['audio-dev'] is None:
        settings['audio-dev'] = "TCI (AetherSDR)"

    if settings['audio-backend'] is None:
        settings['audio-backend'] = "TCI"

    if settings['tci-host'] is None:
        settings['tci-host'] = "localhost"
    if settings['tci-port'] is None:
        settings['tci-port'] = 50001

    for i in range(1,LABEL_MAX):
        if settings[f'F{i}-label'] is None:
            settings[f'F{i}-label'] = f"F{i}"
        if settings[f'F{i}-enabled'] is None:
            settings[f'F{i}-enabled'] = True
        if settings[f'F{i}-audio'] is None:
            settings[f'F{i}-audio'] = ""

    if settings['rig-txpre-delay'] is None:
        settings['rig-txpre-delay'] = 0.1

    if settings['rig-txpost-delay'] is None:
        settings['rig-txpost-delay'] = 0.1

    if settings['volume'] is None:
        settings['volume'] = 1.0
    
    if settings['audio-hack'] is None:
        settings['audio-hack'] = False

    return settings

def main(argv):
    ret = 0
    global audio
    try:
        settings = _init_settings()

        # set up audio backend
        match settings['audio-backend']:
            case "SmartSDR (DAX)":
                audio = PGAudio()
                audio.Initialize(None, None)
            case "TCI":
                audio = TCIAudio()
                audio.Initialize(settings['tci-host'], settings['tci-port'])

        audio.SetVolume(settings['volume'])

        audio.txd_pre = settings['rig-txpre-delay']
        audio.txd_post = settings['rig-txpost-delay']

        layout, window = build_layout(settings)

        t = threading.Thread(
            target=ipc_listener,
            args=(window,),
            daemon=True
        )
        t.start()

        run_gui(settings, layout, window)
    except Exception as e:
        print(f"Error: {e}")
        traceback.print_exc()
        ret = 1
    finally:
 #       rig.UnkeyTX()
        if audio is not None:
            audio.StopAudio()
            audio.Terminate()
        sys.exit(ret)

if __name__ == "__main__":
    main(sys.argv[:1])
