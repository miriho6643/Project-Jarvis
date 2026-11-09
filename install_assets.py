import os
import zipfile
import requests
from language_catalog import LANGUAGE_CATALOG

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(PROJECT_ROOT, "models")
VOICES_DIR = os.path.join(PROJECT_ROOT, "voices")

VOSK_MODEL_NAMES = {code: details["vosk_model"] for code, details in LANGUAGE_CATALOG.items()}
PIPER_MODEL_NAMES = {code: details["piper_path"].rsplit("/", 1)[-1] for code, details in LANGUAGE_CATALOG.items()}
VOSK_MODEL_URLS = {
    code: f"https://alphacephei.com/vosk/models/{details['vosk_model']}.zip"
    for code, details in LANGUAGE_CATALOG.items()
}
PIPER_REPO_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main/"
PIPER_VOICE_URLS = {
    code: [PIPER_REPO_BASE + details["piper_path"]]
    for code, details in LANGUAGE_CATALOG.items()
}
PIPER_VOICE_JSON_URLS = {
    code: [PIPER_REPO_BASE + details["piper_path"] + ".json"]
    for code, details in LANGUAGE_CATALOG.items()
}

def download_file(url, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    print(f"[DOWNLOAD] {url} -> {path}")
    response = requests.get(url, timeout=60, stream=True)
    response.raise_for_status()
    with open(path, "wb") as file:
        for chunk in response.iter_content(chunk_size=65536):
            if chunk:
                file.write(chunk)


def download_first_available(urls, path):
    candidates = urls if isinstance(urls, (list, tuple)) else [urls]
    last_error = None
    for url in candidates:
        try:
            download_file(url, path)
            return path
        except requests.RequestException as error:
            last_error = error
            print(f"[WARN] Download failed for {url}; trying next mirror if available.")
    if last_error is not None:
        raise last_error
    raise requests.RequestException(f"No valid download URL available for {path}")


def ensure_vosk_model(language):
    language = language.lower()
    model_name = VOSK_MODEL_NAMES[language]
    target_dir = os.path.join(MODELS_DIR, model_name)
    if os.path.isdir(target_dir) and os.path.isfile(os.path.join(target_dir, "am", "final.mdl")):
        print(f"[OK] Vosk model {language} already available at {target_dir}")
        return target_dir

    archive_path = os.path.join(MODELS_DIR, f"{model_name}.zip")
    download_file(VOSK_MODEL_URLS[language], archive_path)
    with zipfile.ZipFile(archive_path, "r") as archive:
        archive.extractall(MODELS_DIR)

    if not os.path.isdir(target_dir):
        raise FileNotFoundError(f"Vosk model extraction failed for {language}: {target_dir}")
    print(f"[OK] Installed Vosk model {language}")
    return target_dir


def ensure_piper_voice(language):
    language = language.lower()
    model_name = PIPER_MODEL_NAMES[language]
    target_path = os.path.join(VOICES_DIR, model_name)
    json_path = target_path + ".json"
    if os.path.isfile(target_path) and os.path.isfile(json_path):
        print(f"[OK] Piper voice {language} already available at {target_path}")
        return target_path

    try:
        download_first_available(PIPER_VOICE_URLS[language], target_path)
        if not os.path.isfile(json_path):
            download_first_available(PIPER_VOICE_JSON_URLS[language], json_path)
        print(f"[OK] Installed Piper voice {language}")
        return target_path
    except requests.RequestException as error:
        print(f"[WARN] Piper voice {language} could not be downloaded from the configured URL: {error}")
        print(f"[WARN] Local voice remains unavailable; continue without speech synthesis for {language}.")
        return None


def ensure_all_assets():
    print(f"[INFO] Installing assets for all {len(LANGUAGE_CATALOG)} languages; this may use several gigabytes of bandwidth and disk space.")
    for language in LANGUAGE_CATALOG:
        ensure_vosk_model(language)
        ensure_piper_voice(language)
    print("[READY] All Vosk and Piper assets are installed.")


if __name__ == "__main__":
    ensure_all_assets()
