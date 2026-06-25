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
        rig.StopAudio()
        rig.KeyTX()
        rig.SendAudio(device, file)

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
        #
        [sg.Frame('Keyer Buttons', button_row, expand_y=True, expand_x=True)],
        [sg.Push(), sg.Button('Exit'), sg.Push()]
    ]

    window = sg.Window("WK2X Flex Voice Keyer", layout, finalize=True)

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

def list_pw_sinks():
    result = subprocess.run(
        ["pw-dump"],
        capture_output=True,
        text=True,
        check=True
    )

    nodes = json.loads(result.stdout)
    devices = []

    for obj in nodes:
        props = obj.get("info", {}).get("props", {})

        if props.get("media.class") not in {"Audio/Sink", "Stream/Input/Audio"}:
            continue

        node_id = obj.get("id")
        name = props.get("node.name", "")
        desc = props.get("node.description", name)
        nick = props.get("node.nick", "")

        label = desc
        if nick and nick not in desc:
            label = f"{desc} ({nick})"

        devices.append({
            "id": node_id,
            "name": name,
            "description": desc,
            "label": label,
            "target": str(node_id),   # good for pw-play --target
        })

    return devices

def settings_menu(settings):
    devices = list_pw_sinks()
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

def run_gui(settings, layout, window, rig):
    while True:
        rig.PollAudio()

        event, values = window.read(timeout=50)

        if event == sg.WIN_CLOSED or event == "Exit":
            break
        else:
            device = settings['audio-dev']

            if "Play::" in event:
                keyp = event[6:]
                file = get_file(settings, keyp)
                if file != "":
                    _voice_keyer(rig, device, file)

            if event == "Stop":
                rig.StopAudio()

            if event == "About":
                about_box()

            if event == "Settings":
                rig.StopAudio()
                settings, updated = settings_menu(settings)
                if updated == True:
                    for i in range(1,6):
                        window[f'Play::F{i}'].update(settings[f'F{i}-label'])

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
        sys.exit(ret)

if __name__ == "__main__":
    main(sys.argv[:1])
