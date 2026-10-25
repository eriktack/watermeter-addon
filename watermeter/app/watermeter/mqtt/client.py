"""MQTT connection (task D2): broker from the Supervisor (`services: mqtt:need`, read via the Supervisor API
`GET http://supervisor/services/mqtt` with the SUPERVISOR_TOKEN) unless `Options.mqtt_host` is set.
Publishes discovery on connect and on HA's birth message (`homeassistant/status` = "online").
Tests: `tests/test_mqtt_client.py` (no broker; the broker lookup and the encoding are injected or patched)."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Callable

import aiohttp
import aiomqtt

from ..settings import Options
from .messages import AVAILABILITY_TOPIC, DISCOVERY_PREFIX, SET_VALUE_TOPIC, discovery_messages, parse_set_value

log = logging.getLogger(__name__)

SUPERVISOR_MQTT_URL = "http://supervisor/services/mqtt"
BIRTH_TOPIC = f"{DISCOVERY_PREFIX}/status"
RECONNECT_DELAYS_S = (1, 2, 5, 10, 30)  # the last value repeats
LOG_INTERVAL_S = 60


@dataclass(frozen=True)
class Broker:
    host: str
    port: int
    username: str | None
    password: str | None


async def fetch_supervisor_mqtt(session: aiohttp.ClientSession, token: str) -> dict:
    """The `data` object of the Supervisor's MQTT service (host, port, username, password)."""
    async with session.get(SUPERVISOR_MQTT_URL, headers={"Authorization": f"Bearer {token}"}) as response:
        response.raise_for_status()
        body = await response.json()
    return body["data"]


async def resolve_broker(options: Options, fetch=fetch_supervisor_mqtt) -> Broker:
    """The broker from the add-on options if `mqtt_host` is set, else from the Supervisor."""
    if options.mqtt_host:
        return Broker(options.mqtt_host, options.mqtt_port, options.mqtt_username or None,
                      options.mqtt_password or None)
    token = os.environ.get("SUPERVISOR_TOKEN", "")
    async with aiohttp.ClientSession() as session:
        data = await fetch(session, token)
    return Broker(data["host"], int(data["port"]), data.get("username") or None, data.get("password") or None)


def encode_payload(payload: dict | str) -> str:
    """Dicts become JSON text; strings are sent as they are."""
    return json.dumps(payload) if isinstance(payload, dict) else payload


class MqttPublisher:
    def __init__(self, options: Options, version: str, on_set_value: Callable[[int], None] | None = None) -> None:
        self._options = options
        self._version = version
        self._on_set_value = on_set_value
        self._client: aiomqtt.Client | None = None
        self._task: asyncio.Task | None = None
        self._last_logged = 0.0

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="mqtt")

    async def publish(self, topic: str, payload: dict | str, retain: bool = True) -> None:
        if self._client is None:
            log.debug("not connected, dropping message on %s", topic)
            return
        await self._client.publish(topic, payload=encode_payload(payload), retain=retain)

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._client is not None:
            await self._client.publish(AVAILABILITY_TOPIC, payload="offline", retain=True)
            self._client = None

    async def _run(self) -> None:
        attempt = 0
        while True:
            try:
                broker = await resolve_broker(self._options)
                will = aiomqtt.Will(AVAILABILITY_TOPIC, payload="offline", retain=True)
                async with aiomqtt.Client(broker.host, broker.port, username=broker.username,
                                          password=broker.password, will=will) as client:
                    self._client = client
                    attempt = 0
                    await self._announce(client)
                    await client.subscribe(BIRTH_TOPIC)
                    await client.subscribe(SET_VALUE_TOPIC)
                    async for message in client.messages:
                        await self._handle(message.topic.value, message.payload)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # broker down, Supervisor not ready, network errors: retry
                self._log_failure(exc)
            finally:
                self._client = None
            delay = RECONNECT_DELAYS_S[min(attempt, len(RECONNECT_DELAYS_S) - 1)]
            attempt += 1
            await asyncio.sleep(delay)

    async def _handle(self, topic: str, payload: bytes) -> None:
        """One incoming message: HA's birth message re-announces the entities; a set-value command calls the
        callback with the litres. A bad command is logged and ignored; a callback error never stops the client."""
        if topic == BIRTH_TOPIC and payload == b"online":
            await self._announce(self._client)
        elif topic == SET_VALUE_TOPIC:
            litres = parse_set_value(payload)
            if litres is None:
                log.warning("ignoring set value %r: expected m³ like 170.861", payload[:40])
            elif self._on_set_value is not None:
                try:
                    self._on_set_value(litres)
                except Exception:
                    log.exception("setting the current value failed")

    async def _announce(self, client: aiomqtt.Client) -> None:
        await client.publish(AVAILABILITY_TOPIC, payload="online", retain=True)
        for topic, payload in discovery_messages(self._version):
            await client.publish(topic, payload=encode_payload(payload), retain=True)

    def _log_failure(self, exc: Exception) -> None:
        now = time.monotonic()
        if now - self._last_logged >= LOG_INTERVAL_S:
            self._last_logged = now
            log.warning("MQTT connection failed, retrying: %s", exc)
