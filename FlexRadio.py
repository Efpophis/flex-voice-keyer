#!/usr/bin/env python3

from ClientSocket import *
import subprocess
import time
import threading
from dataclasses import dataclass

# TODO: 
#       Monitor status messages from the Flex to determine if TX is allowed.
#       Reflect that in status and TX state instead of assuming.
#       C#|sub interlock all   (maybe not even needed)

@dataclass
class FlexStatus:
    raw: str
    handle: str
    topic: str
    subtopic: str | None
    values: dict[str, str]

class FlexRadio:
    def __init__(self):
        self.host = ""
        self.port = 0
        self.seq = 1
        self.sock = ClientSocket()
        self.tx = False
        self.rig_status = "DISCONNECTED"
        self.txd_pre = 0
        self.txd_post = 0
        self.listener = None
        self.handle = None
        self.version = None
        
    def __del__(self):
        self.sock.close()
        if self.player is not None:
            self.player.terminate()
        if self.listern is not None:
            self.listener = None

    def parse_flex_status(self, line: str) -> FlexStatus:
        line = line.strip()

        if not line.startswith("S"):
            raise ValueError(f"Not a status message: {line!r}")

        prefix, body = line[1:].split("|", 1)
        handle = prefix

        parts = body.split()
        if not parts:
            raise ValueError(f"Empty status body: {line!r}")

        topic = parts[0]
        subtopic = None
        kv_start = 1

        # If the next token does not contain '=', treat it as a subtopic.
        if len(parts) > 1 and "=" not in parts[1]:
            subtopic = parts[1]
            kv_start = 2

        values = {}

        for token in parts[kv_start:]:
            if "=" not in token:
                continue

            key, value = token.split("=", 1)
            values[key] = value

        return FlexStatus(
            raw=line,
            handle=handle,
            topic=topic,
            subtopic=subtopic,
            values=values,
        )

    def _status_listener(self):
        mysock = ClientSocket()
        mysock.connect(self.host, self.port)
        mysock.settimeout(1)
        while self.listener is not None:
            try:
                msg = mysock.read_until(b'\n').decode('utf-8')

                match msg[0]:
                    case "H":
                        self.handle = msg[1:]
                        #print(f'handle = {self.handle}')
                    case "V":
                        self.version = msg[1:]
                        #print(f'version = {self.version}')
                    case 'M':
                        msgid = msg[1:8]
                        msgtxt = msg[10:]
                        #print(f'messageid = {msgid} : {msgtxt}')
                    case 'R':
                        # response to a command - can probably ignore?
                        # maybe handle it later
                        junk=1
                    case 'S':
                        status = self.parse_flex_status(msg)
                        if status.topic == "interlock" and 'state' in status.values:
                            match status.values['state']:
                                case "RECEIVE":
                                    self.rig_status = "STANDBY"
                                    self.tx = False
                                case "READY":
                                    self.rig_status = "READY"
                                    self.tx = False
                                case "TRANSMITTING":
                                    self.rig_status = "READY"
                                    self.tx = True
                                case "PTT_REQUESTED":
                                    # ignore
                                    self.tx = False
                                case _:
                                    # the rest are errors
                                    self.rig_status = "ERROR"
                                    self.tx = False
                    case _:
                        print(msg)
            except socket.timeout:
                continue
            except Exception as e:
                print(f"Socket error: {e}")
                self.listener = None
        mysock.close()
        print("FlexRadio: status thread finished.")

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
        self.StartStatusThread()
        
    def StartStatusThread(self):
        self.listener = threading.Thread(target=self._status_listener, daemon=True)
        self.listener.start()

    def SendCmd(self, cmd):
        buf = f"C{self.seq}|{cmd}\n"
        self.sock.write(buf.encode())
        garbage = self.sock.read_until(f'R{self.seq}|'.encode())
        data = self.sock.read_until(b'\n')
        self.seq += 1
        return data

    def KeyTX(self):
        cmd = f"xmit 1"
        self.SendCmd(cmd)
        #self.tx = True
        time.sleep(self.txd_pre)

    def UnkeyTX(self):
        cmd = "xmit 0"
        self.SendCmd(cmd)
        #self.tx = False
        time.sleep(self.txd_post)
