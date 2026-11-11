# Jarvis Voice Assistant

A personal, voice-controlled assistant for Windows. Jarvis connects to a local Ollama model or OpenRouter, supports offline speech recognition and speech output, and can call configured Home Assistant, Minecraft RCON, web search, and terminal tools.

## Features

- Local Ollama or OpenRouter chat completions
- Wake-word and microphone input
- Vosk offline speech recognition and Piper text-to-speech
- Language switching and automatic input-language detection
- Home Assistant device controls and Minecraft RCON commands
- Optional web search and local terminal commands
- Persistent conversation and language preference in `memory.json`

The language catalog includes 24 language codes with Vosk and Piper assets currently mapped in `language_catalog.py`. Actual language detection requires the relevant Vosk model to be installed; generated audio requires the corresponding Piper voice.

## Requirements

- Python 3.10 or newer
- Windows (the microphone/device setup and application launching are currently Windows-oriented)
- Ollama installed locally, or an OpenRouter API key
- A working microphone and audio output device
- Optional: Home Assistant and/or a Minecraft server with RCON enabled

## Setup

Open PowerShell in the project directory and run:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `.env` before starting Jarvis. Never commit your real `.env` file or put API keys, Home Assistant tokens, RCON passwords, or personal conversation data in Git.

For Ollama, install/start Ollama and pull the model named by `OLLAMA_MODEL`, for example:

```powershell
ollama pull gemma4:26b
```

Set `AI_PROVIDER=ollama` for local inference. To use OpenRouter instead, set `AI_PROVIDER=openrouter` and replace `AI_API_KEY` with your own key.

## Speech assets

Jarvis automatically checks/downloads assets for the active language. Switching to another language downloads its Vosk model and Piper voice on demand. Automatic language detection checks other Vosk models that are already installed locally.

To preload all catalog assets, run:

```powershell
python install_assets.py
```

This downloads models and voices for all 24 catalog languages and can use several gigabytes of bandwidth and disk space. You can instead select a smaller set, such as `LANGUAGES=de,en,pl`, in `.env`; `DEFAULT_LANGUAGE` must be included in that set.

Model files are intentionally excluded from GitHub by `.gitignore`. They are downloaded from the Vosk and Piper repositories at runtime or by the installer. Review the upstream licenses and terms for model assets before redistributing them.

## Configuration

| Variable | Purpose |
| --- | --- |
| `AI_PROVIDER` | `ollama` or `openrouter` |
| `OLLAMA_MODEL` | Local model name served by Ollama |
| `AI_API_KEY` | OpenRouter API key; keep private |
| `LANGUAGES` | `all` or comma-separated catalog codes |
| `DEFAULT_LANGUAGE` | Initial language; must be enabled in `LANGUAGES` |
| `AUTO_LANGUAGE_SWITCH` | Enable or disable automatic input-language switching |
| `AUTO_INSTALL_ASSETS` | Download a missing active language's assets automatically |
| `HA_URL`, `BEARER_TOKEN` | Optional Home Assistant API connection |
| `MC_RCON_HOST`, `MC_RCON_PORT`, `MC_RCON_PASSWORD` | Optional Minecraft RCON connection |

The assistant also stores active language and conversation history in `memory.json`, which is local and ignored by Git.

## Run

```powershell
python main.py
```

Say the configured wake word, then speak. Choose another language by asking Jarvis to switch language, or configure `DEFAULT_LANGUAGE` in `.env`. The microphone device index is currently set in `MIC_ARGS` in `main.py` and may need adjustment for your computer.

## Security notes

The `terminal_command` tool executes local shell commands. Use this assistant only with models and people you trust, and review commands before allowing them to run. Keep `.env` and `memory.json` private. If a secret was ever committed, rotate it; adding it to `.gitignore` does not remove it from Git history.

## GitHub upload

Install Git, then from the project directory:

```powershell
git init
git add .
git status
git commit -m "Prepare Jarvis project for GitHub"
git branch -M main
git remote add origin https://github.com/YOUR-USERNAME/YOUR-REPOSITORY.git
git push -u origin main
```

Before committing, inspect `git status` and confirm `.env`, `memory.json`, `models/`, and `voices/` are not staged. Choose and add a `LICENSE` file if you want to grant others permission to reuse or modify the source; no license is included by default.
