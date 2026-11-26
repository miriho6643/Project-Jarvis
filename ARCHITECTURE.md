# Project Jarvis Architecture

## Implemented central-server boundary

The current server is a FastAPI process with authenticated WebSocket station connections.

- `main.py` remains the existing assistant adapter.
- `server.py` owns station connections, sessions, response routing and dashboard/API endpoints.
- `core/agent.py` bridges central requests to `ask_ai`, Vosk STT and Piper TTS.
- `memory/sqlite_memory.py` provides structured conversation, fact and audit storage.
- `core/session_manager.py` tracks active station sessions.
- `stations/station_registry.py` tracks station status and heartbeats.
- `core/event_bus.py` provides decoupled local events.
- `core/planner.py` creates bounded task plans.
- `core/permissions.py` and `skills/skill_registry.py` provide permission metadata and skill dispatch.
- `dashboard/index.html` shows status, stations, sessions, memory, skills, tasks and audit entries.
- `station_client.py` is a Raspberry Pi 4 prototype for local wakeword, PCM capture, reconnection and speaker playback.

## Communication protocol

The station control channel uses WebSockets. Station audio is sent as base64-encoded 16 kHz, 16-bit mono PCM frames. Central Piper speech is returned as base64-encoded PCM chunks. Station events include registration, heartbeat, wakeword, session, audio start/chunk/stop and interrupt.

## Security

Use `JARVIS_DASHBOARD_TOKEN` for dashboard/API access and `STATION_TOKENS` for individual station credentials. `JARVIS_STATION_TOKEN` is available as a single-station fallback. Terminal and application commands require explicit permission in the permission model. Run the server on a trusted network or behind TLS and a reverse proxy before exposing it beyond localhost.

## Remaining hardware and transport validation

The following still require physical or multi-process deployment validation:

- Raspberry Pi hardware testing
- Real microphone and speaker tuning
- Station local wakeword model packaging
- Interruption/barge-in latency tuning
- TLS/DTLS, certificate provisioning and credential rotation
- WebRTC for low-latency continuous audio
- MQTT status integration
- Multiple simultaneous audio sessions
- Multiroom routing and presence sensing

PCM/WebSocket is a working first transport, not the final hardware abstraction. `AudioTransport` implementations should be added only after the event protocol and station lifecycle are validated on hardware.

## Run

Start the server:

```powershell
uvicorn server:app --host 127.0.0.1 --port 8000
```

Start a station prototype:

```powershell
python station_client.py --server http://CENTRAL-SERVER:8000 --station-id livingroom --room "Living Room" --token STATION-SECRET --mode wakeword
```

Open `http://127.0.0.1:8000/` and enter `JARVIS_DASHBOARD_TOKEN` to view live server data.
