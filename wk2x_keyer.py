#!/usr/bin/env python3

import socket
import time
import sys
import subprocess
import os
import json
from FlexRadio import *
import FreeSimpleGUI as sg
import threading
from WKAudio import *
from PGAudio import *
from wkicon import icon_b64

audio = None
LABEL_MAX=13
#audio = PGAudio()

def create_ipc_socket():
    SOCKET_PATH="/tmp/wk2x_voicekeyer.sock"
    # Remove stale socket from previous crash
    try:
        os.unlink(SOCKET_PATH)
    except FileNotFoundError:
        pass

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(SOCKET_PATH)
    server.listen(5)

    #print(f"Listening on {SOCKET_PATH}")

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

            if "Play::" in cmd:
                window.write_event_value(cmd, cmd[6:])

        except Exception as e:
            print(f"IPC error: {e}")
        finally:
            conn.close()

def _voice_keyer(rig, device, file):
    try:
        rig.UnkeyTX()
        audio.StopAudio()
        rig.KeyTX()
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
        [sg.Text("Output Volume:  0"),
         sg.Slider((1,110), orientation='horizontal', disable_number_display=True,
                    key="Volume", enable_events=True, default_value=settings['volume']*110, expand_x=True), 
        sg.Text("11")],
        [sg.Frame('Macro Buttons', button_row, expand_y=True, expand_x=True)],
        [sg.Text("")],
        [sg.Push(), sg.Button('Exit')]
    ]

    window = sg.Window("WK2X Flex Voice Keyer", layout, icon=icon_b64, finalize=True)

    # key bindings
    for i in range(1,LABEL_MAX):
        window.bind(f'<F{i}>', f'Play::F{i}')
    window.bind('<Escape>', 'Stop')

    return layout, window

def about_box():
    version = 'v0.0.1'
    sg.popup_ok(f"WK2X Flex Voice Keyer {version}", 
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
    devChoice = sg.Combo(key='Dev::Name', values=[d['name'] for d in devices], default_value=settings['audio-dev'])
    beChoice = sg.Combo(key='Dev::Backend', values=['PyGame', 'pipewire'], enable_events=True, default_value=settings['audio-backend'])
    settings_layout = [
        [sg.Push(), sg.Text("Audio Backend: "), beChoice, sg.Push()],
        [sg.Push(), sg.Text("Device: "), devChoice, sg.Push()],
    ]
    settings_layout.append([sg.Push(), sg.Button("Save"), sg.Button("Cancel")])
    window = sg.Window("WK2X Keyer - Audio Configuration", settings_layout, modal=True, finalize=True)

    while True:
        event, values = window.Read()

        if event == sg.WIN_CLOSED or event == 'Cancel':
            window.close()
            return settings, False
        elif event == "Dev::Backend":
            audio_be = get_audio_backend(values[event])
            devices = audio_be.list_devices()
            window['Dev::Name'].update(values=[d['name'] for d in devices], value=" ")
        elif event == 'Save':
            window.close()
            return save_audio_settings(settings, values), True

def macros_menu(settings):
    settings_layout = [[sg.Push(), sg.Text("Macro Configuration"), sg.Push()]]
    for i in range(1,LABEL_MAX):
        settings_layout.append([sg.Push(), 
                                sg.Checkbox("Enabled:", key=f'F{i}-enabled', default=settings[f'F{i}-enabled']),
                                sg.Text(f"F{i} Label: "),
                                sg.Input(key=f'F{i}-label', default_text=settings[f'F{i}-label']),
                                sg.Text('Audio: '),
                                sg.Input(key=f'F{i}-audio', default_text=settings[f'F{i}-audio']),
                                sg.FileBrowse(key=f'F{i}-file'), sg.Push()])

    settings_layout.append([sg.Push(), sg.Button("Save"), sg.Button("Cancel")])

    window = sg.Window("WK2X Keyer - Macro Configuration", settings_layout, modal=True, finalize=True)

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
                       [sg.Text("Pre-TX Delay: "), sg.Input(key='Rig::PreTXD', default_text=str(settings['rig-txpre-delay'])), sg.Push()],
                       [sg.Text("Post-Tx Delay:"), sg.Input(key='Rig::PosTXD', default_text=str(settings['rig-txpost-delay']))]
    ]
    
    settings_layout.append([sg.Push(), sg.Button("Save"), sg.Button("Cancel")])
    
    window = sg.Window("WK2X Keyer - Rig Settings", settings_layout, modal=True, finalize=True)
    
    while True:
        event, values = window.Read()
        
        if event == sg.WIN_CLOSED or event == 'Cancel':
            window.close()
            return settings, False

        elif event == 'Save':
            window.close()
            return save_rig_settings(settings, values), True

def save_rig_settings(settings, values):
    settings['rig-txpre-delay'] = float(values["Rig::PreTXD"])
    settings['rig-txpost-delay'] = float(values["Rig::PosTXD"])
    return settings

def get_audio_backend(backend_name):
    audio = None
    match backend_name:
        case "pipewire":
            audio = WKAudio()
        case "PyGame":
            audio = PGAudio()
    return audio

