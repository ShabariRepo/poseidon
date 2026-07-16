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
        "context_window": 32768,  # conservative: local models vary widely
    },
    "openai": {
        "label": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "api_key": "",
        "model": "gpt-4o-mini",
        "context_window": 128000,
    },
    "groq": {
        "label": "Groq",
        "base_url": "https://api.groq.com/openai/v1",
        "api_key": "",
        "model": "llama-3.3-70b-versatile",
        "context_window": 131072,
    },
    "bonito": {
        "label": "Bonito Gateway (one key, every provider)",
        "base_url": "https://api.getbonito.com/v1",
        "api_key": "",
        "model": "claude-sonnet-4-6",
        "context_window": 200000,
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
    "engine": {
        # Auto-summarize the session above this estimate. Default assumes a
        # 200k-context model (Claude/GPT-4.1 class) with headroom for the reply;
        # the effective threshold is clamped to the provider's context_window
        # (see orchestrator.compact_threshold), so small-window models compact earlier.
        "compact_tokens": 198000,
        "keep_recent": 8,          # messages kept verbatim through compaction
        "auto_checkpoint": True,   # checkpoint after write/run turns
        "max_iterations": 25,      # tool-loop cap per turn
    },
    "account": {
        # link to a Bonito account (site shows your pk- key on the Poseidon page)
        "bonito_url": "https://api.getbonito.com",
        "key": "", "email": "", "name": "",
    },
    "integrations": {
        "gmail": {"email": "", "app_password": ""},   # myaccount.google.com/apppasswords
        "slack": {"bot_token": "", "default_channel": ""},
    },
}


def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            cfg = json.loads(CONFIG_PATH.read_text())
            merged = {**DEFAULT_CONFIG, **cfg}
            # migrate configs saved when 24000 was the default (pre-0.9.1):
            # anyone still on the old default gets the new one, an explicit
            # custom value is left alone.
            if (merged.get("engine") or {}).get("compact_tokens") == 24000:
                merged["engine"]["compact_tokens"] = DEFAULT_CONFIG["engine"]["compact_tokens"]
            return merged
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
