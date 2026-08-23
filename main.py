from openai import OpenAI
import os, json, threading, time, subprocess, requests
import speech_recognition as sr
import pyttsx3
import openwakeword
from mcrcon import MCRcon # pip install mcrcon

# ========= 1. SETUP =========
client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPENROUTER_API_KEY"),
    default_headers={"HTTP-Referer": "http://localhost", "X-Title": "Jarvis Voice"}
)
MODELS = ["qwen/qwen2.5-7b-instruct:free", "meta-llama/llama-3.1-8b-instruct:free"]
MEMORY_FILE = "memory.json"
WAKEWORD_MODEL = "hey_jarvis"

# ========= HOME ASSISTANT + MINECRAFT CONFIG =========
HA_URL = "http://192.168.1.50:8123/api"
BEARER_TOKEN = "eyJhbGciOi...DEIN_TOKEN_HIER"
HEADERS = {"Authorization": f"Bearer {BEARER_TOKEN}", "content-type": "application/json"}

MC_RCON_HOST = "192.168.1.50" # IP vom Minecraft Server
MC_RCON_PORT = 25575
MC_RCON_PASSWORD = "dein_rcon_passwort" # in server.properties

tools = []
device_lock = threading.Lock()

# Memory
if os.path.exists(MEMORY_FILE):
    with open(MEMORY_FILE, "r", encoding="utf-8") as f: data = json.load(f); conversation_history = data.get("history", [{"role": "system", "content": "Du bist Jarvis. Steuere Geräte mit do/with. Für Minecraft nutze minecraft_command."}]); summary = data.get("summary", "")
else:
    conversation_history = [{"role": "system", "content": "Du bist Jarvis. Steuere Geräte mit do/with. Für Minecraft nutze minecraft_command."}]
    summary = ""

def save_memory():
    with open(MEMORY_FILE, "w", encoding="utf-8") as f: json.dump({"history": conversation_history, "summary": summary}, f, ensure_ascii=False, indent=2)

# TTS
engine = pyttsx3.init(); engine.setProperty('rate', 175)
voices = engine.getProperty('voices')
if voices: engine.setProperty('voice', voices[0].id)
def speak(text): threading.Thread(target=lambda: (engine.say(text), engine.runAndWait())).start()

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

        # Statische PC + MC Tools
        ha_functions.update({"set_volume": set_volume, "open_app": open_app, "get_time": get_time, "minecraft_command": minecraft_command})
        new_tools.extend(static_tools)
        new_tools.append({"type": "function", "function": {"name": "minecraft_command", "description": "Führt einen Befehl auf dem Minecraft Server aus. Nutze Minecraft Syntax ohne /", "parameters": {"type": "object", "properties": {"command": {"type": "string", "description": "Bsp: gamemode creative @p"}}, "required": ["command"]}}})

        with device_lock: tools = new_tools; globals().update(ha_functions)
        print(f"[UPDATE] {len(new_tools)} Tools aktiv")

    except Exception as e: print(f"[DEVICE ERROR] {e}")

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
def chat_with_fallback(messages):
    with device_lock: current_tools = tools.copy()
    for model in MODELS:
        try: res = client.chat.completions.create(model=model, messages=messages, tools=current_tools, tool_choice="auto", max_tokens=500); return res, model
        except: continue
    raise Exception("Kein Modell")

def summarize_conversation(history):
    res, _ = chat_with_fallback(history + [{"role": "user", "content": "Fasse in 4 Sätzen zusammen."}])
    return res.choices[0].message.content

def ask_ai(text):
    global conversation_history, summary
    conversation_history.append({"role": "user", "content": text})
    if len(conversation_history) > 10:
        summary = summary + "\n" + summarize_conversation(conversation_history[1:-8]) if summary else summarize_conversation(conversation_history[1:-8])
        conversation_history = [conversation_history[0]] + conversation_history[-8:]; save_memory()

    response, _ = chat_with_fallback(conversation_history)
    msg = response.choices[0].message
    if msg.tool_calls:
        conversation_history.append(msg)
        for tc in msg.tool_calls:
            result = globals()[tc.function.name](**json.loads(tc.function.arguments))
            conversation_history.append({"role": "tool", "tool_call_id": tc.id, "content": result})
        final, _ = chat_with_fallback(conversation_history); ai_message = final.choices[0].message.content
    else: ai_message = msg.content
    conversation_history.append({"role": "assistant", "content": ai_message}); save_memory(); return ai_message

# ========= 5. SPEECH LOOP =========
r = sr.Recognizer(); mic = sr.Microphone()
def listen():
    with mic as source: r.adjust_for_ambient_noise(source, 0.1); r.pause_threshold = 1.0; print("...höre zu")
    try: audio = r.listen(source, 5); text = r.recognize_google(audio, "de-DE"); print(f"Du: {text}"); return text
    except: print("Nichts verstanden"); return None

print(">>> Lade Wakeword...")
oww = openwakeword.Model(wakeword_models=[WAKEWORD_MODEL]); time.sleep(5)
print(">>> Sag 'Hey Jarvis' <<<")
while True:
    try:
        with mic as source: audio = r.listen(source)
        if oww.predict(audio.get_wav_data())[WAKEWORD_MODEL] > 0.5:
            speak("Ja?"); user_text = listen()
            if user_text: print(f"Jarvis: {ask_ai(user_text)}")
    except KeyboardInterrupt: save_memory(); break
    except Exception as e: print(e); time.sleep(1)