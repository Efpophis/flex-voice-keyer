import socket
import time
import sys
import subprocess
import os
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

    print(f"Listening on {SOCKET_PATH}")

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
    
    #button_row = [
    #    [sg.Push(),        
    #    sg.Button(settings[f'F{i}-label'], key='Play::F{i}'),
    #    sg.Button('F2', key='Play::F2'),
    #    sg.Button('F3', key='Play::F3'),
    #    sg.Button('F4', key='Play::F4'),
    #    sg.Button('F5', key='Play::F5'),
    #    sg.Button('STOP', key="Stop"),
    #    sg.Push()]
    #]
    layout = [
        [sg.Menu(menu_def)],
        [sg.Push(), sg.Text("Device: "), sg.Input(key='Dev::Name', default_text=settings['audio-dev']), sg.Push()],
        [sg.Frame('Keyer Buttons', button_row, expand_y=True, expand_x=True)],
        [sg.Push(), sg.Button('Exit'), sg.Push()]
    ]
    
    window = sg.Window("WK2X Flex Voice Keyer", layout, finalize=True)
    
    # key bindings
    window.bind('<F1>', 'Play::F1')
    window.bind('<F2>', 'Play::F2')
    window.bind('<F3>', 'Play::F3')
    window.bind('<F4>', 'Play::F4')
    window.bind('<F5>', 'Play::F5')
    window.bind('<Escape>', 'Stop')
    
    return layout, window

def about_box():
    version = 'v0.0.1'
    sg.popup_ok(f"WK2X Flex Voice Keyer {version}", 
                "A simple voice keyer for Flex Radios", 
                "by Epophis@gitub https://github.com/Efpophis")

def get_file(keyp):
    filemap = {
        "F1": "call.wav",
        "F2": "call+suffix.wav",
        "F3": "also 59.wav",
        "F4": None,
        "F5": None
    }
    return filemap[keyp]
    
def settings_menu():
    sg.popup_ok("Placeholder",
                "Not implemented yet",
                "TODO")

def run_gui(settings, layout, window, rig):
    while True:
        rig.PollAudio()
        
        event, values = window.read(timeout=50)
        
        if event == sg.WIN_CLOSED or event == "Exit":
            break
        else:
            device = values['Dev::Name']
            
            if "Play::" in event:
                keyp = event[6:]
                file = get_file(keyp)
                if file is not None:
                    _voice_keyer(rig, device, file)
                    
            if event == "Stop":
                rig.StopAudio()

            if event == "About":
                about_box()
            
            if event == "Settings":
                settings_menu()

def _init_settings():
    settings = sg.UserSettings('wk2x-voice-keyer')
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
