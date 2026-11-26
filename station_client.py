import argparse
import asyncio
import base64
import json
import os
import time

import numpy as np
import sounddevice as sd
import websockets


def rms(int16_audio):
    return float(np.sqrt(np.mean(np.square(int16_audio.astype(np.float32)))))


class StationClient:
    def __init__(self, server_url, station_id, token, room="Living Room", device=None, mode="wakeword"):
        self.server_url = server_url.rstrip("/")
        self.station_id = station_id
        self.token = token
        self.room = room
        self.device = device
        self.mode = mode
        self.sample_rate = 16000
        self.chunk_size = 1280
        self.websocket = None
        self.playback = None
        self.speaking = False

    def websocket_url(self):
        base = self.server_url.replace("http://", "ws://").replace("https://", "wss://")
        return f"{base}/ws/stations/{self.station_id}?token={self.token}"

    async def send(self, event_type, payload=None):
        if self.websocket:
            await self.websocket.send(json.dumps({
                "protocol": 1,
                "type": event_type,
                "payload": payload or {},
                "timestamp": time.time(),
            }))

    def stop_playback(self):
        self.speaking = False
        if self.playback is not None:
            try:
                self.playback.stop()
                self.playback.close()
            except Exception:
                pass
            self.playback = None

    def play_pcm(self, base64_audio, sample_rate=16000):
        pcm = base64.b64decode(base64_audio)
        if not self.speaking:
            self.speaking = True
            self.playback = sd.RawOutputStream(
                samplerate=int(sample_rate),
                channels=1,
                dtype="int16",
                device=self.device,
            )
            self.playback.start()
        self.playback.write(pcm)

    async def receive_loop(self):
        async for raw in self.websocket:
            message = json.loads(raw)
            event_type = message.get("type")
            payload = message.get("payload") or {}
            if event_type == "server.speech.chunk":
                self.play_pcm(payload.get("audio_base64", ""), payload.get("sample_rate", 16000))
            elif event_type == "server.speech.stop":
                if self.playback is not None:
                    await asyncio.sleep(0.1)
                    self.stop_playback()
            elif event_type == "server.interrupt":
                self.stop_playback()

    async def capture_wakeword(self):
        import openwakeword
        model = openwakeword.Model(wakeword_models=["hey_jarvis"], inference_framework="onnx")
        with sd.RawInputStream(
            samplerate=self.sample_rate,
            blocksize=self.chunk_size,
            dtype="int16",
            channels=1,
            device=self.device,
        ) as stream:
            print("Listening for Hey Jarvis...")
            while True:
                data, _ = stream.read(self.chunk_size)
                audio = np.frombuffer(data, dtype=np.int16)
                prediction = model.predict(audio)
                if prediction.get("hey_jarvis", 0) > 0.5:
                    model.reset()
                    await self.send("station.wakeword", {"language": os.getenv("DEFAULT_LANGUAGE", "de")})
                    await self.capture_utterance(stream)

    async def capture_utterance(self, stream=None):
        owns_stream = stream is None
        active_stream = stream
        if owns_stream:
            active_stream = sd.RawInputStream(
                samplerate=self.sample_rate,
                blocksize=self.chunk_size,
                dtype="int16",
                channels=1,
                device=self.device,
            )
            active_stream.start()

        await self.send("station.audio.start", {"sample_rate": self.sample_rate})
        pcm_chunks = []
        silence_chunks = 0
        speech_started = False
        try:
            while True:
                data, _ = active_stream.read(self.chunk_size)
                audio = np.frombuffer(data, dtype=np.int16)
                level = rms(audio)

                if level > 500:
                    speech_started = True
                    silence_chunks = 0
                    pcm_chunks.append(bytes(data))
                elif speech_started:
                    silence_chunks += 1
                    pcm_chunks.append(bytes(data))
                    if silence_chunks >= 10:
                        break

                if len(pcm_chunks) >= 100:
                    break

            for pcm in pcm_chunks:
                await self.send("station.audio.chunk", {"audio_base64": base64.b64encode(pcm).decode("ascii")})
            await self.send("station.audio.stop", {"sample_rate": self.sample_rate})
        finally:
            if owns_stream:
                active_stream.stop()
                active_stream.close()

    async def capture_continuous(self):
        with sd.RawInputStream(
            samplerate=self.sample_rate,
            blocksize=self.chunk_size,
            dtype="int16",
            channels=1,
            device=self.device,
        ) as stream:
            print("Always-listening mode active.")
            while True:
                if self.speaking:
                    await asyncio.sleep(0.1)
                    continue
                data, _ = stream.read(self.chunk_size)
                audio = np.frombuffer(data, dtype=np.int16)
                if rms(audio) > 500:
                    await self.capture_utterance(stream)

    async def run(self):
        while True:
            try:
                async with websockets.connect(
                    self.websocket_url(),
                    ping_interval=20,
                    ping_timeout=10,
                ) as websocket:
                    self.websocket = websocket
                    await self.send("station.register", {"room": self.room, "transport": "websocket", "mode": self.mode})
                    receiver = asyncio.create_task(self.receive_loop())
                    if self.mode == "wakeword":
                        await self.capture_wakeword()
                    else:
                        await self.capture_continuous()
            except KeyboardInterrupt:
                raise
            except Exception as error:
                print(f"Station connection lost: {error}; reconnecting in 3 seconds")
                self.websocket = None
                await asyncio.sleep(3)


def main():
    parser = argparse.ArgumentParser(description="Jarvis Raspberry Pi station client")
    parser.add_argument("--server", default=os.getenv("JARVIS_SERVER_URL", "ws://127.0.0.1:8000"))
    parser.add_argument("--station-id", default=os.getenv("JARVIS_STATION_ID", "livingroom"))
    parser.add_argument("--token", default=os.getenv("JARVIS_STATION_TOKEN", ""))
    parser.add_argument("--room", default=os.getenv("JARVIS_STATION_ROOM", "Living Room"))
    parser.add_argument("--mode", choices=["wakeword", "always_listening"], default=os.getenv("ACTIVATION_MODE", "wakeword"))
    parser.add_argument("--device", default=os.getenv("MIC_DEVICE", ""))
    arguments = parser.parse_args()

    if not arguments.token:
        raise SystemExit("JARVIS_STATION_TOKEN is required")

    device = int(arguments.device) if arguments.device.isdigit() else arguments.device or None
    client = StationClient(
        arguments.server,
        arguments.station_id,
        arguments.token,
        room=arguments.room,
        device=device,
        mode=arguments.mode,
    )
    asyncio.run(client.run())


if __name__ == "__main__":
    main()
