import contextlib
with contextlib.redirect_stdout(None):
    import pygame._sdl2.audio as sdl2_audio
    import pygame
from FlexRadio import *

class PGAudio:
    def __init__(self):
        self.player = None
        self.device = None
        self.backend_name = "PyGame"
        self.volume = 1.0
        self.player_busy = False
        self.txd_pre = 0.1
        self.txd_post = 0.1
        self.rig = FlexRadio()
        pygame.mixer.init()

    def Initialize(self, host, port):
        if host is not None and port is not None:
            self.rig.host = host
            self.rig.port = port
        self.rig.Connect()

    def BackendName(self):
        return self.backend_name

    def PollAudio(self):
        if self.player is not None:
            if self.player.get_busy() == False:
                self.player.stop()
                self.player_busy = False
                self.player = None
                return True
        return False

    def SendAudio(self, device, file):
        s = pygame.mixer.Sound(file)
        self.rig.txd_pre = self.txd_pre
        self.rig.txd_post = self.txd_post
        if self.player is None:
            self.player = pygame.mixer.Channel(1)
        if self.player_busy == True:
            self.rig.UnkeyTX()
            self.player.stop()
        self.player.set_volume(self.volume)
        self.rig.KeyTX()
        self.player.play(s)
        self.player_busy = True

    def StopAudio(self):
        self.rig.UnkeyTX()
        if self.player is not None:
            self.player.stop()
            self.player_busy = False

    def SetVolume(self, volume):
        if self.player_busy == True:
            self.player.set_volume(volume)
        self.volume = volume
    
    def Status(self):
        #stub for now
        return self.rig.Status()
    
    def ValidateAudioDevice(self, device):
        for dev in self.list_devices():
            if dev["name"] == device:
                if self.device != device:
                    # re-init with new device
                    pygame.mixer.quit()
                    pygame.mixer.init(devicename=device)
                    self.device = device
                    self.player_busy = False
                return "READY"
        return "NO DEVICE"

    def Terminate(self):
        self.StopAudio()
        self.player = None
        self.player_busy = False
        pygame.mixer.quit()

    def list_devices(self):
        devices = []
        # list playback devices
        devs = sdl2_audio.get_audio_device_names(False)

        for d in devs:
            devices.append({"name": d})
        return devices