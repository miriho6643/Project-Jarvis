from dotenv import load_dotenv
from openai import OpenAI
import os, json, re, threading, time, subprocess, requests
import numpy as np
import speech_recognition as sr
import openwakeword
import sounddevice as sd
from piper import PiperVoice
from mcrcon import MCRcon # pip install mcrcon

# ========= 1. SETUP =========
load_dotenv()

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPENROUTER_API_KEY"),
    default_headers={"HTTP-Referer": "http://localhost", "X-Title": "Jarvis Voice"}
)
MODELS = [
    "nvidia/nemotron-3.5-lightning:free",
    "minimax/minimax-m3:free",
    "liquid/lfm-2.5-2.6b:free"
]
DECISION_MODEL = "minimax/minimax-m3:free"
MODEL_LATENCIES = {}
LATENCY_LOCK = threading.Lock()
MODEL_BASED = {
    "General": {
        "Classification": ["nvidia/nemotron-3.5-lightning:free", "google/gemma-4-26b-a4b-it:free"],
        "Q&A & Knowledge": ["minimax/minimax-m3:free", "nvidia/nemotron-3-ultra-550b-a55b:free", "z-ai/glm-5.2:free"],
        "Summarization": ["minimax/minimax-m3:free", "google/gemma-4-31b-it:free", "thinkingmachines/inkling:free"],
        "Roleplay & Fiction": ["minimax/minimax-m3:free", "thinkingmachines/inkling:free"],
        "Customer Support": ["minimax/minimax-m3:free", "z-ai/glm-5.2:free", "google/gemma-4-31b-it:free"],
        "Conversation": ["minimax/minimax-m3:free", "thinkingmachines/inkling:free", "z-ai/glm-5.2:free"],
        "Context Writing": ["minimax/minimax-m3:free", "thinkingmachines/inkling:free", "google/gemma-4-31b-it:free"],
        "Research & Reports": ["nvidia/nemotron-3-ultra-550b-a55b:free", "minimax/minimax-m3:free", "z-ai/glm-5.2:free"],
        "Math": ["nvidia/nemotron-3-ultra-550b-a55b:free", "z-ai/glm-5.2:free"],
        "Security Audit": ["z-ai/glm-5.2:free", "nvidia/nemotron-3-ultra-550b-a55b:free", "cohere/north-mini-code:free"],
        "Finance & Trading": ["nvidia/nemotron-3-ultra-550b-a55b:free", "minimax/minimax-m3:free"],
        "Translation": ["minimax/minimax-m3:free", "google/gemma-4-31b-it:free"],
        "DevOps": ["nvidia/nemotron-3-ultra-550b-a55b:free", "z-ai/glm-5.2:free", "minimax/minimax-m3:free"]
    },
    "Code": {
        "Code Generation": ["cohere/north-mini-code:free", "poolside/laguna-s-2.1:free", "minimax/minimax-m3:free"],
        "Debugging": ["cohere/north-mini-code:free", "z-ai/glm-5.2:free", "minimax/minimax-m3:free"],
        "File I/O": ["cohere/north-mini-code:free", "poolside/laguna-s-2.1:free"],
        "Shell Execution": ["poolside/laguna-s-2.1:free", "cohere/north-mini-code:free", "minimax/minimax-m3:free"],
        "Code Review": ["cohere/north-mini-code:free", "z-ai/glm-5.2:free", "nvidia/nemotron-3-ultra-550b-a55b:free"],
        "Frontend & UI": ["cohere/north-mini-code:free", "minimax/minimax-m3:free", "google/gemma-4-31b-it:free"],
        "Repo Scanning": ["poolside/laguna-s-2.1:free", "cohere/north-mini-code:free", "minimax/minimax-m3:free"],
        "SQL & Database": ["minimax/minimax-m3:free", "cohere/north-mini-code:free", "z-ai/glm-5.2:free"],
        "DevOps & Config": ["poolside/laguna-s-2.1:free", "cohere/north-mini-code:free", "nvidia/nemotron-3-ultra-550b-a55b:free"]
    },
    "Agent": {
        "Workflow Execution": ["minimax/minimax-m3:free", "nvidia/nemotron-3-ultra-550b-a55b:free", "poolside/laguna-s-2.1:free"],
        "Multi-step Planning": ["nvidia/nemotron-3-ultra-550b-a55b:free", "z-ai/glm-5.2:free", "minimax/minimax-m3:free"],
        "Web Research": ["nvidia/nemotron-3-ultra-550b-a55b:free", "minimax/minimax-m3:free", "thinkingmachines/inkling:free"],
        "Tool Dispatch": ["minimax/minimax-m3:free", "nvidia/nemotron-3.5-lightning:free", "z-ai/glm-5.2:free"],
        "Memory Extraction": ["minimax/minimax-m3:free", "google/gemma-4-31b-it:free", "nvidia/nemotron-3.5-lightning:free"]
    },
    "Data": {
        "Data Extraction": ["liquid/lfm-2.5-2.6b:free", "google/gemma-4-26b-a4b-it:free", "minimax/minimax-m3:free"],
        "Data Transformation": ["liquid/lfm-2.5-2.6b:free", "minimax/minimax-m3:free", "google/gemma-4-31b-it:free"]
    }
}

