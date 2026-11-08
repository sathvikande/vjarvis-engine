"""
Resilient local HTTP client for transmitting telemetry events from the CLI to the local FastAPI bridge.
Includes offline fallback buffering to guarantee uninterrupted simulation loops during network/server drops.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

import httpx

from vjarvis_engine.schemas import MetricsResponse, TriageEventRequest

logger = logging.getLogger("vjarvis.client")

OFFLINE_BUFFER_PATH = Path(".vjarvis_offline_events.jsonl").resolve()


class BridgeClient:
    """
    Robust client interface to the local FastAPI telemetry server.
    """

    def __init__(self, base_url: str = "http://127.0.0.1:8000", timeout: float = 3.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def send_event(self, event: TriageEventRequest) -> bool:
        """
        Sends event to POST /api/triage-event.
        If the server is unreachable, appends to local offline buffer file without failing.
        """
        payload = json.loads(event.model_dump_json())
        url = f"{self.base_url}/api/triage-event"

        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(url, json=payload)
                if resp.status_code in (200, 201):
                    logger.debug("Successfully forwarded event to bridge: %s", resp.json())
                    # Attempt to flush any pending offline buffer
                    self._flush_offline_buffer()
                    return True
                else:
                    logger.warning("Bridge returned status %d: %s", resp.status_code, resp.text)
        except (httpx.ConnectError, httpx.TimeoutException, OSError) as e:
            logger.warning("FastAPI bridge unavailable (%s). Buffering event locally to %s", e, OFFLINE_BUFFER_PATH)

        # Offline fallback
        self._buffer_offline(payload)
        return False

    def get_metrics(self) -> Optional[MetricsResponse]:
        """
        Retrieves current aggregated metrics from the bridge.
        """
        url = f"{self.base_url}/api/metrics"
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.get(url)
                if resp.status_code == 200:
                    return MetricsResponse(**resp.json())
        except Exception as e:
            logger.warning("Failed to fetch metrics from bridge: %s", e)
        return None

    def _buffer_offline(self, payload: dict) -> None:
        try:
            OFFLINE_BUFFER_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(OFFLINE_BUFFER_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(payload) + "\n")
        except OSError as e:
            logger.error("Failed to buffer event offline: %s", e)

    def _flush_offline_buffer(self) -> None:
        if not OFFLINE_BUFFER_PATH.exists():
            return
        try:
            lines = OFFLINE_BUFFER_PATH.read_text(encoding="utf-8").splitlines()
            if not lines:
                return

            remaining = []
            with httpx.Client(timeout=self.timeout) as client:
                for line in lines:
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                        resp = client.post(f"{self.base_url}/api/triage-event", json=data)
                        if resp.status_code not in (200, 201):
                            remaining.append(line)
                    except Exception:
                        remaining.append(line)

            if remaining:
                OFFLINE_BUFFER_PATH.write_text("\n".join(remaining) + "\n", encoding="utf-8")
            else:
                OFFLINE_BUFFER_PATH.unlink(missing_ok=True)
                logger.info("Successfully flushed offline telemetry buffer to bridge.")
        except Exception as e:
            logger.warning("Error during offline buffer flush: %s", e)