def save_audio_settings(settings, values):
    global audio
    settings['audio-dev'] = values['Dev::Name']
    settings['audio-backend'] = values['Dev::Backend']

    if values['Dev::Backend'] != audio.BackendName():
        if audio is not None:
            audio.Terminate()
        audio = get_audio_backend(values['Dev::Backend'])

    return settings

def save_macros(settings, values):

    for i in range(1,LABEL_MAX):
        settings[f'F{i}-label'] = values[f'F{i}-label']
        settings[f'F{i}-audio'] = values[f'F{i}-audio']
        settings[f'F{i}-enabled'] = values[f'F{i}-enabled']

    return settings

def update_status_indicators(window, flex_status, audio_status, state):
    # flex status: {DISCONNECTED (red), DISCOVERY (gold), CONNECTED (green)}
    # audio status: {READY (green), NO DEVICE (red)}
    # state: {TX (gold), READY (green)}
    STATUS_COLORS = {
        "OFFLINE":      "#FF0000",
        "NO DEVICE":    "#FF0000",
        "DISCOVERING":  "#FFA500",
        "CONNECTED":    "#FFD700",
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

def run_gui(settings, layout, window, rig):
    device = settings['audio-dev']
    audio_status = audio.ValidateAudioDevice(device)
    counter = 0
    
    while True:
        # see if audio has finished, and we need to un-key the rig
        if audio.PollAudio() == True:
            time.sleep(0.1)
            rig.UnkeyTX()

        flex_status, state = rig.Status()
    
        if counter >= 20:
            audio_status = audio.ValidateAudioDevice(device)
            counter = 0
        else:
            counter += 1
                
        update_status_indicators(window, flex_status, audio_status, state)
        #window["Dev::Label"].update(visible=(audio_status=="READY"))
        window["Audio::Dev"].update(device, visible=(audio_status == "READY"))
        

        event, values = window.read(timeout=50)

        if event == sg.WIN_CLOSED or event == "Exit":
            break
        else:
            if "Play::" in event:
                keyp = event[6:]
                file = get_file(settings, keyp)
                if file != "" and audio_status == "READY":
                    _voice_keyer(rig, device, file)

            if event == "Stop":
                rig.UnkeyTX()
                audio.StopAudio()

            if event == "About":
                about_box()
                
            if event == "Rig":
                rig.UnkeyTX()
                audio.StopAudio()
                settings, updated = rig_menu(settings)
                if updated == True:
                    rig.txd_pre = settings['rig-txpre-delay']
                    rig.txd_post = settings['rig-txpost-delay']
                    
            if event == "Volume":
                # normalise to 0..1.0
                vol = values["Volume"] / 110.0
                settings['volume'] = vol
                audio.SetVolume(vol)

            if event == "Audio":
                rig.UnkeyTX()
                audio.StopAudio()
                settings, updated = audio_menu(settings)
                if updated == True:
                    device = settings['audio-dev']
                    audio_status = audio.ValidateAudioDevice(device)
                    window["Audio::Backend"].update(settings['audio-backend'])
                    
            if event == "Macros":
                rig.UnkeyTX()
                audio.StopAudio()
                settings, updated = macros_menu(settings)
                if updated == True:
                    for i in range(1,LABEL_MAX):
                        window[f'Play::F{i}'].update(settings[f'F{i}-label'], visible=settings[f'F{i}-enabled'])

def _init_settings():
    config_dir = os.path.join(os.path.expanduser("~"), ".config", "wk2x-voice-keyer")
    settings = sg.UserSettings('voice-keyer.conf', config_dir)
    if settings['audio-dev'] is None:
        settings['audio-dev'] = "AetherSDR"

    if settings['audio-backend'] is None:
        settings['audio-backend'] = "pipewire"

    for i in range(1,LABEL_MAX):
        if settings[f'F{i}-label'] is None:
            settings[f'F{i}-label'] = f"F{i}"
        if settings[f'F{i}-enabled'] is None:
            settings[f'F{i}-enabled'] = True
    
    if settings['rig-txpre-delay'] is None:
        settings['rig-txpre-delay'] = 0.1

    if settings['rig-txpost-delay'] is None:
        settings['rig-txpost-delay'] = 0.1
        
    if settings['volume'] is None:
        settings['volume'] = 1.0

    #print(settings)
    return settings

def main(argv):
    ret = 0
    global audio
    try:
        settings = _init_settings()
        
        # set up audio backend
        if settings['audio-backend'] == "pipewire":
            audio = WKAudio()
        else:
            audio = PGAudio()
        audio.SetVolume(settings['volume'])
        
        rig = FlexRadio()
        rig.Connect()
        rig.txd_pre = settings['rig-txpre-delay']
        rig.txd_post = settings['rig-txpost-delay']

        layout, window = build_layout(settings)

        t = threading.Thread(
            target=ipc_listener,
            args=(window,),
            daemon=True
        )
        t.start()

        run_gui(settings, layout, window, rig)
    except Exception as e:
        print(f"Error: {e}")
        ret = 1
    finally:
        rig.UnkeyTX()
        audio.StopAudio()
        sys.exit(ret)

if __name__ == "__main__":
    main(sys.argv[:1])