def order_models_by_latency(model_list):
    """Put measured fastest models first while preserving unknown model order."""
    with LATENCY_LOCK:
        measured = sorted(
            (model for model in model_list if model in MODEL_LATENCIES),
            key=lambda model: MODEL_LATENCIES[model]
        )
    return measured + [model for model in model_list if model not in measured]

def record_model_latency(model, elapsed):
    with LATENCY_LOCK:
        previous = MODEL_LATENCIES.get(model)
        MODEL_LATENCIES[model] = elapsed if previous is None else (previous * 0.7) + (elapsed * 0.3)
MEMORY_FILE = "memory.json"
WAKEWORD_MODEL = "hey_jarvis"

# ========= HOME ASSISTANT + MINECRAFT CONFIG =========
HA_URL = os.getenv("HA_URL") # URL des Home Assistant Servers
BEARER_TOKEN = os.getenv("BEARER_TOKEN") # Bearer Token für Authentifizierung
HEADERS = {"Authorization": f"Bearer {BEARER_TOKEN}", "content-type": "application/json"}

MC_RCON_HOST = os.getenv("MC_RCON_HOST") # IP vom Minecraft Server
MC_RCON_PORT = int(os.getenv("MC_RCON_PORT")) # Port für RCON
MC_RCON_PASSWORD = os.getenv("MC_RCON_PASSWORD") # in server.properties

MIC_ARGS = {"sample_rate": 16000, "chunk_size": 1280, "device_index": 1} # Mikrofon Nummer (0 = Standard)

tools = []
device_lock = threading.Lock()
openwakeword.utils.download_models()

DEFAULT_HISTORY = [{"role": "system", "content": "Du bist Jarvis. Steuere Geräte mit do/with. Für Minecraft nutze minecraft_command. Du darfst keine Formatierungen Listen oder Emojis nutzen da du auf Sprache antwortest."}]

# Memory
conversation_history = DEFAULT_HISTORY.copy()
summary = ""
if os.path.exists(MEMORY_FILE):
    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        conversation_history = data.get("history", DEFAULT_HISTORY)
        summary = data.get("summary", "")
    except (OSError, json.JSONDecodeError) as error:
        backup_file = MEMORY_FILE + ".corrupt"
        try:
            os.replace(MEMORY_FILE, backup_file)
            print(f"[MEMORY] Ungültige memory.json gesichert als {backup_file}: {error}")
        except OSError:
            print(f"[MEMORY] Ungültige memory.json konnte nicht gesichert werden: {error}")

