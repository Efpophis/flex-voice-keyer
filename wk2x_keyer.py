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
from wkicon import icon_b64

audio = WKAudio()

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
        ['File', ['Settings', 'Exit']],
        ['Help', ['About']]
    ]

    buttons = [sg.Push()]

    for i in range(1,6):
        buttons.append(sg.Button(settings[f'F{i}-label'], key=f'Play::F{i}'))

    buttons.append(sg.Button('STOP', key="Stop"))
    buttons.append(sg.Push())

    button_row= [buttons]

    layout = [
        [sg.Menu(menu_def)],
        [sg.Text("Rig:"), sg.Text("DISCONNECTED", justification="center", text_color="black", background_color="red", key="Rig::Status"),
         sg.Text("PTT:"), sg.Text("RX", background_color="green", justification="center", text_color="black", key="Rig::State"), sg.Push(),
         sg.Text("Audio:"), sg.Text("NO DEVICE", text_color="black", background_color="red", justification="center",key="Audio::Status"),
         sg.Text("Device:", key="Dev::Label"), sg.Text(settings['audio-dev'],justification="center", key="Audio::Dev")],
        [sg.Frame('Keyer Buttons', button_row, expand_y=True, expand_x=True)],
        [sg.Push(), sg.Button('Exit'), sg.Push()]
    ]

    window = sg.Window("WK2X Flex Voice Keyer", layout, icon=icon_b64, finalize=True)

    # key bindings
    for i in range(1,6):
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

    for i in range(1,6):
        filemap[f'F{i}'] = settings[f'F{i}-audio']
        
    return filemap[keyp]


def settings_menu(settings):
    devices = audio.list_pw_sinks()
    devChoice = sg.Combo(key='Dev::Name', values=[d['name'] for d in devices], default_value=settings['audio-dev'])
    settings_layout = [
        [sg.Push(), sg.Text("Device: "), devChoice, sg.Push()],
    ]
    for i in range(1,6):
        settings_layout.append([sg.Push(), 
                                sg.Text(f"F{i} Key Label: "),
                                sg.Input(key=f'F{i}-label', default_text=settings[f'F{i}-label']),
                                sg.Text('Audio: '),
                                sg.Input(key=f'F{i}-audio', default_text=settings[f'F{i}-audio']),
                                sg.FileBrowse(key=f'F{i}-file'), sg.Push()])

    settings_layout.append([sg.Push(), sg.Button("Save"), sg.Button("Cancel")])

    window = sg.Window("Settings", settings_layout, modal=True, finalize=True)

    while True:
        event, values = window.Read()

        if event == sg.WIN_CLOSED or event == 'Cancel':
            window.close()
            return settings, False

        elif event == 'Save':
            window.close()
            return save_settings(settings, values), True

def save_settings(settings, values):
    settings['audio-dev'] = values['Dev::Name']

    for i in range(1,6):
        settings[f'F{i}-label'] = values[f'F{i}-label']
        settings[f'F{i}-audio'] = values[f'F{i}-audio']

    return settings

def update_status_indicators(window, flex_status, audio_status, state):
    # flex status: {DISCONNECTED (red), DISCOVERY (gold), CONNECTED (green)}
    # audio status: {READY (green), NO DEVICE (red)}
    # state: {TX (gold), READY (green)}
    color = ""
    
    match flex_status:
        case "DISCONNECTED":
            color = "red"
            window["Rig::State"].update(visible=False)
        case "DISCOVERY":
            color = "gold"
            window["Rig::State"].update(visible=False)
        case "CONNECTED":
            color = "green"
            window["Rig::State"].update(visible=True)
        case _:
            color = "yellow"
    window['Rig::Status'].update(flex_status, background_color=color)
    
    if state == "TX":
        window["Rig::State"].update(state, background_color="gold")
    else:
        window["Rig::State"].update(state, background_color="green")
    
    match audio_status:
        case "READY":
            color = "green"
        case "NO DEVICE":
            color = "red"
        case _:
            color = "yellow"
    window["Audio::Status"].update(audio_status,background_color=color)

def run_gui(settings, layout, window, rig):
    device = settings['audio-dev']
    #global audio = WKAudio()
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
        window["Dev::Label"].update(visible=(audio_status=="READY"))
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

            if event == "Settings":
                rig.UnkeyTX()
                audio.StopAudio()
                settings, updated = settings_menu(settings)
                if updated == True:
                    for i in range(1,6):
                        window[f'Play::F{i}'].update(settings[f'F{i}-label'])
                    device = settings['audio-dev']
                    audio_status = audio.ValidateAudioDevice(device)

def _init_settings():
    config_dir = os.path.join(os.path.expanduser("~"), ".config", "wk2x-voice-keyer")
    settings = sg.UserSettings('voice-keyer.conf', config_dir)
    if settings['audio-dev'] is None:
        settings['audio-dev'] = "AetherSDR"

    for i in range(1,6):
        if settings[f'F{i}-label'] is None:
            settings[f'F{i}-label'] = f"F{i}"

    #print(settings)
    return settings

def main(argv):
    ret = 0
    try:
        settings = _init_settings()

        rig = FlexRadio()
        rig.Connect()

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
