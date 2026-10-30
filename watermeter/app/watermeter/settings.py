"""All settings with their defaults. Two sources (2026-10-30, replaces the single-source decision of 2026-10-24):

- `Options`: the connection, from `/data/options.json`, written by Home Assistant from the add-on's Configuration tab
  (`addon/watermeter/config.yaml`; changing it restarts the add-on). `tests/test_addon_options.py` keeps the two in step.
- `Settings`: what is tuned while watching the results (capture, retention, recognition, validation), in
  `/data/settings.json`, edited on the add-on's Settings page and applied at once. `FIELDS` describes and limits every
  one of them; `settings_from_dict` checks a dict against it.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any, TypeVar, get_type_hints

T = TypeVar("T")


@dataclass
class CaptureSettings:
    interval_s: int = 60          # time between capture bursts
    frames: int = 3               # frames per burst (voted per digit)
    settle_s: float = 1.0         # wait after light on, before the first frame
    brightness: float = 1.0       # LED brightness 0.0 .. 1.0


@dataclass
class RetentionSettings:
    accepted_days: int = 7        # accepted readings keep their first frame this long
    rejected_days: int = 30       # rejected readings keep all frames this long; labelled images are never deleted


@dataclass
class RecognitionSettings:
    model: str = "haverland/dig-class11_1701_s2.tflite"  # path below the models folder (decisions.md)
    enhance_contrast: bool = True      # local contrast (CLAHE) on each digit crop before the model
    min_digit_confidence: float = 0.5  # below this a digit counts as unknown (tune with C1)
    min_mark_score: float = 0.6        # alignment: minimum template-match score per mark (tune with C3)


@dataclass
class ValidationSettings:
    reject_patterns: list[str] = field(default_factory=lambda: ["000400.000"])  # `*` = any digit, see validate/
    direction: str = "up"            # "up": never accept a lower value; "both": allow decreases (rate still applies)
    max_rate_lph: int = 5000         # 5 m³/h = the meter's Q4 overload flow
    rate_slack_l: int = 1            # always allowed on top of max rate × time (last-digit resolution)
    confirm_readings: int = 3        # readings in a row that must agree before a too-fast jump is accepted
    max_jump_l: int = 0              # beyond the max flow × time by more than this: never accepted (0 = no limit)
    min_confidence: float = 0.5      # a reading below this (minimum digit confidence) is unreadable
    flow_check: bool = False         # flow cross-check, off until real data shows it helps
    flow_check_min_increase_l: int = 5


@dataclass
class Settings:
    capture: CaptureSettings = field(default_factory=CaptureSettings)
    retention: RetentionSettings = field(default_factory=RetentionSettings)
    recognition: RecognitionSettings = field(default_factory=RecognitionSettings)
    validation: ValidationSettings = field(default_factory=ValidationSettings)


@dataclass
class Options:
    """The add-on's Configuration tab in HA (see `addon/watermeter/config.yaml`, B1): the connection only."""
    esphome_host: str = ""
    esphome_port: int = 6053
    esphome_encryption_key: str = ""
    mqtt_host: str = ""           # empty = use the broker the Supervisor provides
    mqtt_port: int = 1883
    mqtt_username: str = ""
    mqtt_password: str = ""
    log_level: str = "info"


# ---- the tunable settings: one description for the check and the Settings page ----------------------------------

@dataclass(frozen=True)
class Field:
    group: str                  # Settings attribute: capture, retention, recognition, validation
    name: str
    label: str
    kind: str                   # int, float, bool, choice, patterns, model
    lo: float | None = None
    hi: float | None = None
    choices: tuple[str, ...] = ()
    help: str = ""