def save_memory():
    temporary_file = MEMORY_FILE + ".tmp"
    with open(temporary_file, "w", encoding="utf-8") as f:
        json.dump({"history": conversation_history, "summary": summary}, f, ensure_ascii=False, indent=2)
    os.replace(temporary_file, MEMORY_FILE)

# TTS
TTS_MODEL_PATH = os.path.join(os.path.dirname(__file__), "voices", "de_DE-thorsten-medium.onnx")
tts_voice = PiperVoice.load(TTS_MODEL_PATH)
tts_lock = threading.Lock()

def speak(text):
    def synthesize_and_play():
        try:
            with tts_lock:
                audio_stream = None
                for audio_chunk in tts_voice.synthesize(text):
                    if audio_stream is None:
                        audio_stream = sd.RawOutputStream(
                            samplerate=audio_chunk.sample_rate,
                            channels=1,
                            dtype="int16"
                        )
                        audio_stream.start()
                    audio_stream.write(audio_chunk.audio_int16_bytes)
                if audio_stream is not None:
                    audio_stream.stop()
                    audio_stream.close()
        except Exception as error:
            print(f"[TTS ERROR] {error}")

    threading.Thread(target=synthesize_and_play, daemon=True).start()

# ========= 2. HA + MC TOOL GENERATOR =========
def call_ha_service(domain, service, entity_id, data={}):
    url = f"{HA_URL}/services/{domain}/{service}"
    try: r = requests.post(url, headers=HEADERS, json={"entity_id": entity_id, **data}, timeout=3); return r.status_code == 200, r.text
    except: return False, "Connection Error"

def minecraft_command(command: str):
    """Führt einen Minecraft Befehl über RCON aus. z.B. 'gamemode creative @a'"""
    try:
        with MCRcon(MC_RCON_HOST, MC_RCON_PASSWORD, port=MC_RCON_PORT) as mcr:
            resp = mcr.command(command)
            return f"Befehl ausgeführt: {resp}"
    except Exception as e:
        return f"Fehler bei RCON: {e}"

