import asyncio
import base64
import hmac
import json
import os
import threading
import time
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse

from core.agent import JarvisAgentAdapter
from core.event_bus import EventBus
from core.permissions import PermissionLevel, PermissionManager
from core.planner import TaskPlanner
from integrations.pc_control import get_system_status, open_application
from core.protocol import (
    AUDIO_CHUNK,
    AUDIO_START,
    AUDIO_STOP,
    HEARTBEAT,
    INTERRUPT,
    REGISTER,
    SESSION_ENDED,
    SESSION_STARTED,
    SPEECH_CHUNK,
    SPEECH_START,
    SPEECH_STOP,
    STATUS,
    TRANSCRIPT,
    WAKEWORD,
)
from core.session_manager import SessionManager
from stations.station_registry import StationRegistry
from memory.sqlite_memory import SQLiteMemory
from skills.skill_registry import Skill, SkillRegistry

load_dotenv()

app = FastAPI(title="Project Jarvis Central Server", version="1.0")

station_registry = StationRegistry(
    heartbeat_timeout=int(os.getenv("STATION_HEARTBEAT_TIMEOUT", "30"))
)
sessions = SessionManager()
event_bus = EventBus()
permissions = PermissionManager()
skills = SkillRegistry()
planner = TaskPlanner()
task_store = {}
memory_store = SQLiteMemory(os.getenv("JARVIS_MEMORY_DB", "memory/jarvis.sqlite3"))
agent = JarvisAgentAdapter()
connections = {}
audio_buffers = {}


def load_station_tokens():
    raw = os.getenv("STATION_TOKENS", "").strip()
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict) and parsed:
                return {str(key): str(value) for key, value in parsed.items()}
        except json.JSONDecodeError:
            pass

    token = os.getenv("JARVIS_STATION_TOKEN", "")
    if token:
        station_id = os.getenv("JARVIS_STATION_ID", "default-station")
        return {station_id: token}
    return {}


station_tokens = load_station_tokens()

def verify_station_token(station_id, token):
    expected = station_tokens.get(station_id)
    if not expected:
        return False
    return hmac.compare_digest(str(token or ""), str(expected))


def dashboard_token_valid(token):
    expected = os.getenv("JARVIS_DASHBOARD_TOKEN", "")
    if not expected:
        return False
    return hmac.compare_digest(str(token or ""), expected)


def require_dashboard(token):
    if not dashboard_token_valid(token):
        raise HTTPException(status_code=401, detail="Invalid dashboard token")


def lazy_skill(skill_id):
    def handler(*args, **kwargs):
        import main as jarvis
        return getattr(jarvis, skill_id)(*args, **kwargs)
    return handler


skills.register(Skill("system_status", "Get local system status", get_system_status, "safe", {}))
skills.register(Skill("open_application", "Open a local application", open_application, "confirm", {"application": "string"}))

for skill_id, description, permission_level, parameters in (
    ("get_time", "Get the local date and time", "safe", {}),
    ("web_search", "Search the web", "safe", {"query": "string", "max_results": "integer"}),
    ("terminal_command", "Run a bounded local shell command", "confirm", {"command": "string", "timeout": "integer"}),
    ("minecraft_command", "Run a Minecraft RCON command", "admin", {"command": "string"}),
    ("switch_language", "Switch the assistant language", "confirm", {"language": "string"}),
    ("set_activation_mode", "Switch activation mode", "confirm", {"mode": "string"}),
):
    from skills.skill_registry import Skill
    skills.register(Skill(skill_id, description, lazy_skill(skill_id), permission_level, parameters))

@app.on_event("startup")
def startup():
    migrated = memory_store.migrate_legacy_json("memory.json")
    memory_store.audit("server_started", details={"protocol": 1, "migrated_messages": migrated})

@app.get("/api/health")
def api_health():
    return {"status": "ok", "protocol": 1, "timestamp": time.time()}


@app.get("/api/status")
def api_status(token: str = Query(default="")):
    require_dashboard(token)
    return {
        "status": "ok",
        "protocol": 1,
        "connected_stations": sum(1 for station in station_registry.snapshot() if station["connected"]),
        "active_sessions": sessions.active_count(),
        "offline_mode": os.getenv("OFFLINE_MODE", "false").lower() == "true",
        "ai_provider": os.getenv("AI_PROVIDER", "ollama"),
    }

@app.get("/api/stations")
def api_stations(token: str = Query(default="")):
    require_dashboard(token)
    return {"stations": station_registry.snapshot()}

@app.get("/api/sessions")
def api_sessions(token: str = Query(default="")):
    require_dashboard(token)
    active = [session for session in sessions.sessions.values() if session["status"] == "active"]
    return {"sessions": active}

@app.get("/api/skills")
def api_skills(token: str = Query(default="")):
    require_dashboard(token)
    return {"skills": skills.snapshot()}

@app.get("/api/memory")
def api_memory(limit: int = Query(default=20, ge=1, le=200), token: str = Query(default="")):
    require_dashboard(token)
    return {"messages": memory_store.recent_messages(limit)}

@app.get("/api/tasks")
def api_tasks(token: str = Query(default="")):
    require_dashboard(token)
    return {"tasks": list(task_store.values())}


@app.post("/api/tasks/plan")
def api_plan_task(payload: dict, token: str = Query(default="")):
    require_dashboard(token)
    request = str(payload.get("request", "")).strip()
    if not request:
        raise HTTPException(status_code=400, detail="request is required")
    plan = planner.plan(request, payload.get("station_id"))
    task_store[plan["task_id"]] = plan
    memory_store.audit("task_planned", payload.get("station_id"), {"task_id": plan["task_id"]})
    return plan


