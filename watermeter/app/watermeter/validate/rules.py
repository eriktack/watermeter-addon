"""Validation rules (plan §6). The tests in `tests/test_validator.py` are the specification (task D1a/D1b).

Rules, applied in this order to one `ValidatorInput`:

1. ALIGNMENT   `aligned` is False.
2. UNREADABLE  `volume_l` is None, or `confidence` < `min_confidence`.
3. REJECT_LIST `volume_text` matches one of `reject_patterns` (see `matches_reject_pattern`).
   Readings rejected by 1–3 leave the state completely unchanged (also `pending` and `last_flow_lph`).
   From here on the reading is readable: `last_flow_lph` in the returned state is set to the input's `flow_lph`
   (also when it is None), whatever the outcome.
4. First reading (state has no `last_value_l`): OK, becomes the base.
5. NEGATIVE    direction "up" and `volume_l` < `last_value_l`. State unchanged except `last_flow_lph`.
5b. TOO_LARGE  `max_jump_l` > 0 and the change (as `delta` in rule 6) exceeds what rule 6 allows by more than
               `max_jump_l`: delta > allowed + max_jump_l. It grows with the time since the last accepted reading
               like the rate does, so a long offline time is no problem. Never confirmed by later readings; only
               "set current value" gets past it. State unchanged except `last_flow_lph`.
6. Rate        delta = |volume_l - last_value_l| (direction "both") or volume_l - last_value_l ("up");
               allowed = max_rate_lph × hours since `last_time` + rate_slack_l (hours < 0 count as 0).
               delta <= allowed → continue to 7. Otherwise → PENDING_JUMP handling (below).
7. FLOW_MISMATCH (only if `flow_check`) the volume rose by >= `flow_check_min_increase_l` while both the input's
               `flow_lph` and the state's `last_flow_lph` are exactly 0. State unchanged except `last_flow_lph`.
8. OK          state: last_value_l = volume_l, last_time = time, pending cleared.

PENDING_JUMP handling (rate exceeded):
- The candidate "agrees" with the newest pending reading if, compared with it, it passes the direction rule and the
  rate rule (same formulas, using the pending reading's value and time instead of the last accepted ones).
- No pending, or not agreeing: pending becomes just this reading. Agreeing: it is appended.
- If pending now holds `confirm_readings` readings: OK, the reading is accepted as the new value (last_value_l,
  last_time), pending cleared. Otherwise PENDING_JUMP, `value_l` stays the last accepted one.
- Only an OK reading clears pending; rejections by rules 1–3, 5, 5b and 7 leave it as it is.

`Decision.value_l` is always the published value after this reading: the new value when OK, otherwise the last
accepted value (None before the first accepted reading).
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from ..models import Decision, PendingReading, Status, ValidatorInput, ValidatorState
from ..settings import ValidationSettings


def matches_reject_pattern(volume_text: str, pattern: str) -> bool:
    """True if the reading matches the pattern.

    Both are compared with the decimal point removed. The pattern must then have the same number of characters as
    the reading; each pattern character is a digit (must be equal) or `*` (matches any digit). A reading containing
    `?` never matches. Leading/trailing spaces in the pattern are ignored. An empty pattern never matches.
    Examples: "000400.000" matches "000400.000"; "000400.***" matches "000400.123"; "000400" does not match
    "000400.000" (different length).
    """
    pattern = pattern.strip()
    if not pattern:
        return False
    reading = volume_text.replace(".", "")
    if "?" in reading:
        return False
    pattern = pattern.replace(".", "")
    if len(pattern) != len(reading):
        return False
    return all(p == "*" or p == r for p, r in zip(pattern, reading))


def _hours(start: datetime, end: datetime) -> float:
    return max(0.0, (end - start).total_seconds() / 3600)


def _excess(prev_value: int, prev_time: datetime, value: int, time: datetime, settings: ValidationSettings) -> float:
    """How far the change exceeds what the rate allows in the time between (rule 6); <= 0 means within the rate."""
    delta = abs(value - prev_value) if settings.direction == "both" else value - prev_value
    return delta - (settings.max_rate_lph * _hours(prev_time, time) + settings.rate_slack_l)


def _step_ok(prev_value: int, prev_time: datetime, value: int, time: datetime, settings: ValidationSettings) -> bool:
    """Direction and rate check of one reading against an earlier one."""
    if settings.direction == "up" and value < prev_value:
        return False
    return _excess(prev_value, prev_time, value, time, settings) <= 0


def _reject(status: Status, state: ValidatorState, detail: str) -> tuple[Decision, ValidatorState]:
    return Decision(status, state.last_value_l, detail), state


def validate(inp: ValidatorInput, state: ValidatorState, settings: ValidationSettings
             ) -> tuple[Decision, ValidatorState]:
    """Apply the rules above. Returns the decision and the new state (the input state is not modified)."""
    if not inp.aligned:
        return _reject(Status.ALIGNMENT, state, "alignment marks not found")
    if inp.volume_l is None or inp.confidence < settings.min_confidence:
        return _reject(Status.UNREADABLE, state, f"unreadable: {inp.volume_text} at {inp.confidence:.2f}")
    if any(matches_reject_pattern(inp.volume_text, p) for p in settings.reject_patterns):
        return _reject(Status.REJECT_LIST, state, f"{inp.volume_text} is on the reject list")

    value = inp.volume_l
    previous_flow = state.last_flow_lph
    state = replace(state, last_flow_lph=inp.flow_lph)

    if state.last_value_l is None:
        return _accept(value, inp, state)

    last = state.last_value_l
    if settings.direction == "up" and value < last:
        return _reject(Status.NEGATIVE, state, f"{last} -> {value}, lower than the last accepted value")
    if settings.max_jump_l > 0 and _excess(last, state.last_time, value, inp.time, settings) > settings.max_jump_l:
        return _reject(Status.TOO_LARGE, state,
                       f"{last} -> {value}, more than {settings.max_jump_l} l above the max flow")

    if _step_ok(last, state.last_time, value, inp.time, settings):
        if settings.flow_check and inp.flow_lph == 0 and previous_flow == 0 \
                and value - last >= settings.flow_check_min_increase_l:
            return _reject(Status.FLOW_MISMATCH, state, f"{last} -> {value} while the flow is 0 l/h")
        return _accept(value, inp, state)

    return _pending(value, inp, state, settings)


def _accept(value: int, inp: ValidatorInput, state: ValidatorState) -> tuple[Decision, ValidatorState]:
    new = ValidatorState(last_value_l=value, last_time=inp.time, last_flow_lph=inp.flow_lph, pending=())
    return Decision(Status.OK, value), new


def _pending(value: int, inp: ValidatorInput, state: ValidatorState, settings: ValidationSettings
             ) -> tuple[Decision, ValidatorState]:
    last = state.last_value_l
    newest = state.pending[-1] if state.pending else None
    if newest is not None and _step_ok(newest.value_l, newest.time, value, inp.time, settings):
        pending = state.pending + (PendingReading(value, inp.time),)
    else:
        pending = (PendingReading(value, inp.time),)

    if len(pending) >= settings.confirm_readings:
        return _accept(value, inp, state)

    detail = f"{last} -> {value} in {_seconds(state.last_time, inp.time)} s, max {_allowed_l(state, inp, settings)} l"
    new = replace(state, pending=pending)
    return Decision(Status.PENDING_JUMP, last, detail), new


def _seconds(start: datetime | None, end: datetime) -> int:
    return int((end - start).total_seconds()) if start is not None else 0


def _allowed_l(state: ValidatorState, inp: ValidatorInput, settings: ValidationSettings) -> int:
    hours = _hours(state.last_time, inp.time) if state.last_time is not None else 0.0
    return round(settings.max_rate_lph * hours + settings.rate_slack_l)


def set_current_value(state: ValidatorState, value_l: int, time: datetime) -> ValidatorState:
    """Manual correction (the MQTT set-value command): the given value becomes the base; pending is cleared,
    `last_flow_lph` is kept."""
    return ValidatorState(last_value_l=value_l, last_time=time, last_flow_lph=state.last_flow_lph, pending=())