def generate_ha_tools():
    global tools
    new_tools = []; ha_functions = {}
    try:
        devices = requests.get(f"{HA_URL}/states", headers=HEADERS, timeout=5).json()
        print(f"[UPDATE] Lade {len(devices)} Geräte...")

        for device in devices:
            entity_id = device["entity_id"]; friendly_name = device["attributes"].get("friendly_name", entity_id)
            domain = entity_id.split(".")[0]; safe_name = entity_id.replace(".", "_")

            def make_controller(entity, domain, name):
                def device_controller(do: str, with_val):
                    if domain == "light":
                        if do == "state":
                            state = "turn_on" if str(with_val).lower() == "on" else "turn_off"
                            ok,_ = call_ha_service("light", state, entity); return f"{name} {with_val}" if ok else "Fehler"
                        elif do == "dim":
                            brightness = max(1, min(255, int(int(with_val) * 2.55)))
                            ok,_ = call_ha_service("light", "turn_on", entity, {"brightness": brightness}); return f"{name} auf {with_val}%" if ok else "Fehler"
                    elif domain == "switch":
                        if do == "state":
                            state = "turn_on" if str(with_val).lower() == "on" else "turn_off"
                            ok,_ = call_ha_service("switch", state, entity); return f"{name} {with_val}" if ok else "Fehler"
                    elif domain == "cover":
                        if do == "state":
                            w = str(with_val).lower()
                            service = "open_cover" if w in ["on", "open"] else "close_cover" if w in ["off", "close"] else "stop_cover"
                            ok,_ = call_ha_service("cover", service, entity); return f"{name} {w}" if ok else "Fehler"
                        elif do == "position":
                            pos = max(0, min(100, int(with_val)))
                            ok,_ = call_ha_service("cover", "set_cover_position", entity, {"position": pos}); return f"{name} auf {pos}%" if ok else "Fehler"
                    elif domain == "climate":
                        if do == "state":
                            mode = "heat" if str(with_val).lower() == "on" else "off"
                            ok,_ = call_ha_service("climate", "set_hvac_mode", entity, {"hvac_mode": mode}); return f"{name} {with_val}" if ok else "Fehler"
                        elif do == "temp":
                            temp = float(with_val)
                            ok,_ = call_ha_service("climate", "set_temperature", entity, {"temperature": temp}); return f"{name} auf {temp} Grad" if ok else "Fehler"
                    elif domain == "fan":
                        if do == "state":
                            state = "turn_on" if str(with_val).lower() == "on" else "turn_off"
                            ok,_ = call_ha_service("fan", state, entity); return f"{name} {with_val}" if ok else "Fehler"
                        elif do == "speed":
                            speed = max(0, min(100, int(with_val)))
                            ok,_ = call_ha_service("fan", "set_percentage", entity, {"percentage": speed}); return f"{name} auf {speed}%" if ok else "Fehler"
                    elif domain == "media_player":
                        if do == "state":
                            w = str(with_val).lower()
                            service = "media_play" if w == "play" else "media_pause" if w == "pause" else "media_stop"
                            ok,_ = call_ha_service("media_player", service, entity); return f"{name} {w}" if ok else "Fehler"
                        elif do == "volume":
                            vol = max(0.0, min(1.0, float(with_val) / 100))
                            ok,_ = call_ha_service("media_player", "volume_set", entity, {"volume_level": vol}); return f"{name} Lautstärke {with_val}%" if ok else "Fehler"
                    return f"Befehl {do} wird für {name} nicht unterstützt."
                device_controller.__name__ = safe_name
                return device_controller

            ha_functions[safe_name] = make_controller(entity_id, domain, friendly_name)

            if domain == "light":
                desc = f"{friendly_name}. do: state[on/off] oder dim[1-100]"; params = {"type": "object", "properties": {"do": {"enum": ["state", "dim"]}, "with": {}}, "required": ["do", "with"]}
            elif domain == "switch":
                desc = f"{friendly_name}. do: state[on/off]"; params = {"type": "object", "properties": {"do": {"enum": ["state"]}, "with": {"enum": ["on", "off"]}}, "required": ["do", "with"]}
            elif domain == "cover":
                desc = f"{friendly_name} Rollo. do: state[open/close/stop] oder position[0-100]"; params = {"type": "object", "properties": {"do": {"enum": ["state", "position"]}, "with": {}}, "required": ["do", "with"]}
            elif domain == "climate":
                desc = f"{friendly_name} Heizung/Klima. do: state[on/off] oder temp"; params = {"type": "object", "properties": {"do": {"enum": ["state", "temp"]}, "with": {}}, "required": ["do", "with"]}
            elif domain == "fan":
                desc = f"{friendly_name} Lüfter. do: state[on/off] oder speed[0-100]"; params = {"type": "object", "properties": {"do": {"enum": ["state", "speed"]}, "with": {}}, "required": ["do", "with"]}
            elif domain == "media_player":
                desc = f"{friendly_name} Lautsprecher/TV. do: state[play/pause/stop] oder volume[0-100]"; params = {"type": "object", "properties": {"do": {"enum": ["state", "volume"]}, "with": {}}, "required": ["do", "with"]}
            else: continue
    
            new_tools.append({"type": "function", "function": {"name": safe_name, "description": desc, "parameters": params}})
    except Exception as e: print(f"[DEVICE ERROR] {e}")

    try:

        # Statische PC + MC Tools
        ha_functions.update({"set_volume": set_volume, "open_app": open_app, "get_time": get_time, "minecraft_command": minecraft_command})
        new_tools.extend(static_tools)
        new_tools.append({"type": "function", "function": {"name": "minecraft_command", "description": "Führt einen Befehl auf dem Minecraft Server aus. Nutze Minecraft Syntax ohne /", "parameters": {"type": "object", "properties": {"command": {"type": "string", "description": "Bsp: gamemode creative @p"}}, "required": ["command"]}}})

        with device_lock: tools = new_tools; globals().update(ha_functions)
        print(f"[UPDATE] {len(new_tools)} Tools aktiv")

    except Exception as e: print(f"[ERROR] {e}")

