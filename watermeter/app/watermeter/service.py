"""The add-on's main loop (task D6, Sonnet): wires capture → pipeline → validate → state → MQTT → storage → web.

Every `capture.interval_s` (and on `capture_now`): capture a burst, save the frames, `read_burst`,
`to_validator_input`, `validate` with the saved state, save the new state (`/data/state.json`), publish
`state_message`, write the burst's JSON next to the images, update the WebContext, prune old images once an hour.
Errors in one cycle are logged and the loop continues.

Before regions and a reference image exist (Regions page) the loop only captures and stores frames, so there is
something to draw the regions on. Files in the data folder: `options.json` (the connection, written by Home
Assistant), `settings.json` (the Settings page; applied at once, `apply_settings`), `state.json`, `regions.json`,
`reference.jpg`, `labels.json`, `images/`.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from aiohttp import web

from .capture.esphome import CameraClient, CameraError
from .labels import load_labels
from .models import (Decision, DigitResult, Image, LineReading, RawReading, Regions, Status, ValidatorState)
from .mqtt.client import MqttPublisher
from .mqtt.messages import state_message
from .pipeline import read_burst, to_validator_input
from .recognize.base import Recognizer, load_recognizer
from .settings import Options, Settings, load_options, load_settings, save_settings
from .storage import ImageStore
from .validate.rules import set_current_value as apply_current_value
from .validate.rules import validate
from .vision.images import decode_jpeg
from .vision.regions_io import REFERENCE_FILE, REGIONS_FILE, load_reference_bytes, load_regions
from .web.app import WebContext, create_app

try:
    from ._version import VERSION
except ImportError:  # running from the repository: the release script writes _version.py into the add-on image
    VERSION = "dev"

log = logging.getLogger(__name__)

INGRESS_PORT = 8099          # `ingress_port` in addon/watermeter/config.yaml
PRUNE_EVERY_S = 3600
STATE_FILE = "state.json"
OPTIONS_FILE = "options.json"
SETTINGS_FILE = "settings.json"
MODEL_SUFFIXES = (".tflite", ".onnx")
LABELS_FILE = "labels.json"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def load_state(path: Path) -> ValidatorState:
    """The saved validator state; a missing or damaged file starts fresh (the first reading becomes the base)."""
    try:
        return ValidatorState.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, KeyError, TypeError):
        return ValidatorState()


def save_state(path: Path, state: ValidatorState) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state.to_dict(), indent=2), encoding="utf-8")
    tmp.replace(path)


class Service:
    def __init__(self, data_dir: Path, models_dir: Path, *, camera: Any = None, mqtt: Any = None,
                 recognizer_loader: Callable[[Path, float], Recognizer] = load_recognizer,
                 clock: Callable[[], datetime] = _utc_now) -> None:
        self.data_dir, self.models_dir = Path(data_dir), Path(models_dir)
        self.options: Options = load_options(self.data_dir / OPTIONS_FILE)
        try:
            settings = load_settings(self.data_dir / SETTINGS_FILE)
        except ValueError as e:
            log.error("%s; using the defaults until the Settings page saves new ones", e)
            settings = Settings()
        self.camera = camera if camera is not None else CameraClient(self.options)
        self.mqtt = mqtt if mqtt is not None else MqttPublisher(self.options, VERSION,
                                                                on_set_value=self.set_current_value)
        self._recognizer_loader = recognizer_loader
        self._clock = clock
        self.store = ImageStore(self.data_dir)
        self.ctx = WebContext(data_dir=self.data_dir, settings=settings, version=VERSION,
                              state=load_state(self.data_dir / STATE_FILE), models=self._model_files())
        self.ctx.capture_now = self.cycle
        self.ctx.set_current_value = self.set_current_value
        self.ctx.apply_settings = self.apply_settings
        self.recognizer: Recognizer | None = None
        self._lock = asyncio.Lock()
        self._cache: tuple[tuple, Regions | None, Image | None] | None = None
        self._last_prune = 0.0
        self._warned_setup = False
        self._load_recognizer()

    # ---- settings and state ------------------------------------------------------------------------------

    @property
    def settings(self) -> Settings:
        return self.ctx.settings

    def _model_files(self) -> tuple[str, ...]:
        """The model files below the models folder (for the Settings page), as paths relative to it."""
        if not self.models_dir.is_dir():
            return ()
        return tuple(sorted(p.relative_to(self.models_dir).as_posix() for p in self.models_dir.rglob("*")
                            if p.suffix in MODEL_SUFFIXES))

    def apply_settings(self, settings: Settings) -> None:
        """From the Settings page: save, use from now on, reload the model if its settings changed."""
        old = self.settings.recognition
        save_settings(self.data_dir / SETTINGS_FILE, settings)
        self.ctx.settings = settings
        new = settings.recognition
        if (new.model, new.min_digit_confidence) != (old.model, old.min_digit_confidence) or self.recognizer is None:
            self._load_recognizer()
        log.info("settings saved")

    def _load_recognizer(self) -> None:
        rec = self.settings.recognition
        try:
            self.recognizer = self._recognizer_loader(self.models_dir / rec.model, rec.min_digit_confidence)
        except Exception as e:  # missing file, unknown extension, runtime not installed: keep capturing
            self.recognizer = None
            log.error("cannot load the digit model %s: %s", rec.model, e)

    def _set_state(self, state: ValidatorState) -> None:
        self.ctx.state = state
        save_state(self.data_dir / STATE_FILE, state)

    def set_current_value(self, litres: int) -> None:
        """Callback for the MQTT set-value command (S3): the only way to lower the value. Becomes the new base, pending
        cleared."""
        now = self._clock()
        self._set_state(apply_current_value(self.ctx.state, litres, now))
        decision = Decision(Status.OK, litres, "set by hand")
        self.ctx.last_decision = decision
        digits = tuple(DigitResult(int(c), 1.0) for c in f"{litres:09d}"[-9:])
        self.ctx.last_raw = RawReading(now, LineReading(digits, 3), None, aligned=True)
        log.info("current value set to %d l", litres)
        try:
            asyncio.get_running_loop().create_task(self._publish(decision, self.ctx.last_raw))
        except RuntimeError:
            pass  # no running loop (called from a test): nothing to publish to

    # ---- one capture cycle -------------------------------------------------------------------------------

    def _regions_and_reference(self) -> tuple[Regions | None, Image | None]:
        """Regions and reference image, re-read only when their files change."""
        key = tuple((p.stat().st_mtime_ns if p.exists() else None)
                    for p in (self.data_dir / REGIONS_FILE, self.data_dir / REFERENCE_FILE))
        if self._cache is None or self._cache[0] != key:
            regions, jpeg = load_regions(self.data_dir), load_reference_bytes(self.data_dir)
            reference = None
            if jpeg is not None:
                try:
                    reference = decode_jpeg(jpeg)
                except ValueError:
                    log.error("reference.jpg cannot be decoded")
            self._cache = (key, regions, reference)
        return self._cache[1], self._cache[2]

    async def cycle(self) -> None:
        """One capture burst, from camera to published reading. Safe to call while another cycle runs (it waits)."""
        async with self._lock:
            c = self.settings.capture
            frames = await self.camera.capture_burst(c.frames, c.settle_s, c.brightness)
            paths = self.store.save_burst(frames)
            regions, reference = self._regions_and_reference()
            if regions is None or reference is None or self.recognizer is None:
                if not self._warned_setup:
                    log.warning("images are saved but not read yet: set the reference image and the regions "
                                "(Regions page) and check that the digit model loads")
                    self._warned_setup = True
                return
            self._warned_setup = False
            loop = asyncio.get_running_loop()
            raw = await loop.run_in_executor(None, read_burst, frames, reference, regions, self.recognizer,
                                             self.settings.recognition.min_mark_score,
                                             self.settings.recognition.enhance_contrast)
            decision, state = validate(to_validator_input(raw), self.ctx.state, self.settings.validation,
                                       self.settings.capture.interval_s)
            self._set_state(state)
            self.ctx.last_raw, self.ctx.last_decision = raw, decision
            self._write_burst_json(paths, raw, decision)
            log.info("read %s -> %s%s", raw.volume.text, decision.status.value,
                     f" ({decision.detail})" if decision.detail else "")
            await self._publish(decision, raw)

    def _write_burst_json(self, paths: list[Path], raw: RawReading, decision: Decision) -> None:
        """`images/YYYY-MM-DD/HHMMSS.json` next to the frames (format: card D4), read by the Log page."""
        first = paths[0]
        target = self.data_dir / first.parent / (first.stem.split("_")[0] + ".json")
        doc = {
            "time": raw.captured_at.isoformat(),
            "frames": [p.as_posix() for p in paths],
            "raw": raw.volume.text,
            "flow": raw.flow.text if raw.flow is not None else None,
            "confidence": round(raw.volume.confidence, 3),
            "status": decision.status.value,
            "detail": decision.detail,
            "value_l": decision.value_l,
        }
        tmp = target.with_suffix(".tmp")
        tmp.write_text(json.dumps(doc), encoding="utf-8")
        tmp.replace(target)

    async def _publish(self, decision: Decision, raw: RawReading) -> None:
        last = self.ctx.state.last_time
        topic, payload = state_message(decision, raw, last.isoformat() if last else None)
        try:
            await self.mqtt.publish(topic, payload)
        except Exception as e:  # a broker problem must not stop reading the meter
            log.warning("could not publish: %s", e)

    # ---- housekeeping and the loop -----------------------------------------------------------------------

    def prune(self) -> int:
        rejected: set[str] = set()
        for doc_path in (self.data_dir / "images").glob("*/??????.json"):
            try:
                doc = json.loads(doc_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if doc.get("status") != Status.OK.value:
                rejected.update(doc.get("frames", []))
        labelled = set(load_labels(self.data_dir / LABELS_FILE))
        deleted = self.store.prune(self._clock(), self.settings.retention, rejected, labelled)
        if deleted:
            log.info("pruned %d old images", deleted)
        return deleted

    async def _step(self) -> None:
        try:
            await self.cycle()
        except CameraError as e:
            log.warning("capture failed: %s", e)
        except Exception:
            log.exception("capture cycle failed")
        if time.monotonic() - self._last_prune >= PRUNE_EVERY_S:
            self._last_prune = time.monotonic()
            try:
                self.prune()
            except Exception:
                log.exception("pruning failed")

    async def serve(self, port: int = INGRESS_PORT) -> None:
        runner = web.AppRunner(create_app(self.ctx))
        await runner.setup()
        await web.TCPSite(runner, "0.0.0.0", port).start()
        await self.mqtt.start()
        log.info("Watermeter %s started; web UI on port %d", VERSION, port)
        try:
            while True:
                started = time.monotonic()
                await self._step()
                await asyncio.sleep(max(1.0, self.settings.capture.interval_s - (time.monotonic() - started)))
        finally:
            await self.mqtt.stop()
            await self.camera.close()
            await runner.cleanup()


async def run(data_dir: Path, models_dir: Path) -> None:
    options = load_options(Path(data_dir) / OPTIONS_FILE)
    logging.basicConfig(level=getattr(logging, options.log_level.upper(), logging.INFO),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    await Service(data_dir, models_dir).serve()
