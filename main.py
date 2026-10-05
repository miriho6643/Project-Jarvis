from dotenv import load_dotenv
from openai import OpenAI
import os, json, re, threading, time, subprocess, requests
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlencode, urlparse, unquote
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
DECISION_MODELS = [DECISION_MODEL]
DECISION_MODELS_BACKUP = [DECISION_MODEL, "nvidia/nemotron-3.5-lightning:free"]
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
MODEL_BASED_BACKUP = {
    group: {task: model_ids.copy() for task, model_ids in tasks.items()}
    for group, tasks in MODEL_BASED.items()
}

MODEL_CATALOG_LOCK = threading.RLock()
TASK_MODEL_HINTS = {
    "Classification": ("classification", "classify", "categorization"),
    "Q&A & Knowledge": ("question answering", "knowledge", "factual", "reasoning"),
    "Summarization": ("summarization", "summary", "long context"),
    "Roleplay & Fiction": ("roleplay", "creative writing", "storytelling"),
    "Customer Support": ("customer support", "customer service", "conversation"),
    "Conversation": ("chat", "conversation", "instruction following"),
    "Context Writing": ("writing", "content generation", "long context"),
    "Research & Reports": ("research", "analysis", "report", "reasoning"),
    "Math": ("mathematics", "math", "numerical reasoning"),
    "Security Audit": ("security", "code analysis", "vulnerability"),
    "Finance & Trading": ("finance", "financial", "quantitative"),
    "Translation": ("translation", "multilingual"),
    "DevOps": ("devops", "infrastructure", "deployment", "coding"),
    "Code Generation": ("code generation", "coding", "programming", "software engineering"),
    "Debugging": ("debugging", "code analysis", "software engineering"),
    "File I/O": ("file handling", "coding", "tool use"),
    "Shell Execution": ("terminal", "command line", "tool use", "coding"),
    "Code Review": ("code review", "coding", "software engineering"),
    "Frontend & UI": ("frontend", "web development", "user interface", "coding"),
    "Repo Scanning": ("repository", "codebase", "coding", "long context"),
    "SQL & Database": ("sql", "database", "data analysis", "coding"),
    "DevOps & Config": ("devops", "configuration", "coding", "tool use"),
    "Workflow Execution": ("workflow", "agent", "tool use", "function calling"),
    "Multi-step Planning": ("planning", "reasoning", "agent"),
    "Web Research": ("web research", "search", "reasoning", "agent"),
    "Tool Dispatch": ("tool use", "function calling", "agent"),
    "Memory Extraction": ("information extraction", "structured data", "long context"),
    "Data Extraction": ("data extraction", "structured output", "json"),
    "Data Transformation": ("data transformation", "structured output", "json")
}

