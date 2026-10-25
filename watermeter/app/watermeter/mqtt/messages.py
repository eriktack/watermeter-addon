"""MQTT discovery and state messages (pure; task D2). Tests: `tests/test_mqtt_messages.py`.

Topics (base = "watermeter"):
- availability: `watermeter/availability`, payload "online"/"offline" (retained; "offline" is the client's will)
- state: `watermeter/state`, one JSON object (retained), see `state_message`
- discovery: `homeassistant/sensor/watermeter/<object>/config` (retained), one per entity in the plan's §7 table,
  then `homeassistant/number/watermeter/set_value/config` for the "Set current value" entity
- command: `watermeter/set_value` (not retained), payload the new volume in m³ as text, e.g. "170.861"
  (the "set current value" entity; task S3)
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from ..models import Decision, RawReading

SET_VALUE_PATTERN = re.compile(r"^\d+(\.\d{1,3})?$")
BASE = "watermeter"
DISCOVERY_PREFIX = "homeassistant"
STATE_TOPIC = f"{BASE}/state"
AVAILABILITY_TOPIC = f"{BASE}/availability"
SET_VALUE_TOPIC = f"{BASE}/set_value"
MAX_VALUE_L = 999_999_999   # 999999.999 m³: the display's 6 + 3 digits


def parse_set_value(payload: bytes | str) -> int | None:
    r"""The litres for a "set current value" command, or None if it is not acceptable.
    Accepted: a plain non-negative decimal number in m³ with at most 3 decimals (`170`, `170.8`, `170.861`, leading and
    trailing spaces allowed), at most 999999.999; digits are required before the point, and after it if there is one
    (`.5` and `5.` are refused). Regex: `^\d+(\.\d{1,3})?$`. Refused (None): empty, negative, more than 3 decimals, exponent or
    other characters (`1e3`, `170,861`, `abc`), not UTF-8. Conversion is exact (no float rounding): "0.001" → 1."""
    if isinstance(payload, bytes):
        try:
            payload = payload.decode("utf-8")
        except UnicodeDecodeError:
            return None
    text = payload.strip()
    if not SET_VALUE_PATTERN.match(text):
        return None
    try:
        litres = int(Decimal(text) * 1000)
    except InvalidOperation:
        return None
    return litres if litres <= MAX_VALUE_L else None


def _entity(obj: str, name: str, version: str, **extra: object) -> dict:
    return {
        "name": name,
        "unique_id": f"watermeter_{obj}",
        "object_id": f"watermeter_{obj}",
        "state_topic": STATE_TOPIC,
        "value_template": f"{{{{ value_json.{obj} }}}}",
        "availability_topic": AVAILABILITY_TOPIC,
        "device": {
            "identifiers": [BASE],
            "name": "Water meter",
            "manufacturer": "Watermeter add-on",
            "sw_version": version,
        },
        **extra,
    }


def discovery_messages(version: str) -> list[tuple[str, dict]]:
    """(topic, payload) per entity. Every payload has: `name`, `unique_id` = "watermeter_<object>",
    `object_id` = "watermeter_<object>", `state_topic` = "watermeter/state", `value_template` reading its key from
    the state JSON, `availability_topic` = "watermeter/availability", and `device` =
    {"identifiers": ["watermeter"], "name": "Water meter", "manufacturer": "Watermeter add-on",
    "sw_version": version}. Objects, in this order:
    - volume: device_class water, state_class total (not total_increasing: a manual correction downwards must count
      as a negative difference, not as a meter reset that adds the whole value), unit "m³",
      suggested_display_precision 3
    - flow: device_class volume_flow_rate, state_class measurement, unit "m³/h", suggested_display_precision 3
    - raw: entity_category diagnostic (text, no unit)
    - status: entity_category diagnostic (text)
    - last_accepted: device_class timestamp, entity_category diagnostic
    - confidence: unit "%", state_class measurement, entity_category diagnostic
    """
    entities = [
        ("volume", "Volume", {
            "device_class": "water",
            "state_class": "total",
            "unit_of_measurement": "m³",
            "suggested_display_precision": 3,
        }),
        ("flow", "Flow", {
            "device_class": "volume_flow_rate",
            "state_class": "measurement",
            "unit_of_measurement": "m³/h",
            "suggested_display_precision": 3,
        }),
        ("raw", "Raw reading", {"entity_category": "diagnostic"}),
        ("status", "Status", {"entity_category": "diagnostic"}),
        ("last_accepted", "Last accepted", {
            "device_class": "timestamp",
            "entity_category": "diagnostic",
        }),
        ("confidence", "Confidence", {
            "unit_of_measurement": "%",
            "state_class": "measurement",
            "entity_category": "diagnostic",
        }),
    ]
    return [
        (f"{DISCOVERY_PREFIX}/sensor/{BASE}/{obj}/config", _entity(obj, name, version, **extra))
        for obj, name, extra in entities
    ] + [(f"{DISCOVERY_PREFIX}/number/{BASE}/set_value/config", _set_value_entity(version))]


def _set_value_entity(version: str) -> dict:
    """The "Set current value" number: the only way to lower the published volume (plan §6). Its state shows the
    published volume, so the field starts at the current value."""
    entity = _entity("set_value", "Set current value", version, entity_category="config",
                     command_topic=SET_VALUE_TOPIC, min=0, max=MAX_VALUE_L / 1000, step=0.001, mode="box",
                     unit_of_measurement="m³", icon="mdi:counter")
    entity["value_template"] = "{{ value_json.volume }}"
    return entity


def state_message(decision: Decision, raw: RawReading, last_accepted_iso: str | None) -> tuple[str, dict]:
    """("watermeter/state", payload). Payload keys:
    volume (m³ float with 3 decimals from decision.value_l, or None), flow (m³/h float from raw.flow if readable,
    else None), raw (raw.volume.text), status (decision.status.value), last_accepted (last_accepted_iso),
    confidence (round(raw.volume.confidence * 100, 1)).
    """
    volume = None if decision.value_l is None else round(decision.value_l / 1000, 3)
    flow_litres = raw.flow.litres if raw.flow is not None else None
    flow = None if flow_litres is None else round(flow_litres / 1000, 3)
    payload = {
        "volume": volume,
        "flow": flow,
        "raw": raw.volume.text,
        "status": decision.status.value,
        "last_accepted": last_accepted_iso,
        "confidence": round(raw.volume.confidence * 100, 1),
    }
    return STATE_TOPIC, payload
