"""API client for Senzomatic moisture monitoring system.

Bootstraps from the Central Unit's local HTTP config (``/var/config.json``),
which exposes the unit's long-lived JWT and device list, then reads sensor
values from the cloud VictoriaMetrics proxy using that token.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any

import aiohttp

from .const import VMPROXY_BASE_URL

_LOGGER = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 2  # seconds
REQUEST_TIMEOUT = 30  # seconds

METRICS = [
    "temperature_ambient_celsius",
    "rel_humidity_ambient_pct",
    "abs_humidity_ambient_gm3",
    "moisture",
]


class SenzomaticAPI:
    """API client for Senzomatic system."""

    def __init__(self, session: aiohttp.ClientSession, host: str) -> None:
        """Initialize the API client."""
        self.session = session
        self.host = host
        self.jwt: str | None = None
        self.unit_id: str | None = None
        self.devices: list[dict[str, Any]] = []
        self._request_count = 0
        self._failed_request_count = 0
        _LOGGER.info("Senzomatic API client initialized for host: %s", host)

    async def async_authenticate(self) -> bool:
        """Bootstrap token and device list from the local Central Unit."""
        try:
            return await self._async_bootstrap()
        except Exception as exc:  # noqa: BLE001 - surface as auth failure
            _LOGGER.error("Bootstrap from %s failed: %s", self.host, exc)
            return False

    async def _async_bootstrap(self) -> bool:
        """Fetch /var/config.json for the JWT and device list."""
        url = f"http://{self.host}/var/config.json"
        timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
        async with self.session.get(url, timeout=timeout) as response:
            self._request_count += 1
            response.raise_for_status()
            # Device serves application/json but be lenient about content-type.
            cfg = await response.json(content_type=None)

        self.jwt = cfg.get("global", {}).get("jwt_token")
        # Stable identity: the Central Unit UUID embedded in its cloud URLs
        # (survives IP changes, unlike the host). Fall back to host if absent.
        match = re.search(
            r"/central_units/([0-9a-f-]+)",
            cfg.get("cloud_api", {}).get("config_url", ""),
        )
        self.unit_id = match.group(1) if match else self.host
        self.devices = [
            {
                "id": uuid,
                "uuid": uuid,
                "name": (dev.get("display_name") or uuid[:8]).strip(),
                "model": dev.get("type", ""),
            }
            for uuid, dev in cfg.get("devices", {}).items()
        ]

        if not self.jwt:
            _LOGGER.error("No jwt_token in config.json from %s", self.host)
            return False
        _LOGGER.info("Bootstrapped %d devices from %s", len(self.devices), self.host)
        return bool(self.devices)

    async def _retry_with_backoff(self, func, *args, **kwargs):
        """Retry a coroutine on network errors with exponential backoff."""
        last_exception = None
        for attempt in range(MAX_RETRIES):
            try:
                return await func(*args, **kwargs)
            except aiohttp.ClientError as exc:
                last_exception = exc
                if attempt < MAX_RETRIES - 1:
                    wait_time = RETRY_BACKOFF_BASE**attempt
                    _LOGGER.warning(
                        "Request failed (attempt %d/%d), retrying in %ds: %s",
                        attempt + 1, MAX_RETRIES, wait_time, exc,
                    )
                    await asyncio.sleep(wait_time)
                else:
                    _LOGGER.error("Request failed after %d attempts: %s", MAX_RETRIES, exc)
            except Exception as exc:  # noqa: BLE001
                _LOGGER.error("Non-retryable error in request: %s", exc, exc_info=True)
                raise
        raise last_exception

    async def async_get_sensor_data(
        self,
        device_id: str,
        metric: str,
        start_time: int | None = None,
        end_time: int | None = None,
    ) -> dict[str, Any]:
        """Get sensor data for a specific device and metric from the VM proxy."""
        if not self.jwt and not await self.async_authenticate():
            return {}

        now = int(time.time())
        start_time = start_time or now - 3600  # last hour
        end_time = end_time or now

        async def _fetch():
            if metric == "moisture":
                # Model-dependent moisture source; MHT02 reports humidity, others resistance.
                query = (
                    f'round(avg(label_del((moisture_humidity_pct{{device_id="{device_id}",device_model="MHT02"}} '
                    f'or moisture_resistance_pct{{device_id="{device_id}",device_model!="MHT02"}} '
                    f'or moisture_pct{{device_id="{device_id}",device_model!="MHT02"}}),"scrape_id"))by(device_id),0.01)'
                )
            else:
                query = f'round(avg(label_del({metric}{{device_id="{device_id}"}},"scrape_id"))by(device_id),0.01)'

            url = f"{VMPROXY_BASE_URL}/query_range"
            params = {"query": query, "start": start_time, "end": end_time, "step": 300}
            headers = {"Authorization": f"Bearer {self.jwt}"}
            timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)

            async with self.session.get(url, params=params, headers=headers, timeout=timeout) as response:
                self._request_count += 1
                if response.status in (401, 403):
                    # Token rotated or revoked; drop it so the next cycle re-bootstraps.
                    _LOGGER.warning("VM proxy returned %d, invalidating token", response.status)
                    self.jwt = None
                    raise aiohttp.ClientResponseError(
                        request_info=response.request_info,
                        history=response.history,
                        status=response.status,
                        message="Authentication required",
                    )
                if response.status != 200:
                    self._failed_request_count += 1
                    _LOGGER.error(
                        "VM query failed: device=%s..., metric=%s, status=%d",
                        device_id[:8], metric, response.status,
                    )
                    return {}
                return await response.json()

        try:
            return await self._retry_with_backoff(_fetch)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.error(
                "Error getting sensor data after retries: device=%s..., metric=%s: %s",
                device_id[:8], metric, exc,
            )
            return {}

    async def async_get_data(self) -> dict[str, Any]:
        """Get latest values for all metrics across all devices."""
        if not self.devices and not await self.async_authenticate():
            _LOGGER.warning("No devices available to fetch data from")
            return {}

        result: dict[str, Any] = {"devices": [], "sensors": {}}

        for device in self.devices:
            device_id = device["uuid"]
            device_data: dict[str, float] = {}

            for metric in METRICS:
                data = await self.async_get_sensor_data(device_id, metric)
                value = _latest_value(data)
                if value is not None:
                    device_data[metric] = value

            if device_data:
                result["devices"].append(device)
                result["sensors"][device["id"]] = device_data
            else:
                _LOGGER.debug("No sensor data for %s (%s...)", device["name"], device_id[:8])

        _LOGGER.info(
            "Data fetch complete: %d/%d devices, requests=%d, failed=%d",
            len(result["devices"]), len(self.devices),
            self._request_count, self._failed_request_count,
        )
        return result


def _latest_value(data: dict[str, Any]) -> float | None:
    """Extract the newest sample from a VM query_range matrix response."""
    try:
        values = data["data"]["result"][0]["values"]
        return float(values[-1][1]) if values else None
    except (KeyError, IndexError, TypeError, ValueError):
        return None
