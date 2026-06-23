#!/usr/bin/env python3

import socket
import sys

SOCKET = "/tmp/wk2x_voicekeyer.sock"

with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
    s.connect(SOCKET)
    s.sendall((" ".join(sys.argv[1:]) + "\n").encode())
