🤖 Project Jarvis

> A local voice-controlled AI assistant for PC, Home Assistant and Minecraft.

Project Jarvis is a Python-based personal AI assistant designed to combine
natural voice interaction with AI-powered task routing and real-world
actions.

Jarvis listens for the wake word *"Hey Jarvis"*, converts speech to text,
selects an appropriate AI model for the requested task, executes tools when
necessary and responds using local text-to-speech.

The project is designed to become a modular personal assistant that can
control devices, interact with a PC and communicate with external services.

---

✨ Features

🎙️ Voice Interface

Jarvis is designed around hands-free voice interaction.

*Wake Word*

text
Hey Jarvis


Wake-word detection is handled locally using
[OpenWakeWord](https://github.com/dscripka/openWakeWord).

After the wake word is detected, Jarvis listens for the user's command.

🗣️ Speech Recognition

Speech is converted to text using Google's speech recognition service.

The current configuration uses:

text
Language: de-DE
Sample rate: 16 kHz
Maximum phrase length: 20 seconds


🔊 Local Text-to-Speech

Jarvis uses [Piper](https://github.com/rhasspy/piper) for local speech
synthesis.

The configured voice is:

text
de_DE-thorsten-medium.onnx


Audio is played directly through the configured audio output device.

---

🧠 AI System

Project Jarvis does not rely on a single fixed AI model.

Instead, it uses a *model routing system*.

When the user asks something, Jarvis first determines what type of task
the request represents.

For example:

text
"Schalte das Licht ein"
        ↓
Agent / Tool Dispatch
        ↓
Home Assistant tool

text
"Schreib mir eine Python-Funktion"
        ↓
Code / Code Generation
        ↓
Code-oriented model


or:

text
"Was ist Photosynthese?"
        ↓
General / Q&A & Knowledge
        ↓
Knowledge-oriented model


Model Selection

A dedicated decision model is used to classify requests into the internal
task taxonomy.

The current taxonomy contains categories such as:

- General
- Code
- Agent
- Data

with tasks including:

- Code Generation
- Debugging
- Code Review
- File I/O
- Shell Execution
- Web Research
- Workflow Execution
- Tool Dispatch
- Memory Extraction
- Data Extraction
- Data Transformation
- Q&A & Knowledge
- Summarization
- Translation
- Mathematics
- Security Auditing
- DevOps

The router then selects a ranked list of models suitable for the task.

---

⚡ Model Fallback & Latency Tracking

Jarvis keeps track of how long individual models take to respond.

Measured latency is used to reorder available models so that faster models
can be preferred over time.

If a selected model fails, Jarvis automatically tries another available
model.

This creates a basic:

text
Task Router
     ↓
Preferred Models
     ↓
Fastest known model
     ↓
Fallback model
     ↓
Fallback model


architecture.

The goal is to keep Jarvis usable even when a particular model or provider
is temporarily unavailable.

---

🛠️ Tool Calling

Jarvis supports AI function/tool calling.

This means the AI can decide that a real action needs to be performed
instead of simply generating text.

For example:

text
User:
"Mach das Wohnzimmerlicht auf 50 Prozent."

Jarvis:
→ selects the appropriate tool
→ calls the Home Assistant service
→ receives the result
→ generates a spoken response


---

🏠 Home Assistant Integration

Jarvis can connect to a Home Assistant instance.

Instead of manually defining every device, Jarvis queries:

text
/api/states


and dynamically generates tools based on the devices available.

This means adding a supported device to Home Assistant can make it
available to Jarvis without manually adding another function to the code.

Currently supported Home Assistant domains

💡 Light

Supported actions:

text
state: on / off
dim: 1-100


Example:

text
"Schalte das Licht ein."
"Dimme das Wohnzimmerlicht auf 30 Prozent."


🔌 Switch

Supported actions:

text
state: on / off


🪟 Cover

Supported actions:

text
state: open / close / stop
position: 0-100


Example:

text
"Öffne das Rollo."
"Fahre das Rollo auf 50 Prozent."


🌡️ Climate

Supported actions:

text
state: on / off
temp: temperature


Example:

text
"Schalte die Heizung ein."
"Stell die Heizung auf 21 Grad."


🌀 Fan

Supported actions:

text
state: on / off
speed: 0-100


📺 Media Player

Supported actions:

text
state: play / pause / stop
volume: 0-100


---

🖥️ PC Control

Jarvis currently exposes a small set of local PC tools.

System Volume

Jarvis can change the system volume:

text
set_volume(level)


On Windows this uses `nircmd.exe`.

On Linux-based systems it uses:

text
amixer


Application Launching

Jarvis can attempt to launch applications using:

text
open_app(app_name)


Example:

text
"Öffne Discord."


---

🎮 Minecraft Integration

Jarvis can communicate with a Minecraft server through *RCON*.

The AI has access to:

text
minecraft_command(command)


This allows Jarvis to execute Minecraft commands on the configured
server.

Example:

text
"Setze mich in den Creative-Modus."


which can result in a Minecraft command such as:

text
gamemode creative @p


Minecraft commands are sent through the configured RCON connection.

> ⚠️ Only enable RCON access on a server you control and protect the
> RCON password appropriately.

---

🧠 Memory
Jarvis maintains conversation history in:

text
memory.json


The stored data contains:

json
{
  "history": [],
  "summary": ""
}


As the conversation becomes longer, older messages are summarized and the
recent conversation is retained.

This prevents the conversation history from growing indefinitely.

The memory file is also written atomically using a temporary file before
being replaced.

If an existing `memory.json` cannot be parsed, Jarvis attempts to preserve
the corrupted file as:

text
memory.json.corrupt


---

🔄 Dynamic Device Discovery

Home Assistant devices are refreshed periodically.

The device updater runs in the background and refreshes the available
tools every:

text
10 minutes


This allows Jarvis to adapt when devices are added or removed from
Home Assistant.

---

🏗️ Architecture

The current system can be roughly represented as:

text
                 ┌──────────────────┐
                 │   Microphone     │
                 └────────┬─────────┘
                          │
                          ▼
                 ┌──────────────────┐
                 │  Wake Word       │
                 │  Hey Jarvis      │
                 └────────┬─────────┘
                          │
                          ▼
                 ┌──────────────────┐
                 │ Speech-to-Text   │
                 │    Google STT    │
                 └────────┬─────────┘
                          │
                          ▼
                 ┌──────────────────┐
                 │   Task Router    │
                 └────────┬─────────┘
                          │
                ┌─────────┴─────────┐
                ▼                   ▼
        ┌──────────────┐     ┌──────────────┐
        │   AI Model   │     │    Tools     │
        │   Routing    │     │              │
        └──────┬───────┘     │ Home Assist. │
               │             │ Minecraft    │
               ▼             │ PC Control   │
        ┌──────────────┐     └──────┬───────┘
        │  OpenRouter  │            │
        └──────┬───────┘            │
               └──────────┬─────────┘
                          ▼
                 ┌──────────────────┐
                 │   AI Response    │
                 └────────┬─────────┘
                          │
                          ▼
                 ┌──────────────────┐
                 │  Piper TTS       │
                 │  Local Voice     │
                 └────────┬─────────┘
                          │
                          ▼
                       🔊 Audio


---

📁 Project Structure

text
Project-Jarvis/
│
├── main.py
├── README.md
├── LICENSE
├── .env
│
├── voices/
│   └── de_DE-thorsten-medium.onnx
│
└── memory.json


`memory.json` and `.env` should normally be excluded from version control.

---

⚙️ Configuration

Jarvis currently expects environment variables for its external services.

Example:

env
OPENROUTER_API_KEY=your_openrouter_api_key

HA_URL=http://your-home-assistant:8123/api
BEARER_TOKEN=your_home_assistant_token

MC_RCON_HOST=your.minecraft.server
MC_RCON_PORT=25575
MC_RCON_PASSWORD=your_rcon_password


Security

**Never commit real API keys, access tokens or passwords to a public
repository.**

Add the following to `.gitignore`:

gitignore
.env
memory.json
memory.json.corrupt
memory.json.tmp


If credentials have already been committed, revoke and regenerate them.

---

📦 Dependencies

The current implementation uses Python packages including:

text
python-dotenv
openai
numpy
SpeechRecognition
openwakeword
sounddevice
piper-tts
mcrcon
requests


Install them with:

bash
pip install python-dotenv openai numpy SpeechRecognition \
    openwakeword sounddevice piper-tts mcrcon requests


---

🚀 Running Jarvis
After configuring the environment:

bash
python main.py


Jarvis initializes the wake-word model and waits for:

text
Hey Jarvis


After activation, speak a command.

Example:

text
Hey Jarvis

"Wie spät ist es?"


or:

text
Hey Jarvis

"Schalte das Wohnzimmerlicht auf 40 Prozent."


or:

text
Hey Jarvis

"Stell das Rollo auf 50 Prozent."


---

🧪 Current Status

Project Jarvis is currently an active development project.

The core voice → AI → tool → voice pipeline is already implemented.

Working architecture

- [x] Wake-word detection
- [x] German speech recognition
- [x] AI conversations
- [x] AI model routing
- [x] Model fallback
- [x] Latency-based model ordering
- [x] Function/tool calling
- [x] Home Assistant integration
- [x] Dynamic Home Assistant tools
- [x] Minecraft RCON integration
- [x] PC volume control
- [x] Application launching
- [x] Local text-to-speech
- [x] Conversation memory
- [x] Conversation summarization
- [x] Background Home Assistant device refresh

---

🛣️ Roadmap

Possible future improvements include:

- [ ] Better long-term memory
- [ ] Persistent user profiles
- [ ] More Home Assistant domains
- [ ] More PC automation
- [ ] Permission system for dangerous actions
- [ ] Better error reporting
- [ ] Configurable microphones
- [ ] Configurable wake words
- [ ] GUI
- [ ] Plugin architecture
- [ ] Better multi-step agent workflows
- [ ] Local speech recognition
- [ ] More external integrations

---

🔐 Security Considerations

Jarvis is capable of performing real actions on connected systems.

Depending on the configuration, this includes:

- controlling Home Assistant devices
- launching applications
- changing system volume
- sending commands to a Minecraft server

For this reason, Jarvis should only be run in an environment where the
configured credentials and connected services are trusted.

Do not expose Home Assistant API credentials or Minecraft RCON credentials
publicly.

---

📜 License

This project is licensed under the MIT License.

See [LICENSE](LICENSE) for details.

---

👤 Author

Created by *miriho6643*

GitHub:
https://github.com/miriho6643

Project:
https://github.com/miriho6643/Project-Jarvis

---

⭐ If you like the project, consider giving it a star.