def refresh_model_decision_list():
    """Rank up to three current free models per task, retaining curated backups."""
    global DECISION_MODEL, DECISION_MODELS, MODELS
    try:
        response = requests.get("https://openrouter.ai/api/v1/models", timeout=12)
        response.raise_for_status()
        catalog = response.json().get("data", [])
        free_models = [
            model for model in catalog
            if model.get("id", "").endswith(":free")
            and "text" in model.get("architecture", {}).get("output_modalities", [])
        ]
        if not free_models:
            raise ValueError("OpenRouter catalog contained no free text models")

        def created(model):
            try:
                return int(model.get("created", 0))
            except (TypeError, ValueError):
                return 0

        newest = sorted(free_models, key=created, reverse=True)
        by_id = {model["id"]: model for model in free_models}
        updated = {}
        for group, tasks in MODEL_BASED_BACKUP.items():
            updated[group] = {}
            for task, backup_models in tasks.items():
                task_words = tuple(
                    word.casefold() for word in re.findall(r"[a-z0-9]+", task)
                    if len(word) > 2 and word.casefold() not in {"and", "for", "the"}
                )
                hints = TASK_MODEL_HINTS.get(task, ())

                def relevance(model):
                    description = f"{model.get('name', '')} {model.get('description', '')}".casefold()
                    score = sum(3 for word in task_words if word in description)
                    score += sum(4 for hint in hints if hint in description)
                    if model["id"] in backup_models:
                        score += 5
                    parameters = model.get("supported_parameters", [])
                    if "tools" in parameters and group in ("Agent", "Code"):
                        score += 2
                    try:
                        coding_score = float(
                            model.get("benchmarks", {}).get("artificial_analysis", {}).get("coding_index") or 0
                        )
                    except (AttributeError, TypeError, ValueError):
                        coding_score = 0
                    if group == "Code":
                        score += coding_score / 25
                    return score

                matching = sorted(
                    free_models,
                    key=lambda model: (relevance(model), created(model)),
                    reverse=True
                )
                candidates = [model["id"] for model in matching[:3] if relevance(model) > 0]
                candidates.extend(model_id for model_id in backup_models if model_id in by_id)
                candidates.extend(model["id"] for model in newest if model["id"] not in candidates)
                updated[group][task] = list(dict.fromkeys(candidates))[:3]

        tool_models = sorted(
            (model for model in free_models if "tools" in model.get("supported_parameters", [])),
            key=lambda model: (
                "tool calling" in model.get("description", "").casefold()
                or "agent" in model.get("description", "").casefold(),
                created(model)
            ),
            reverse=True
        )
        with MODEL_CATALOG_LOCK:
            MODEL_BASED.clear()
            MODEL_BASED.update(updated)
            if tool_models:
                DECISION_MODELS = [model["id"] for model in tool_models[:3]]
                DECISION_MODEL = DECISION_MODELS[0]
                MODELS = DECISION_MODELS.copy()
        print(f"[MODELS] refreshed {len(free_models)} free models; decision candidates: {DECISION_MODELS}")
        return True
    except Exception as error:
        print(f"[MODELS] catalog refresh failed; keeping configured model list: {error}")
        return False

def model_catalog_refresher():
    while True:
        refresh_model_decision_list()
        time.sleep(3600)

# Replace stale baked-in IDs before Jarvis can route its first request.
refresh_model_decision_list()
threading.Thread(target=model_catalog_refresher, daemon=True).start()

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
keep_listening_event = threading.Event()
openwakeword.utils.download_models()

DEFAULT_HISTORY = [{"role": "system", "content": "Du bist Jarvis. Steuere Geräte mit do/with. Für Minecraft nutze minecraft_command. Du darfst keine Formatierungen Listen oder Emojis nutzen da du auf Sprache antwortest. Nutze nur die Sprache Deutsch und keine andere Sprache. Gib ausnahmslos eine Antwort wieder."}]

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

class DuckDuckGoResultsParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.results = []
        self._active = None
        self._field = None

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        classes = attributes.get("class", "").split()
        if tag == "a" and "result__a" in classes:
            url = attributes.get("href", "")
            parsed = urlparse(url)
            if parsed.netloc.endswith("duckduckgo.com") and parsed.path == "/l/":
                url = parse_qs(parsed.query).get("uddg", [url])[0]
            self._active = {"title": "", "url": unquote(url), "snippet": ""}
            self._field = "title"
        elif tag in ("a", "div") and "result__snippet" in classes and self.results:
            self._active = self.results[-1]
            self._field = "snippet"
    def handle_data(self, data):
        if self._active and self._field:
            self._active[self._field] += data

    def handle_endtag(self, tag):
        if self._active and tag == "a" and self._field == "title":
            if self._active["title"].strip() and self._active["url"]:
                self.results.append(self._active)
            self._active = None
            self._field = None
        elif self._field == "snippet" and tag in ("a", "div"):
            self._active = None
            self._field = None

def web_search(query: str, max_results: int = 5):
    """Search the web and return titles, snippets, and source URLs."""
    query = query.strip()
    if not query:
        return "Suchanfrage darf nicht leer sein."
    max_results = max(1, min(int(max_results), 10))
    try:
        response = requests.get(
            "https://html.duckduckgo.com/html/?" + urlencode({"q": query}),
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Jarvis/1.0"},
            timeout=12
        )
        response.raise_for_status()
        parser = DuckDuckGoResultsParser()
        parser.feed(response.text)
        results = parser.results[:max_results]
        if not results:
            return "Keine Web-Ergebnisse gefunden."
        return "\n\n".join(
            f"{index}. {item['title'].strip()}\n{item['snippet'].strip()}\n{item['url']}"
            for index, item in enumerate(results, 1)
        )
    except Exception as error:
        return f"Websuche fehlgeschlagen: {error}"

