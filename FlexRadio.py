#!/usr/bin/env python3

from ClientSocket import *
import subprocess
import time

class FlexRadio:
    def __init__(self):
        self.host = ""
        self.port = 0
        self.seq = 1
        self.sock = ClientSocket()
        self.player = None
        self.tx = False
        
    def __del__(self):
        self.sock.close()
        if self.player is not None:
            self.player.terminate()

    def Discover(self):
        disc = {}
        sd = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sd.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sd.bind(('', 4992))
        data, addr = sd.recvfrom(4096)
        if len(data) > 7:
            string = data[28:].decode()
            #print(string)
            ps = string.split(' ')
            for s in ps:
                item = s.split('=')
                disc[item[0]] = item[1]
            #print(disc)
            self.host = disc['ip']
            self.port = int(disc['port'])            
            #print(f'host: {self.host}, port: {self.port}')                                
        sd.close()

    def Connect(self):
        if self.port == 0:
            self.Discover()
        self.sock.connect(self.host, self.port)
        radio_info=self.sock.empty()
        #print(radio_info)

    def SendCmd(self, cmd):
        buf = f"C{self.seq}|{cmd}\n"
        self.sock.write(buf.encode())
        garbage = self.sock.read_until(f'R{self.seq}|'.encode())
        data = self.sock.read_until(b'\n')
        #print(data)
        self.seq += 1
        return data

    def KeyTX(self):
        cmd = f"xmit 1"
        self.SendCmd(cmd)
        self.tx = True
        time.sleep(0.1)

    def UnkeyTX(self):
        cmd = "xmit 0"
        self.SendCmd(cmd)
        self.tx = False
        time.sleep(0.1)

    def PollAudio(self):
        if self.player and self.player.poll() is not None:
            self.StopAudio()

    def SendAudio(self, device, file):
        self.player = subprocess.Popen(["pw-play", '--target', device, file])

    def StopAudio(self):
        if self.player is not None:
            if self.tx == True:
                time.sleep(0.1)
                self.UnkeyTX()

            self.player.terminate()
            self.player.wait(timeout=1)
            self.player = None