def device_updater():
    while True: generate_ha_tools(); time.sleep(600)
threading.Thread(target=device_updater, daemon=True).start()

# ========= 3. STATISCHE PC FUNKTIONEN =========
def set_volume(level: int):
    level = max(0, min(100, level))
    try:
        if "win" in os.sys.platform: subprocess.run(["nircmd.exe", "setsysvolume", str(int(level * 655.35))])
        else: subprocess.run(["amixer", "set", "Master", f"{level}%"])
        return f"Lautstärke {level}%"
    except: return "Fehler"

def open_app(app_name: str):
    try:
        if "win" in os.sys.platform: subprocess.Popen(["start", app_name], shell=True)
        else: subprocess.Popen([app_name])
        return f"Öffne {app_name}"
    except: return "Fehler"

def get_time(): return time.strftime("Es ist %H:%M am %d.%m.%Y")

static_tools = [
    {"type": "function", "function": {"name": "set_volume", "description": "PC Lautstärke", "parameters": {"type": "object", "properties": {"level": {"type": "integer"}}, "required": ["level"]}}},
    {"type": "function", "function": {"name": "open_app", "description": "Programm öffnen", "parameters": {"type": "object", "properties": {"app_name": {"type": "string"}}, "required": ["app_name"]}}},
    {"type": "function", "function": {"name": "get_time", "description": "Uhrzeit", "parameters": {"type": "object", "properties": {}}}}
]

# ========= 4. CORE KI LOGIK =========
TASK_KEYWORDS = {
    "Code": {
        "Code Generation": ("code", "programm", "implement", "schreib", "funktion", "python", "script"),
        "Debugging": ("debug", "fehler", "bug", "funktioniert nicht", "traceback", "exception"),
        "File I/O": ("datei", "file", "lesen", "schreiben", "speichern", "ordner"),
        "Shell Execution": ("terminal", "shell", "powershell", "befehl", "command", "ausführen"),
        "Code Review": ("code review", "prüfe den code", "review", "verbessere den code"),
        "Frontend & UI": ("frontend", "website", "webseite", "html", "css", "ui", "interface"),
        "Repo Scanning": ("repository", "repo", "codebase", "projekt durchsuchen"),
        "SQL & Database": ("sql", "datenbank", "database", "query", "tabelle"),
        "DevOps & Config": ("docker", "deploy", "devops", "config", "konfiguration", "ci/cd")
    },
    "Agent": {
        "Workflow Execution": ("workflow", "ablauf", "erledige", "automatisiere", "schritte"),
        "Multi-step Planning": ("plane", "plan", "mehrere schritte", "strategie"),
        "Web Research": ("recherchiere", "recherche", "websuche", "internet", "quellen"),
        "Tool Dispatch": ("schalte", "öffne", "starte", "steuere", "minecraft", "home assistant"),
        "Memory Extraction": ("merke dir", "erinnere dich", "speichere", "memory", "erinnerung")
    },
    "Data": {
        "Data Extraction": ("extrahiere", "extract", "daten aus", "parse", "strukturiere"),
        "Data Transformation": ("konvertiere", "transformiere", "csv", "json", "formatieren", "umwandeln")
    },
    "General": {
        "Classification": ("klassifiziere", "kategorisiere", "ordne zu", "label"),
        "Q&A & Knowledge": ("was ist", "wer ist", "erkläre", "warum", "wissen"),
        "Summarization": ("zusammenfassung", "zusammenfasse", "fasse zusammen", "kurz machen"),
        "Roleplay & Fiction": ("rollenspiel", "geschichte", "fiction", "fantasie", "charakter"),
        "Customer Support": ("kunden", "support", "beschwerde", "ticket"),
        "Conversation": ("unterhalte", "gespräch", "rede mit mir", "hallo"),
        "Context Writing": ("schreibe einen", "formuliere", "brief", "email", "text verfassen"),
        "Research & Reports": ("bericht", "analyse", "untersuche", "research"),
        "Math": ("rechne", "mathematik", "mathe", "gleichung", "prozent"),
        "Security Audit": ("sicherheit", "security", "vulnerability", "schwachstelle", "audit"),
        "Finance & Trading": ("finanzen", "aktie", "trading", "investment", "börse"),
        "Translation": ("übersetze", "übersetzung", "translate", "sprache"),
        "DevOps": ("server", "deployment", "monitoring", "logs")
    }
}

