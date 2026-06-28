#!/usr/bin/env python3

import asyncio
import websockets
import struct
import threading
from pydub import AudioSegment

class TCIAudio:
    def __init__(self):
        self.backend_name = "TCI (AetherSDR)"
        self.volume = 1.0
        self.player_busy = False
        
        # Threading and synchronization structures
        self.audio_data_buffer = bytearray()
        self.tx_trigger = threading.Event()
        self.abort_trigger = threading.Event()
        self.stop_network_thread = threading.Event()
        
        # Network configuration state
        self.tci_uri = None
        self.persistent_thread = None
        self.trx_index = 0
        self.sample_rate = 48000
        self.header_format = "<16I"

    def BackendName(self):
        return self.backend_name

    def Initialize(self, host, port):
        """Configures the target connection profile and provisions the background networking pipeline."""
        target_uri = f"ws://{host}:{port}"
        
        # Optimization: If we are already connected to this exact address, do nothing
        if self.tci_uri == target_uri and self.persistent_thread and self.persistent_thread.is_alive():
            return "READY"
            
        print(f"TCI Backend: Initializing pipeline for target {target_uri}...")
        
        # 1. Cleanly tear down any active running thread before rebuilding
        self.Terminate()
        
        # 2. Update address parameters and reset thread-stop controls
        self.tci_uri = target_uri
        self.stop_network_thread.clear()
        self.abort_trigger.clear()
        self.tx_trigger.clear()
        self.player_busy = False
        self.audio_data_buffer = bytearray()
        
        # 3. Spin up the fresh persistent thread lifecycle
        self.persistent_thread = threading.Thread(
            target=self._start_persistent_worker, 
            daemon=True
        )
        self.persistent_thread.start()
        return "READY"

    def PollAudio(self):
        """Returns True if the transmission ended or was aborted during this tick."""
        if self.player_busy == True and not self.tx_trigger.is_set() and len(self.audio_data_buffer) == 0:
            self.player_busy = False
            return True
        return False

    def SendAudio(self, device, file):
        """Prepares audio, handles volume math, and instantly signals the live connection to transmit."""
        # Ensure the pipeline was initialized first to prevent edge-case crashes
        if not self.tci_uri:
            print("TCI Backend Warning: SendAudio called before Initialize()!")
            return

        if self.player_busy:
            self.StopAudio()

        try:
            # 1. Format the audio file to standard 48kHz 16-bit Mono PCM
            audio = AudioSegment.from_file(file)
            audio = audio.set_frame_rate(self.sample_rate).set_channels(1).set_sample_width(2)
            raw_pcm = bytearray(audio.raw_data)
            
            # 2. Apply volume slider attenuation scaling configurations
            processed_pcm = self._adjust_volume(raw_pcm, self.volume)
            
            # 3. Swap the buffer data and trip the thread triggers safely
            self.audio_data_buffer = processed_pcm
            self.abort_trigger.clear()
            self.player_busy = True
            
            # This triggers the background worker loop to instantly run the transmission stream
            self.tx_trigger.set()
            
        except Exception as e:
            print(f"TCI Audio Queue Error: {e}")
            self.player_busy = False

    def StopAudio(self):
        """Instantly flags the background async engine to cancel active audio transmission loops."""
        if self.player_busy:
            self.abort_trigger.set()
            self.tx_trigger.clear()
            self.audio_data_buffer = bytearray()
            self.player_busy = False

    def SetVolume(self, volume):
        """Sets the volume factor for future transmissions (Range: 0.0 - 1.0)."""
        self.volume = volume

    def ValidateAudioDevice(self, device):
        """Polymorphic placeholder compatibility verification."""
        return "READY"

    def list_devices(self):
        """Polymorphic placeholder data interface signature mapping."""
        return [{"name": "TCI Persistent Network Pipeline"}]

    def Terminate(self):
        """Completely closes connections, drops PTT, and terminates the background loop worker cleanly."""
        self.StopAudio()
        
        # Tell the persistent thread worker to break its main operational loops
        self.stop_network_thread.set()
        
        if self.persistent_thread:
            self.persistent_thread.join(timeout=1.5)
            self.persistent_thread = None

    # --- Internal Thread & Asynchronous Socket Core ---

    def _adjust_volume(self, pcm_bytes, factor):
        """Modifies volume scales from 0.0 (silent) to 1.0 (unmodified WAV)."""
        factor = max(0.0, min(1.0, float(factor)))
        if factor == 1.0:
            return pcm_bytes
        if factor == 0.0:
            return bytearray(len(pcm_bytes))

        num_samples = len(pcm_bytes) // 2
        samples = struct.unpack(f"<{num_samples}h", pcm_bytes)
        adjusted = [int(s * factor) for s in samples]
        return bytearray(struct.pack(f"<{num_samples}h", *adjusted))

    def _start_persistent_worker(self):
        """Thread worker starting a dedicated asyncio context event loop."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._network_lifecycle_manager())
        finally:
            loop.close()

    async def _network_lifecycle_manager(self):
        """Maintains the connection loop, handling automated reconnects on network drops."""
        while not self.stop_network_thread.is_set():
            try:
                print(f"TCI Persistent: Establishing connection to {self.tci_uri}...")
                async with websockets.connect(self.tci_uri) as ws:
                    print("TCI Persistent: Connected and hot-standby active.")
                    
                    while not self.stop_network_thread.is_set():
                        if self.tx_trigger.is_set():
                            self.tx_trigger.clear()
                            await self._stream_active_audio(ws)
                            
                        await asyncio.sleep(0.01)
                        
            except (websockets.ConnectionClosed, OSError) as conn_err:
                # Only log error and sleep if we aren't intentionally shutting down the thread
                if not self.stop_network_thread.is_set():
                    print(f"TCI Persistent Link Dropped ({conn_err}). Reconnecting in 3s...")
                    self.player_busy = False
                    await asyncio.sleep(3)

    async def _stream_active_audio(self, ws):
        """Streams the pre-allocated data matrix over the active socket session with zero handshake lag."""
        byte_pointer = 0
        audio_length = len(self.audio_data_buffer)
        
        try:
            # ASSERT PTT INSTANTLY (The connection is already alive!)
            await ws.send(f"TRX:{self.trx_index},true,tci;")
            
            while byte_pointer < audio_length and not self.stop_network_thread.is_set():
                if self.abort_trigger.is_set():
                    print("TCI Persistent: Playback transmission sequence aborted!")
                    break
                
                try:
                    packet = await asyncio.wait_for(ws.recv(), timeout=0.04)
                except asyncio.TimeoutError:
                    continue
                
                if isinstance(packet, bytes) and len(packet) >= 64:
                    header = struct.unpack(self.header_format, packet[:64])
                    stream_type = header[6]
                    requested_samples = header[5]
                    
                    if stream_type == 3:  # TYPE_TX_CHRONO
                        needed_bytes = requested_samples * 2
                        chunk = self.audio_data_buffer[byte_pointer : byte_pointer + needed_bytes]
                        actual_samples = len(chunk) // 2
                        
                        if len(chunk) < needed_bytes:
                            chunk = chunk.ljust(needed_bytes, b'\x00')
                            actual_samples = requested_samples
                        
                        tx_packet = struct.pack(
                            self.header_format, self.trx_index, self.sample_rate, 
                            0, 0, 0, actual_samples, 2, 1, 0, 0, 0, 0, 0, 0, 0, 0
                        ) + chunk
                        
                        await ws.send(tx_packet)
                        byte_pointer += needed_bytes
            
            if not self.abort_trigger.is_set() and not self.stop_network_thread.is_set():
                await asyncio.sleep(0.20)
                
        except Exception as tx_err:
            print(f"TCI Persistent Stream Error: {tx_err}")
        finally:
            # DROP PTT IMMEDIATELY
            try:
                await ws.send(f"TRX:{self.trx_index},false;")
            except Exception:
                pass
            
            self.audio_data_buffer = bytearray()
