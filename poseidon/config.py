"""Config lives in ~/.poseidon/config.json. One provider, one approval policy."""
import json
import os
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("POSEIDON_HOME", str(Path.home() / ".poseidon")))
CONFIG_PATH = CONFIG_DIR / "config.json"

# OpenAI-compatible presets. Anything with a /v1/chat/completions works.
PRESETS = {
    "ollama": {
        "label": "Ollama (local, free)",
        "base_url": "http://localhost:11434/v1",
        "api_key": "ollama",
        "model": "hermes3",
    },
    "openai": {
        "label": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "api_key": "",
        "model": "gpt-4o-mini",
    },
    "groq": {
        "label": "Groq",
        "base_url": "https://api.groq.com/openai/v1",
        "api_key": "",
        "model": "llama-3.3-70b-versatile",
    },
    "bonito": {
        "label": "Bonito Gateway (one key, every provider)",
        "base_url": "https://api.getbonito.com/v1",
        "api_key": "",
        "model": "claude-sonnet-4-6",
    },
    "custom": {
        "label": "Custom (any OpenAI-compatible endpoint)",
        "base_url": "",
        "api_key": "",
        "model": "",
    },
}

DEFAULT_CONFIG = {
    "provider": None,  # {base_url, api_key, model}
    "approvals": {
        # reads (read_file, list_dir, web_fetch) are always allowed;
        # writes and commands ask unless a rule matches.
        "rules": []  # [{"tool": "run_command", "pattern": "git *"}]
    },
}


def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            cfg = json.loads(CONFIG_PATH.read_text())
            return {**DEFAULT_CONFIG, **cfg}
        except (json.JSONDecodeError, OSError):
            pass
    return json.loads(json.dumps(DEFAULT_CONFIG))


def save_config(cfg: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2))
    try:
        os.chmod(CONFIG_PATH, 0o600)  # api keys live here
    except OSError:
        pass