def select_models(text):
    """Use a free AI model to select the ranked models for the user's request."""
    available_tasks = {
        group: list(tasks.keys()) for group, tasks in MODEL_BASED.items()
    }
    decision_prompt = (
        "Ordne die Benutzeranfrage genau einer Gruppe und einer Aufgabe zu. "
        "Waehle ausschliesslich aus dieser JSON-Taxonomie: "
        f"{json.dumps(available_tasks, ensure_ascii=True)}. "
        "Antworte ausschliesslich als JSON mit den Schluesseln group und task."
    )
    try:
        response = client.chat.completions.create(
            model=DECISION_MODEL,
            messages=[
                {"role": "system", "content": decision_prompt},
                {"role": "user", "content": text}
            ],
            max_tokens=100
        )
        decision_message = response.choices[0].message
        decision_text = decision_message.content or getattr(decision_message, "reasoning", "") or ""
        decision = parse_model_decision(decision_text, available_tasks)
        group = decision["group"]
        task = decision["task"]
        if group in MODEL_BASED and task in MODEL_BASED[group]:
            selected_models = order_models_by_latency(MODEL_BASED[group][task])
            print(f"[DECISION] {group} / {task}: {', '.join(selected_models)}")
            return selected_models
    except Exception as error:
        print(f"[DECISION ERROR] {error}")

    # Keep the assistant usable when the decision model is unavailable.
    normalized = text.casefold()
    scores = []
    for group, tasks in TASK_KEYWORDS.items():
        for task, keywords in tasks.items():
            score = sum(1 for keyword in keywords if keyword.casefold() in normalized)
            if score:
                scores.append((score, group, task))

    if not scores:
        group, task = "General", "Conversation"
    else:
        _, group, task = max(scores, key=lambda match: match[0])

    selected_models = order_models_by_latency(MODEL_BASED[group][task])
    print(f"[ROUTER] {group} / {task}: {', '.join(selected_models)}")
    return selected_models

def parse_model_decision(decision_text, available_tasks):
    """Parse strict JSON and common free-model response variants safely."""
    decision_text = decision_text.strip()
    try:
        decision = json.loads(decision_text)
    except json.JSONDecodeError:
        json_match = re.search(r"\{[^{}]*\}", decision_text, re.DOTALL)
        if json_match:
            decision = json.loads(json_match.group(0))
        else:
            group_match = re.search(r"(?:group|gruppe)\s*[:=]\s*[`\"']?([^`\"'\n,]+)", decision_text, re.IGNORECASE)
            task_match = re.search(r"(?:task|aufgabe)\s*[:=]\s*[`\"']?([^`\"'\n]+)", decision_text, re.IGNORECASE)
            if not group_match or not task_match:
                raise ValueError("Decision model returned no usable group/task")
            decision = {"group": group_match.group(1).strip(), "task": task_match.group(1).strip()}

    group = str(decision.get("group", "")).strip()
    task = str(decision.get("task", "")).strip()
    if group not in available_tasks or task not in available_tasks[group]:
        raise ValueError(f"Invalid decision: {group} / {task}")
    return {"group": group, "task": task}

