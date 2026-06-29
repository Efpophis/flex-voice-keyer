#!/usr/bin/env python3

import asyncio
import websockets
import struct
import threading
import io
from pydub import AudioSegment
import array
import time

class TCIAudio:
    def __init__(self):
        self.backend_name = "TCI"
        self.volume = 1.0
        self.player_busy = False
        self.txd_pre = 0.1
        self.txd_post = 0.1
        self.rig_status = "OFFLINE"
        self.tx_status = "RX"
        
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
        self.packet_cache = {}
        self.audio_duration = 0
        self.tx_stream_start = 0
        self.tx_idx = 0

    def BackendName(self):
        return self.backend_name

    def Status(self):
        return self.rig_status, self.tx_status
    
    def Initialize(self, host='localhost', port=50001):
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
            # 3. Swap the buffer data and trip the thread triggers safely
            self.audio_data_buffer, self.audio_duration = self.load_tci_audio(file, 
                                                            sample_rate=self.sample_rate,
                                                            volume=self.volume)
            self.abort_trigger.clear()
            self.player_busy = True
            
            # This triggers the background worker loop to instantly run the transmission stream
            self.tx_trigger.set()
            
        except Exception as e:
            print(f"TCI Audio Queue Error: {e}")
            self.player_busy = False
            raise

    def StopAudio(self):
        """Instantly flags the background async engine to cancel active audio transmission loops."""
        if self.player_busy:
            print("aborting")
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
        return [{"name": "TCI (AetherSDR)"}]

    def Terminate(self):
        """Completely closes connections, drops PTT, and terminates the background loop worker cleanly."""
        self.StopAudio()
        
        # Tell the persistent thread worker to break its main operational loops
        self.stop_network_thread.set()
        
        if self.persistent_thread:
            self.persistent_thread.join(timeout=1.5)
            self.persistent_thread = None

    def _start_persistent_worker(self):
        """Thread worker starting a dedicated asyncio context event loop."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            #loop.run_until_complete(self._network_lifecycle_manager())
            loop.run_until_complete(self._network_loop())
        finally:
            loop.close()

    async def _network_loop(self):
        """Maintains the connection loop, handling automated reconselfnects on network drops."""
        while not self.stop_network_thread.is_set():
            idx = 0
            try:
                print(f"TCI Persistent: Establishing connection to {self.tci_uri}...")
                async with websockets.connect(self.tci_uri) as ws:
                    print("TCI Persistent: Connected and hot-standby active.")
                    self.rig_status = "CONNECTED"
                    await ws.send(f'TRX:{self.trx_index};')
                    while not self.stop_network_thread.is_set():
                        if self.tx_trigger.is_set():
                            self.tx_trigger.clear()
                            self.player_busy = True
                            self.tx_idx = 0
                            # ASSERT PTT INSTANTLY (The connection is already alive!)
                            await ws.send(f"TRX:{self.trx_index},true,tci;")
                            if self.txd_pre > 0.0:
                                await asyncio.sleep(self.txd_pre)

                            flushed = await self.flush_pending(ws)
                            self.tx_stream_start = time.monotonic()

                        try:
                            packet = await asyncio.wait_for(ws.recv(), timeout=0.05)
                            if isinstance(packet, bytes) and len(packet) >= 64:
                                tx_done = await self._handle_sync_packet(packet, ws)
                                if tx_done or self.abort_trigger.is_set():
                                    await ws.send(f"TRX:{self.trx_index},false;")
                                    end_flush = await self.flush_pending(ws)
                                    self.player_busy = False
                            elif isinstance(packet, str):
                                await self._handle_text_packet(packet, ws)
                        except asyncio.TimeoutError:
                            pass
                        except Exception as e:
                            raise

                        await asyncio.sleep(0.01)

            except (websockets.ConnectionClosed, OSError) as conn_err:
                # Only log error and sleep if we aren't intentionally shutting down the thread
                if not self.stop_network_thread.is_set():
                    print(f"TCI Persistent Link Dropped ({conn_err}). Reconnecting in 3s...")
                    self.player_busy = False
                    self.rig_status = "DISCONNECTED"
                    await asyncio.sleep(3)
            except Exception as e:
                print("Exception 2 in _network_loop(): {e}")
                raise

    async def _handle_sync_packet(self, packet, ws):
        header = struct.unpack(self.header_format, packet[:64])
        if header[6] == 3:  # TYPE_TX_CHRONO
            if self.tx_idx < len(self.audio_data_buffer):
                await ws.send(self.audio_data_buffer[self.tx_idx])
                self.tx_idx += 1
            else:
                elapsed = time.monotonic() - self.tx_stream_start
                if elapsed < self.audio_duration:
                    await asyncio.sleep(self.audio_duration - elapsed)

                if self.txd_post > 0:
                    await asyncio.sleep(self.txd_post)
                return True
        else:
            print(f'got weird packet: {header}')

        return False

    async def _handle_text_packet(self, packet, ws):
        packet = packet.strip()
#        print(f'TCI: {packet}')

        if packet.startswith("tx_enable:"):
            if "true" in packet:
                self.rig_status = "READY"
            else:
                self.rig_status = "STANDBY"

        if packet.startswith("trx:"):
            if "true" in packet:
                self.tx_status = "TX"
            else:
                self.tx_status = "RX"


    def load_tci_audio(self, path : str, 
                       trx_index: int = 0,
                       sample_rate: int = 48000,
                       samples_per_packet: int = 2048,
                       volume=1.0) -> list[bytes]:
        if path in self.packet_cache:
            print(f"using cached buffer for {path}")
            return self.packet_cache[path]['buffer'], self.packet_cache[path]['duration']

        FORMAT = 0 #PCM16
        TYPE_TX_AUDIO_STREAM = 2
        num_silent_packets = 6

        audio = AudioSegment.from_file(path)

        audio = (
            audio
            .set_frame_rate(sample_rate)
            .set_channels(1)
            .set_sample_width(2)   # 16-bit signed PCM
        )

        pcm = audio.raw_data

        channels = 1
        bytes_per_sample = 2
        bytes_per_packet = samples_per_packet * channels * bytes_per_sample
        duration = audio.duration_seconds
        packets = []

        for pos in range(0, len(pcm), bytes_per_packet):
            chunk = pcm[pos:pos + bytes_per_packet]

            if len(chunk) < bytes_per_packet:
                chunk = chunk.ljust(bytes_per_packet, b"\x00")

            header = struct.pack(
                self.header_format,
                trx_index,
                sample_rate,
                FORMAT,
                0,
                0,
                samples_per_packet,
                TYPE_TX_AUDIO_STREAM,
                1,
                0, 0, 0, 0, 0, 0, 0, 0
            )

            packets.append(header + chunk)

        quiet = bytes(bytes_per_packet)
        silence = header + quiet
        packets.extend([silence] * num_silent_packets)
        astr = io.BytesIO(quiet)
        a = AudioSegment.from_raw(astr, sample_width=2, 
                                  frame_rate=sample_rate,
                                  channels=1)
        duration += a.duration_seconds * num_silent_packets
        self.packet_cache[path] = { "buffer": packets, "duration": duration }
        print(f"cached {path} with duration {duration}")
        return packets, duration

    async def flush_pending(self, ws):
        flushed = 0
        while True:
            try:
                await asyncio.wait_for(ws.recv(), timeout=0.001)
                flushed += 1
            except asyncio.TimeoutError:
                return flushed
