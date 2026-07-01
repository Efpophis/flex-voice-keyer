#!/usr/bin/env python3

import socket
import sys
import os

def get_socket_path():
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    if not runtime_dir:
        runtime_dir = f"/run/user/{os.getuid()}"
    return os.path.join(runtime_dir, "wk2x_voicekeyer.sock")

SOCKET = get_socket_path()

with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
    s.connect(SOCKET)
    s.sendall((" ".join(sys.argv[1:]) + "\n").encode())