@app.get("/api/logs")
def api_logs(limit: int = Query(default=100, ge=1, le=500), token: str = Query(default="")):
    require_dashboard(token)
    return {"entries": memory_store.audit_entries(limit)}

@app.post("/api/skills/{skill_id}/execute")
def execute_skill(skill_id: str, arguments: dict, token: str = Query(default="")):
    require_dashboard(token)
    skill = skills.get(skill_id)
    if skill is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    return skills.execute(skill_id, arguments)

@app.get("/", response_class=HTMLResponse)
def dashboard():
    dashboard_path = Path(__file__).with_name("dashboard") / "index.html"
    if dashboard_path.exists():
        return HTMLResponse(dashboard_path.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Jarvis Dashboard</h1>")

async def send_json(websocket, event_type, payload=None):
    await websocket.send_json({
        "protocol": 1,
        "type": event_type,
        "payload": payload or {},
        "timestamp": time.time(),
    })


async def process_transcript(websocket, station_id, text, session_id=None, source="station"):
    text = str(text or "").strip()
    if not text:
        return

    session = sessions.get(session_id) if session_id else sessions.get_for_station(station_id)
    if session is None:
        session = sessions.start(station_id)
    session_id = session["session_id"]
    sessions.touch(session_id)
    memory_store.add_message("user", text, station_id, session_id)

    loop = asyncio.get_running_loop()
    answer = await loop.run_in_executor(None, agent.ask, text)
    memory_store.add_message("assistant", answer, station_id, session_id)
    memory_store.audit("transcript_answered", station_id, {"session_id": session_id, "length": len(answer), "source": source})

    await send_json(websocket, SPEECH_START, {"session_id": session_id, "language": agent.language()})
    for chunk in agent.synthesize(answer):
        await send_json(websocket, SPEECH_CHUNK, {
            "session_id": session_id,
            "sample_rate": chunk["sample_rate"],
            "channels": chunk["channels"],
            "dtype": chunk["dtype"],
            "audio_base64": base64.b64encode(chunk["audio"]).decode("ascii"),
        })
    await send_json(websocket, SPEECH_STOP, {"session_id": session_id, "text": answer})


@app.websocket("/ws/stations/{station_id}")
async def station_socket(websocket: WebSocket, station_id: str):
    token = websocket.query_params.get("token", "")
    if not verify_station_token(station_id, token):
        await websocket.close(code=4401, reason="Invalid station credentials")
        return

    await websocket.accept()
    connections[station_id] = websocket
    station_registry.register(station_id)
    memory_store.audit("station_connected", station_id, {"transport": "websocket"})

    try:
        while True:
            message = await websocket.receive_json()
            event_type = message.get("type")
            payload = message.get("payload") or {}

            if event_type == REGISTER:
                station = station_registry.register(
                    station_id,
                    room=payload.get("room", "Unknown"),
                    transport=payload.get("transport", "websocket"),
                    metadata=payload,
                )
                await send_json(websocket, "station.registered", station)

            elif event_type == HEARTBEAT:
                station_registry.heartbeat(station_id, payload)
                await send_json(websocket, "station.heartbeat.ack", {"station_id": station_id})

            elif event_type == STATUS:
                station_registry.heartbeat(station_id, payload)

            elif event_type == WAKEWORD:
                session = sessions.start(station_id, payload.get("language"))
                station_registry.heartbeat(station_id, payload)
                memory_store.audit("wakeword", station_id, {"session_id": session["session_id"]})
                event_bus.publish(WAKEWORD, {"station_id": station_id, "session": session})
                await send_json(websocket, SESSION_STARTED, session)

            elif event_type == TRANSCRIPT:
                await process_transcript(
                    websocket,
                    station_id,
                    payload.get("text", ""),
                    payload.get("session_id"),
                    source="station_transcript",
                )

            elif event_type == AUDIO_START:
                session = sessions.get_for_station(station_id)
                session_id = payload.get("session_id") or (session["session_id"] if session else sessions.start(station_id)["session_id"])
                audio_buffers[station_id] = {"session_id": session_id, "pcm": bytearray()}
                event_bus.publish(event_type, {"station_id": station_id, "session_id": session_id})

            elif event_type == AUDIO_CHUNK:
                audio = payload.get("audio_base64", "")
                if audio and station_id in audio_buffers:
                    try:
                        audio_buffers[station_id]["pcm"].extend(base64.b64decode(audio))
                    except Exception:
                        pass
                event_bus.publish(event_type, {"station_id": station_id, "bytes": len(audio)})

            elif event_type == AUDIO_STOP:
                buffered = audio_buffers.pop(station_id, None)
                if buffered and buffered["pcm"]:
                    loop = asyncio.get_running_loop()
                    text, confidence = await loop.run_in_executor(None, agent.transcribe, bytes(buffered["pcm"]), payload.get("language") or agent.language())
                    if text:
                        await send_json(websocket, TRANSCRIPT, {
                            "text": text,
                            "confidence": confidence,
                            "session_id": buffered["session_id"],
                            "source": "central_vosk",
                        })
                        await process_transcript(
                            websocket,
                            station_id,
                            text,
                            buffered["session_id"],
                            source="central_vosk",
                        )
                event_bus.publish(event_type, {"station_id": station_id})

            elif event_type == SESSION_ENDED:
                session_id = payload.get("session_id")
                if session_id:
                    sessions.end(session_id)

            elif event_type == INTERRUPT:
                await send_json(websocket, INTERRUPT, {"session_id": payload.get("session_id")})

    except WebSocketDisconnect:
        pass
    except Exception as error:
        memory_store.audit("station_error", station_id, {"error": str(error)})
    finally:
        connections.pop(station_id, None)
        station_registry.disconnect(station_id)
        memory_store.audit("station_disconnected", station_id)