FIELDS: tuple[Field, ...] = (
    Field("capture", "interval_s", "Capture interval (s)", "int", 10, 3600),
    Field("capture", "frames", "Frames per capture", "int", 1, 9, help="voted per digit"),
    Field("capture", "settle_s", "Wait after light on (s)", "float", 0, 10),
    Field("capture", "brightness", "LED brightness (0–1)", "float", 0.01, 1),
    Field("recognition", "model", "Digit model", "model"),
    Field("recognition", "enhance_contrast", "Enhance contrast", "bool", help="local contrast on each digit crop"),
    Field("recognition", "min_digit_confidence", "Min digit confidence", "float", 0, 1,
          help="below this a digit is unknown"),
    Field("recognition", "min_mark_score", "Min alignment score", "float", 0, 1),
    Field("validation", "direction", "Direction", "choice", choices=("up", "both"),
          help="up: never accept a lower value"),
    Field("validation", "max_rate_lph", "Max flow (l/h)", "int", 1, 100000,
          help="a faster rise waits for confirming readings"),
    Field("validation", "rate_slack_l", "Rate slack (l)", "int", 0, 1000),
    Field("validation", "confirm_readings", "Readings to confirm a jump", "int", 1, 20),
    Field("validation", "max_jump_l", "Max jump (l)", "int", 0, 10_000_000,
          help="above what the max flow allows in the time since the last accepted reading; more is invalid, "
               "never confirmed; 0 = no limit"),
    Field("validation", "min_confidence", "Min reading confidence", "float", 0, 1),
    Field("validation", "reject_patterns", "Reject patterns", "patterns",
          help="one per line, * = any digit, e.g. 000400.000"),
    Field("validation", "flow_check", "Flow cross-check", "bool"),
    Field("validation", "flow_check_min_increase_l", "Flow check: min rise (l)", "int", 0, 1000),
    Field("retention", "accepted_days", "Keep accepted (days)", "int", 1, 365),
    Field("retention", "rejected_days", "Keep rejected (days)", "int", 1, 365),
)
PATTERN = re.compile(r"^[0-9*.]+$")


def _check(f: Field, value: Any) -> Any:
    """The value, checked against the field (ValueError with the label otherwise)."""
    is_num = isinstance(value, (int, float)) and not isinstance(value, bool)
    if f.kind == "int" and not (isinstance(value, int) and not isinstance(value, bool)):
        raise ValueError(f"{f.label}: a whole number")
    if f.kind == "float" and not is_num:
        raise ValueError(f"{f.label}: a number")
    if f.kind in ("int", "float") and not f.lo <= value <= f.hi:
        raise ValueError(f"{f.label}: between {f.lo:g} and {f.hi:g}")
    if f.kind == "float":
        return float(value)
    if f.kind == "bool" and not isinstance(value, bool):
        raise ValueError(f"{f.label}: true or false")
    if f.kind == "choice" and value not in f.choices:
        raise ValueError(f"{f.label}: one of {', '.join(f.choices)}")
    if f.kind == "model" and (not isinstance(value, str) or not value.strip() or ".." in value):
        raise ValueError(f"{f.label}: a model file below the models folder")
    if f.kind == "patterns":
        if not isinstance(value, list) or not all(isinstance(p, str) for p in value):
            raise ValueError(f"{f.label}: a list of patterns")
        value = [p.strip() for p in value if p.strip()]
        bad = [p for p in value if not PATTERN.match(p)]
        if bad:
            raise ValueError(f"{f.label}: only digits, * and . ({bad[0]!r})")
    return value


def settings_from_dict(data: Any) -> Settings:
    """Settings from their JSON form, every value checked against `FIELDS`; missing ones keep their defaults, unknown
    ones are ignored. Raises ValueError naming the first bad field."""
    settings = Settings()
    if not isinstance(data, dict):
        raise ValueError("settings must be an object")
    for f in FIELDS:
        group = data.get(f.group)
        if isinstance(group, dict) and f.name in group:
            setattr(getattr(settings, f.group), f.name, _check(f, group[f.name]))
    return settings


def settings_to_dict(settings: Settings) -> dict:
    return asdict(settings)


def load_settings(path: Path) -> Settings:
    """The saved settings; defaults if there is no file. A damaged file raises ValueError (the caller decides)."""
    if not path.exists():
        return Settings()
    try:
        return settings_from_dict(json.loads(path.read_text(encoding="utf-8")))
    except json.JSONDecodeError as e:
        raise ValueError(f"{path.name} is not valid JSON: {e}") from e


def save_settings(path: Path, settings: Settings) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(settings_to_dict(settings), indent=2), encoding="utf-8")
    tmp.replace(path)


def _from_dict(cls: type[T], data: Any) -> T:
    """Build dataclass `cls` from a dict, recursively; missing keys keep defaults, unknown keys are ignored."""
    if not isinstance(data, dict):
        return cls()
    hints = get_type_hints(cls)
    kwargs = {}
    for f in fields(cls):
        if f.name not in data:
            continue
        typ = hints[f.name]
        value = data[f.name]
        kwargs[f.name] = _from_dict(typ, value) if is_dataclass(typ) else value
    return cls(**kwargs)


def load_options(path: Path) -> Options:
    if not path.exists():
        return Options()
    return _from_dict(Options, json.loads(path.read_text(encoding="utf-8")))