def chat_with_fallback(messages, model_list=None):
    with device_lock: current_tools = tools.copy()
    candidates = list(model_list or [])
    candidates.extend(model for model in MODELS if model not in candidates)
    last_error = None
    for model in order_models_by_latency(candidates):
        started = time.perf_counter()
        try:
            res = client.chat.completions.create(model=model, messages=messages, tools=current_tools, tool_choice="auto", max_tokens=500)
            record_model_latency(model, time.perf_counter() - started)
            return res, model
        except Exception as error:
            last_error = error
            continue
    raise Exception(f"Kein Modell verfügbar: {last_error}")

def summarize_conversation(history):
    res, _ = chat_with_fallback(history + [{"role": "user", "content": "Fasse in 4 Sätzen zusammen."}])
    return res.choices[0].message.content

def ask_ai(text):
    global conversation_history, summary
    model_list = select_models(text)
    conversation_history.append({"role": "user", "content": text})
    if len(conversation_history) > 10:
        summary = summary + "\n" + summarize_conversation(conversation_history[1:-8]) if summary else summarize_conversation(conversation_history[1:-8])
        conversation_history = [conversation_history[0]] + conversation_history[-8:]; save_memory()

    response, _ = chat_with_fallback((conversation_history + [{"role": "summary", "content": summary}]), model_list)
    msg = response.choices[0].message
    if msg.tool_calls:
        conversation_history.append(msg.model_dump(exclude_none=True))
        for tc in msg.tool_calls:
            result = globals()[tc.function.name](**json.loads(tc.function.arguments))
            conversation_history.append({"role": "tool", "tool_call_id": tc.id, "content": result})
        final, _ = chat_with_fallback(conversation_history, model_list); ai_message = final.choices[0].message.content
    else: ai_message = msg.content
    conversation_history.append({"role": "assistant", "content": ai_message}); save_memory(); return ai_message

# ========= 5. SPEECH LOOP =========
r = sr.Recognizer()
def listen(timeout=60):
    try:
        with sr.Microphone(**MIC_ARGS) as source:
            r.adjust_for_ambient_noise(source, duration=0.1)
            print("...höre zu")

            r.pause_threshold = 1.0
            r.phrase_threshold = 0.3
            r.non_speaking_duration = 1.0

            audio = r.listen(
                source,
                timeout=timeout,
                phrase_time_limit=20
            )

        text = r.recognize_google(audio, language="de-DE")
        print(f"Du: {text}")
        return text

    except sr.WaitTimeoutError:
        print("Keine Sprache erkannt")
        return None

    except sr.UnknownValueError:
        print("Nichts verstanden")
        return None

    except sr.RequestError as e:
        print(f"Spracherkennung nicht erreichbar: {e}")
        return None

    except Exception as e:
        print(f"[MIC ERROR] {e}")
        return None

if __name__ == "__main__":
    print(">>> Lade Wakeword...")
    oww = openwakeword.Model(wakeword_models=[WAKEWORD_MODEL], inference_framework="onnx"); time.sleep(5)
    print(">>> Sag 'Hey Jarvis' <<<")
    while True:
        try:
            with sr.Microphone(**MIC_ARGS) as source:
                # Wakeword detection must process short, continuous 16 kHz PCM frames.
                while True:
                    audio_bytes = source.stream.read(MIC_ARGS["chunk_size"])
                    audio_data = np.frombuffer(audio_bytes, dtype=np.int16)
                    if len(audio_data) != MIC_ARGS["chunk_size"]:
                        continue

                    prediction = oww.predict(audio_data)
                    if prediction.get(WAKEWORD_MODEL, 0) > 0.5:
                        print(">>> Wakeword erkannt! <<<")
                        prediction = {}
                        oww.reset()
                        break

            try:
                user_text = listen()

                if user_text:
                    answer = ask_ai(user_text)
                    print(f"Jarvis: {answer}")
                    speak(answer)

            finally:
                prediction = {}
                oww.reset()

        except KeyboardInterrupt:
            save_memory()
            break

        except Exception as e:
            print(f"[ERROR] {e}")
            time.sleep(1)
