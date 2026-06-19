"""Persistent host settings (stored in runtime/settings.json, gitignored).

Holds host-level choices the user can change live: the conductor's model and PI's
model/provider. Per-agent models are NOT stored here — an agent's `model:` in its
`agent.yaml` is the source of truth, edited in place by `/settings model`.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from agentspace.common import paths

DEFAULT_MODEL = "claude-sonnet-4-6"

# Friendly aliases offered in setup / accepted by /settings.
KNOWN_MODELS = {
    "opus": "claude-opus-4-8",
    "sonnet": "claude-sonnet-4-6",
    "haiku": "claude-haiku-4-5",
}


def resolve_model(name: str) -> str:
    return KNOWN_MODELS.get(name.strip().lower(), name.strip())


@dataclass
class Settings:
    conductor_model: str = DEFAULT_MODEL
    pi_model: str = ""        # "" → let PI pick its default
    pi_provider: str = "anthropic"
    # Telegram bridge / notifications (stored here, gitignored, like other settings).
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""


def settings_file(root: Path) -> Path:
    return paths.runtime_dir(root) / "settings.json"


def is_first_run(root: Path) -> bool:
    return not settings_file(root).exists()


def load(root: Path) -> Settings:
    f = settings_file(root)
    if f.exists():
        try:
            data = json.loads(f.read_text())
            return Settings(**{k: v for k, v in data.items() if k in Settings.__dataclass_fields__})
        except Exception:  # noqa: BLE001
            pass
    return Settings()


def save(root: Path, s: Settings) -> None:
    f = settings_file(root)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(asdict(s), indent=2))
