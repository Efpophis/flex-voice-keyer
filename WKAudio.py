import subprocess
import time
import json


class WKAudio:

    def __init__(self):
        self.player = None
        self.volume = "1.0"
        self.backend_name = "pipewire"

    def BackendName(self):
        return self.backend_name

    def PollAudio(self):
        if self.player and self.player.poll() is not None:
            self.StopAudio()
            return True
        return False

    def SendAudio(self, device, file):
        self.player = subprocess.Popen(["pw-play", '--target', device, '--volume', self.volume, file])

    def StopAudio(self):
        if self.player is not None:
            self.player.terminate()
            self.player.wait(timeout=1)
            self.player = None

    def ValidateAudioDevice(self, device):
        for dev in self.list_devices():
            if dev["name"] == device:
                return "READY"
        return "NO DEVICE"

    def SetVolume(self, volume):
        self.volume = str(volume)

    def Terminate(self):
        self.StopAudio()

    def list_devices(self):
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

            devices.append({"name": name})

        return devices