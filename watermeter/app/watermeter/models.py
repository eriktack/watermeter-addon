"""Data types passed between the stages.

Units: volume in litres (int), flow in litres per hour (int). `170861` litres is 170.861 m³ on the display.
Times are timezone-aware `datetime`s (UTC inside the add-on).

Pipeline: Frame -> (align, crop) -> crops -> Recognizer -> DigitResult per digit and frame -> vote ->
LineReading -> RawReading -> ValidatorInput -> validate -> Decision (+ new ValidatorState) -> MQTT.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

import numpy as np

UNKNOWN_DIGIT = "?"


# ---- images and regions ---------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Frame:
    """One JPEG from the camera."""
    jpeg: bytes
    captured_at: datetime
    index: int = 0  # position within one capture burst (0..N-1)


@dataclass(frozen=True)
class Box:
    """Axis-aligned rectangle in reference-image pixels; (x, y) is the top-left corner."""
    x: int
    y: int
    w: int
    h: int


@dataclass(frozen=True)
class Mark:
    """An alignment mark: a distinctive patch of the reference image (the AXIOMA logo, the `1621` text)."""
    name: str
    box: Box


@dataclass(frozen=True)
class Line:
    """One number on the display: its digit boxes left to right and how many of them are decimals."""
    digits: tuple[Box, ...]
    decimals: int


@dataclass(frozen=True)
class Regions:
    """Everything drawn on the reference image in the Regions page (C2). Stored in `/data/regions.json`."""
    reference_width: int
    reference_height: int
    marks: tuple[Mark, ...]
    volume: Line                  # 9 digits, 3 decimals on the Qalcosonic W1
    flow: Line | None = None      # second display line, m³/h


# ---- recognition ----------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class DigitResult:
    """One recognised digit. `value` is None when the model says "not a number" or is not sure enough."""
    value: int | None
    confidence: float  # 0.0 .. 1.0


@dataclass(frozen=True)
class LineReading:
    """One display line after the vote (C5)."""
    digits: tuple[DigitResult, ...]
    decimals: int

    @property
    def text(self) -> str:
        """Digits as shown on the display, `?` for unknown, with the decimal point: `000170.861`, `0001?0.861`."""
        chars = "".join(UNKNOWN_DIGIT if d.value is None else str(d.value) for d in self.digits)
        if self.decimals <= 0:
            return chars
        return chars[: len(chars) - self.decimals] + "." + chars[len(chars) - self.decimals:]

    @property
    def litres(self) -> int | None:
        """The value in thousandths of the display unit (litres for m³, l/h for m³/h); None if any digit is unknown.

        The display unit is m³ (or m³/h) with `decimals` decimals, so the integer of all digits is scaled to 3 decimals.
        """
        if any(d.value is None for d in self.digits):
            return None
        raw = int("".join(str(d.value) for d in self.digits)) if self.digits else 0
        return raw * 10 ** (3 - self.decimals) if self.decimals <= 3 else raw // 10 ** (self.decimals - 3)

    @property
    def confidence(self) -> float:
        """Minimum digit confidence (0.0 for an empty line)."""
        return min((d.confidence for d in self.digits), default=0.0)


@dataclass(frozen=True)
class RawReading:
    """What the pipeline read from one capture burst, before validation."""
    captured_at: datetime
    volume: LineReading
    flow: LineReading | None = None
    aligned: bool = True  # False when the alignment marks were not found (then volume is all unknown)


# ---- validation -----------------------------------------------------------------------------------------------

class Status(str, Enum):
    """Outcome of validating one reading. Published to HA as the Status entity (its `value`)."""
    OK = "ok"
    ALIGNMENT = "alignment"
    UNREADABLE = "unreadable"
    REJECT_LIST = "reject_list"
    NEGATIVE = "negative"
    PENDING_JUMP = "pending_jump"  # faster than the max rate; waits for N agreeing readings
    FLOW_MISMATCH = "flow_mismatch"


@dataclass(frozen=True)
class ValidatorInput:
    """One reading as the validator sees it."""
    time: datetime
    volume_l: int | None         # None if any digit is unknown
    volume_text: str             # display form with `?` for unknown digits, e.g. "000400.000"
    confidence: float            # minimum digit confidence, 0.0 .. 1.0
    flow_lph: int | None = None  # None if the flow line is unreadable or not configured
    aligned: bool = True


@dataclass(frozen=True)
class PendingReading:
    value_l: int
    time: datetime


@dataclass(frozen=True)
class ValidatorState:
    """Everything the validator remembers between readings. Saved to `/data/state.json`."""
    last_value_l: int | None = None       # last accepted volume; None until the first accepted reading
    last_time: datetime | None = None     # time of the last accepted reading
    last_flow_lph: int | None = None      # flow from the previous readable reading (for the flow cross-check)
    pending: tuple[PendingReading, ...] = field(default_factory=tuple)  # candidate jump, oldest first

    def to_dict(self) -> dict:
        """JSON-safe dict (times as ISO 8601 strings)."""
        return {
            "last_value_l": self.last_value_l,
            "last_time": self.last_time.isoformat() if self.last_time is not None else None,
            "last_flow_lph": self.last_flow_lph,
            "pending": [{"value_l": p.value_l, "time": p.time.isoformat()} for p in self.pending],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ValidatorState":
        last_time = data.get("last_time")
        return cls(
            last_value_l=data.get("last_value_l"),
            last_time=datetime.fromisoformat(last_time) if last_time else None,
            last_flow_lph=data.get("last_flow_lph"),
            pending=tuple(PendingReading(p["value_l"], datetime.fromisoformat(p["time"]))
                          for p in data.get("pending", [])),
        )


@dataclass(frozen=True)
class Decision:
    """Result of validating one reading."""
    status: Status
    value_l: int | None   # the published volume after this reading: the new value if OK, else the last accepted one
    detail: str = ""      # short human-readable explanation for the Log page, e.g. "170861 -> 400000 in 60 s"

    @property
    def accepted(self) -> bool:
        return self.status is Status.OK


# ---- image helpers --------------------------------------------------------------------------------------------

Image = np.ndarray  # decoded image, HxWx3 uint8, RGB order
