"""User settings, read from a single JSON file. Every key is optional."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_MODEL = "z-image-turbo"
DEFAULT_FORMAT = "webp"
DEFAULT_QUALITY = 82

SAMPLE_CONFIG = {
    "model": DEFAULT_MODEL,
    "output_dir": "~/Pictures/sitepix",
    "format": DEFAULT_FORMAT,
    "quality": DEFAULT_QUALITY,
    "styles": {
        "flat": {
            "suffix": "flat vector illustration, simple shapes, limited color palette, white background"
        },
        "photo": {
            "suffix": "natural light photograph, shallow depth of field, realistic detail"
        },
    },
}


class ConfigError(ValueError):
    pass


def home_dir() -> Path:
    """Folder for saved models and the job lock."""
    return Path(os.environ.get("SITEPIX_HOME", "~/.local/share/sitepix")).expanduser()


def config_path() -> Path:
    return Path(os.environ.get("SITEPIX_CONFIG", "~/.config/sitepix/config.json")).expanduser()


@dataclass
class Style:
    name: str
    prefix: str = ""
    suffix: str = ""
    lora: str = ""
    lora_scale: float = 1.0
    model: str = ""

    def apply(self, prompt: str) -> str:
        parts = [self.prefix.strip(), prompt.strip(), self.suffix.strip()]
        return ", ".join(part for part in parts if part)


@dataclass
class Config:
    model: str = DEFAULT_MODEL
    output_dir: str = "."
    format: str = DEFAULT_FORMAT
    quality: int = DEFAULT_QUALITY
    min_free_gb: float | None = None
    styles: dict[str, Style] = field(default_factory=dict)

    def style(self, name: str) -> Style:
        if name not in self.styles:
            known = ", ".join(sorted(self.styles)) or "none defined"
            raise ConfigError(f"unknown style '{name}', styles in your config: {known}")
        return self.styles[name]


def load_config(path: Path | None = None) -> Config:
    path = path or config_path()
    if not path.exists():
        return Config()
    try:
        raw = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"could not read {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"{path} must hold a JSON object")
    styles = {}
    for name, body in (raw.get("styles") or {}).items():
        if not isinstance(body, dict):
            raise ConfigError(f"style '{name}' in {path} must be a JSON object")
        styles[name] = Style(
            name=name,
            prefix=str(body.get("prefix", "")),
            suffix=str(body.get("suffix", "")),
            lora=str(body.get("lora", "")),
            lora_scale=float(body.get("lora_scale", 1.0)),
            model=str(body.get("model", "")),
        )
    min_free = raw.get("min_free_gb")
    return Config(
        model=str(raw.get("model", DEFAULT_MODEL)),
        output_dir=str(raw.get("output_dir", ".")),
        format=str(raw.get("format", DEFAULT_FORMAT)).lower(),
        quality=int(raw.get("quality", DEFAULT_QUALITY)),
        min_free_gb=float(min_free) if min_free is not None else None,
        styles=styles,
    )


def write_sample_config(path: Path | None = None) -> Path:
    path = path or config_path()
    if path.exists():
        raise ConfigError(f"{path} already exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(SAMPLE_CONFIG, indent=2) + "\n")
    return path
