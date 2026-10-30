"""All settings with their defaults.

One source (simplified 2026-10-24, task S2): `/data/options.json`, written by Home Assistant from the add-on's
Configuration tab, which renders a form from `addon/watermeter/config.yaml`. Read-only for the add-on; changing it in
HA restarts the add-on. Mapped to the flat `Options`; `settings_from_options` builds the grouped `Settings` the rest
of the code uses. `tests/test_addon_options.py` keeps `Options`, the defaults below and `config.yaml` in step.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, fields, is_dataclass
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
    """The add-on's Configuration tab in HA (see `addon/watermeter/config.yaml`, B1)."""
    esphome_host: str = ""
    esphome_port: int = 6053
    esphome_encryption_key: str = ""
    mqtt_host: str = ""           # empty = use the broker the Supervisor provides
    mqtt_port: int = 1883
    mqtt_username: str = ""
    mqtt_password: str = ""
    log_level: str = "info"
    # capture
    capture_interval_s: int = 60
    capture_frames: int = 3
    capture_settle_s: float = 1.0
    light_brightness_pct: int = 100          # Settings.capture.brightness = pct / 100
    # retention
    keep_accepted_days: int = 7
    keep_rejected_days: int = 30
    # recognition
    model: str = "haverland/dig-class11_1701_s2.tflite"
    enhance_contrast: bool = True
    min_digit_confidence: float = 0.5
    min_mark_score: float = 0.6
    # validation
    reject_patterns: list[str] = field(default_factory=lambda: ["000400.000"])
    direction: str = "up"                    # "up" or "both"
    max_rate_m3h: float = 5.0                # Settings.validation.max_rate_lph = round(m3h * 1000)
    rate_slack_l: int = 1
    confirm_readings: int = 3
    min_confidence: float = 0.5
    flow_check: bool = False
    flow_check_min_increase_l: int = 5


def settings_from_options(options: Options) -> Settings:
    """The grouped Settings for the given Options (pure). Every Settings field comes from the Option of the same
    meaning; with default Options the result equals `Settings()`. Conversions: brightness = light_brightness_pct / 100,
    max_rate_lph = round(max_rate_m3h * 1000), reject_patterns copied (a new list), patterns stripped of spaces and
    empty ones dropped."""
    return Settings(
        capture=CaptureSettings(interval_s=options.capture_interval_s, frames=options.capture_frames,
                                settle_s=options.capture_settle_s,
                                brightness=options.light_brightness_pct / 100),
        retention=RetentionSettings(accepted_days=options.keep_accepted_days,
                                    rejected_days=options.keep_rejected_days),
        recognition=RecognitionSettings(model=options.model, enhance_contrast=options.enhance_contrast,
                                        min_digit_confidence=options.min_digit_confidence,
                                        min_mark_score=options.min_mark_score),
        validation=ValidationSettings(
            reject_patterns=[p.strip() for p in options.reject_patterns if p.strip()],
            direction=options.direction,
            max_rate_lph=round(options.max_rate_m3h * 1000),
            rate_slack_l=options.rate_slack_l,
            confirm_readings=options.confirm_readings,
            min_confidence=options.min_confidence,
            flow_check=options.flow_check,
            flow_check_min_increase_l=options.flow_check_min_increase_l,
        ),
    )


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