def terminal_command(command: str, timeout: int = 10):
    """Run a local Windows CMD command in the project directory with bounded output/time."""
    command = command.strip()
    if not command:
        return "CMD-Befehl darf nicht leer sein."
    timeout = max(1, min(int(timeout), 60))
    try:
        result = subprocess.run(
            [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/s", "/c", command],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False
        )
        output = "\n".join(part.strip() for part in (result.stdout, result.stderr) if part.strip())
        output = output or "Befehl erfolgreich ausgeführt, aber keine Ausgabe."
        if len(output) > 12000:
            output = output[:12000] + "\n[Ausgabe gekürzt]"
        return f"Exit-Code {result.returncode}\n{output}"
    except subprocess.TimeoutExpired:
        return f"Befehl '{command}' hat die Zeitüberschreitung von {timeout} Sekunden überschritten."
    except Exception as e:
        return f"Fehler beim Ausführen des Befehls '{command}': {e}"

def keep_listening():
    """Listen for one follow-up utterance without requiring the wakeword."""
    keep_listening_event.set()
    return "Ich höre direkt auf deine nächste Frage. Danach ist wieder das Wakeword nötig."

web_terminal_tools = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Durchsucht das aktuelle Internet nach Informationen. "
                "Nutze dieses Tool für aktuelle Nachrichten, aktuelle "
                "Software-Versionen, Preise, Fakten oder wenn ausdrücklich "
                "eine Websuche gewünscht wird."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Die Suchanfrage.",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Anzahl der Ergebnisse, 1 bis 10.",
                        "minimum": 1,
                        "maximum": 10,
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "terminal_command",
            "description": (
                "Führt einen lokalen Terminal- oder Shell-Befehl auf dem "
                "Computer aus. Nutze es für lokale Dateien, Programme, "
                "Systeminformationen, Python-Befehle und andere Shell-Aufgaben."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Der auszuführende Terminal-Befehl.",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Maximale Laufzeit in Sekunden, 1 bis 60.",
                        "minimum": 1,
                        "maximum": 60,
                    },
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "keep_listening",
            "description": (
                "Nimm genau eine weitere gesprochene Nutzereingabe ohne Wakeword entgegen. "
                "Verwende das Tool, wenn der Nutzer eine Rückfrage ankündigt oder Jarvis "
                "nach der Antwort direkt für eine Folgefrage bereit sein soll. Danach wird "
                "das normale Wakeword wieder benötigt."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
]

def generate_ha_tools():
    global tools
    new_tools = web_terminal_tools.copy(); ha_functions = {}
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
        ha_functions.update({"set_volume": set_volume, "open_app": open_app, "get_time": get_time, "minecraft_command": minecraft_command, "keep_listening": keep_listening})
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
    with MODEL_CATALOG_LOCK:
        available_tasks = {
            group: list(tasks.keys()) for group, tasks in MODEL_BASED.items()
        }
        decision_candidates = list(dict.fromkeys(DECISION_MODELS + DECISION_MODELS_BACKUP))[:3]
    decision_prompt = (
        "Classify the user's request into exactly one group and task from this taxonomy. "
        "Return only a compact JSON object with exactly the keys group and task. "
        "Example: {\"group\":\"General\",\"task\":\"Math\"}. "
        "Do not explain or use markdown. Taxonomy: "
        f"{json.dumps(available_tasks, ensure_ascii=True)}. "
    )
    decision_errors = []
    for decision_model in decision_candidates:
        try:
            response = client.chat.completions.create(
                model=decision_model,
                messages=[
                    {"role": "system", "content": decision_prompt},
                    {"role": "user", "content": text}
                ],
                max_tokens=100,
                temperature=0,
                response_format={"type": "json_object"}
            )
            decision_message = response.choices[0].message
            decision_text = decision_message.content or getattr(decision_message, "reasoning", "") or ""
            decision = parse_model_decision(decision_text, available_tasks)
            group = decision["group"]
            task = decision["task"]
            with MODEL_CATALOG_LOCK:
                configured_models = MODEL_BASED.get(group, {}).get(task, [])
            if configured_models:
                selected_models = order_models_by_latency(configured_models[:3])
                print(f"[DECISION] {group} / {task}: {', '.join(selected_models)}")
                return selected_models
        except Exception as error:
            decision_errors.append(f"{decision_model}: {error}")

    if decision_errors:
        print(f"[DECISION] AI classification unavailable; using backup router ({'; '.join(decision_errors)})")

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

    with MODEL_CATALOG_LOCK:
        configured_models = MODEL_BASED[group][task][:3]
    selected_models = order_models_by_latency(configured_models)
    print(f"[ROUTER] {group} / {task}: {', '.join(selected_models)}")
    return selected_models

def parse_model_decision(decision_text, available_tasks):
    """Normalize common decision-model schemas into a validated group/task pair."""
    decision_text = decision_text.strip()
    if not decision_text:
        raise ValueError("Decision model returned empty content")

    try:
        decision = json.loads(decision_text)
    except json.JSONDecodeError:
        json_match = re.search(r"\{[^{}]*\}", decision_text, re.DOTALL)
        if json_match:
            decision = json.loads(json_match.group(0))
        else:
            group_match = re.search(
                r"(?:group|gruppe|macro[_ ]category|category)\s*[:=]\s*[`\"']?([^`\"'\n,]+)",
                decision_text,
                re.IGNORECASE
            )
            task_match = re.search(
                r"(?:task|aufgabe|display[_ ]name|task[_ ]name)\s*[:=]\s*[`\"']?([^`\"'\n]+)",
                decision_text,
                re.IGNORECASE
            )
            if not group_match or not task_match:
                raise ValueError(f"Decision model returned no usable group/task: {decision_text[:160]!r}")
            decision = {"group": group_match.group(1).strip(), "task": task_match.group(1).strip()}

    if not isinstance(decision, dict):
        raise ValueError("Decision must be a JSON object")

    def normalize(value):
        return re.sub(r"[^a-z0-9]+", "", str(value).casefold())

    group_value = next(
        (decision[key] for key in ("group", "macro_category", "macroCategory", "category") if key in decision),
        ""
    )
    task_value = next(
        (decision[key] for key in ("task", "task_name", "taskName", "display_name", "displayName", "classification") if key in decision),
        ""
    )
    group_normalized = normalize(group_value)
    task_normalized = normalize(task_value)
    normalized_groups = {normalize(group): group for group in available_tasks}
    group = normalized_groups.get(group_normalized)

    task_matches = [
        (candidate_group, candidate_task)
        for candidate_group, candidate_tasks in available_tasks.items()
        for candidate_task in candidate_tasks
        if normalize(candidate_task) == task_normalized
    ]
    if not task_matches and task_normalized:
        task_matches = [
            (candidate_group, candidate_task)
            for candidate_group, candidate_tasks in available_tasks.items()
            for candidate_task in candidate_tasks
            if normalize(candidate_task) in task_normalized or task_normalized in normalize(candidate_task)
        ]

    if group and task_matches:
        matching_task = next((match for match in task_matches if match[0] == group), None)
        if matching_task:
            return {"group": matching_task[0], "task": matching_task[1]}
    elif not group and len(task_matches) == 1:
        return {"group": task_matches[0][0], "task": task_matches[0][1]}

    raise ValueError(f"Invalid decision fields: group={group_value!r}, task={task_value!r}")

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

    response, _ = chat_with_fallback(conversation_history, model_list)
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
            if keep_listening_event.is_set():
                keep_listening_event.clear()
            else:
                with sr.Microphone(**MIC_ARGS) as source:
                    # Wakeword detection must process short, continuous 16 kHz PCM frames.
                    while True:
                        if keep_listening_event.is_set():
                            keep_listening_event.clear()
                            print(">>> Folgefrage ohne Wakeword. <<<")
                            break

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
