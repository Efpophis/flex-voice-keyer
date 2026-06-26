import contextlib
with contextlib.redirect_stdout(None):
    import pygame._sdl2.audio as sdl2_audio
    import pygame

class PGAudio:
    def __init__(self):
        self.player = None
        self.device = None
        self.backend_name = "PyGame"
        pygame.mixer.init()
    
    def BackendName(self):
        return self.backend_name
    
    def PollAudio(self):
        if self.player is not None:
            if self.player.get_busy() == False:
                self.player.stop()
                return True
        return False

    def SendAudio(self, device, file):
        s = pygame.mixer.Sound(file)
        if self.player is None:
            self.player = pygame.mixer.Channel(1)
        if self.player.get_busy():
            self.player.stop()
        self.player.play(s)
    
    def StopAudio(self):
        if self.player is not None:
            self.player.stop()

    def SetVolume(self, volume):
        self.player.set_volume(volume)        
        
    def ValidateAudioDevice(self, device):
        for dev in self.list_devices():
            if dev["name"] == device:
                if self.device != device:
                    # re-init with new device
                    pygame.mixer.quit()
                    pygame.mixer.init(devicename=device)
                    self.device = device                    
                return "READY"
        return "NO DEVICE"

    def Terminate(self):
        self.StopAudio()
        self.player = None
        pygame.mixer.quit()

    def list_devices(self):
        devices = []
        # list playback devices
        devs = sdl2_audio.get_audio_device_names(False)

        for d in devs:
            devices.append({"name": d})
        return devices