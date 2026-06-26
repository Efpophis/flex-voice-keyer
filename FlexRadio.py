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
        self.tx = False
        self.rig_status = "DISCONNECTED"
        
    def __del__(self):
        self.sock.close()
        if self.player is not None:
            self.player.terminate()

    def Discover(self):
        self.rig_status = "DISCOVERY"
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

    def Status(self):
        flex_status = self.rig_status
        
        if self.tx == True:
            state = "TX"
        else:
            state = "RX"
        
        return flex_status, state

    def Connect(self):
        if self.port == 0:
            self.Discover()
        self.sock.connect(self.host, self.port)
        radio_info=self.sock.empty()
        self.rig_status = "CONNECTED"
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

   
