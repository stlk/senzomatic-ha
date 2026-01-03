"""API client for Senzomatic moisture monitoring system."""
from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlparse

import aiohttp

from .const import (
    DASHBOARD_BASE_URL,
    LOGIN_URL,
    OAUTH_AUTHORIZE_URL,
    VMPROXY_BASE_URL,
)

_LOGGER = logging.getLogger(__name__)

# Constants for retry and session management
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 2  # seconds
REQUEST_TIMEOUT = 30  # seconds
SESSION_VALIDITY_HOURS = 23  # Re-authenticate before 24h expiry

class SenzomaticAPI:
    """API client for Senzomatic system."""

    def __init__(
        self, 
        session: aiohttp.ClientSession, 
        username: str, 
        password: str,
        oauth_client_id: str
    ) -> None:
        """Initialize the API client."""
        self.session = session
        self.username = username
        self.password = password
        self.oauth_client_id = oauth_client_id
        self.installation_id = None
        self.device_ids = []
        self.authenticated = False
        self.last_auth_time = None
        self._request_count = 0
        self._failed_request_count = 0
        _LOGGER.info("Senzomatic API client initialized for user: %s", username)

    def _is_session_valid(self) -> bool:
        """Check if the current session is still valid."""
        if not self.authenticated:
            _LOGGER.debug("Session invalid: not authenticated")
            return False
        
        if not self.last_auth_time:
            _LOGGER.debug("Session invalid: no authentication timestamp")
            return False
        
        session_age = datetime.now() - self.last_auth_time
        is_valid = session_age < timedelta(hours=SESSION_VALIDITY_HOURS)
        
        if not is_valid:
            _LOGGER.warning(
                "Session expired: age=%s (max %d hours)", 
                session_age, 
                SESSION_VALIDITY_HOURS
            )
        else:
            _LOGGER.debug("Session valid: age=%s", session_age)
        
        return is_valid

    def _mark_authentication_success(self) -> None:
        """Mark successful authentication."""
        self.authenticated = True
        self.last_auth_time = datetime.now()
        _LOGGER.info(
            "Authentication successful at %s", 
            self.last_auth_time.isoformat()
        )

    def _mark_authentication_failure(self) -> None:
        """Mark authentication failure."""
        self.authenticated = False
        self.last_auth_time = None
        _LOGGER.warning("Authentication failed, session invalidated")

    async def _retry_with_backoff(self, func, *args, **kwargs):
        """Retry a function with exponential backoff."""
        last_exception = None
        
        for attempt in range(MAX_RETRIES):
            try:
                return await func(*args, **kwargs)
            except aiohttp.ClientError as exc:
                last_exception = exc
                if attempt < MAX_RETRIES - 1:
                    wait_time = RETRY_BACKOFF_BASE ** attempt
                    _LOGGER.warning(
                        "Request failed (attempt %d/%d), retrying in %ds: %s",
                        attempt + 1,
                        MAX_RETRIES,
                        wait_time,
                        exc
                    )
                    await asyncio.sleep(wait_time)
                else:
                    _LOGGER.error(
                        "Request failed after %d attempts: %s",
                        MAX_RETRIES,
                        exc
                    )
            except Exception as exc:
                # Don't retry non-network errors
                _LOGGER.error("Non-retryable error in request: %s", exc, exc_info=True)
                raise
        
        raise last_exception

    async def async_authenticate(self) -> bool:
        """Authenticate with the Senzomatic system."""
        start_time = time.time()
        _LOGGER.info("Starting authentication flow for user: %s", self.username)
        
        try:
            # Step 1: Get login page to extract authenticity token
            _LOGGER.debug("Step 1: Fetching login page from %s", LOGIN_URL)
            
            timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
            async with self.session.get(LOGIN_URL, timeout=timeout) as response:
                request_time = time.time() - start_time
                _LOGGER.debug(
                    "Login page response: status=%d, time=%.2fs",
                    response.status,
                    request_time
                )
                
                if response.status != 200:
                    _LOGGER.error(
                        "Failed to get login page: status=%d, url=%s",
                        response.status,
                        response.url
                    )
                    self._mark_authentication_failure()
                    return False
                
                content = await response.text()
                _LOGGER.debug("Login page content length: %d bytes", len(content))
                
                # Extract authenticity token from hidden input or meta tags
                authenticity_token = None

                # Try hidden input first
                token_match = re.search(r'name="authenticity_token"\s+value="([^"]*)"', content, re.IGNORECASE)
                if token_match:
                    authenticity_token = token_match.group(1)
                    _LOGGER.debug("Found authenticity token in hidden input: %s...", authenticity_token[:10])
                else:
                    meta_token_match = re.search(r'<meta\s+name="csrf-token"\s+content="([^"]+)"\s*/?>', content, re.IGNORECASE)
                    if meta_token_match:
                        authenticity_token = meta_token_match.group(1)
                        _LOGGER.debug("Found authenticity token in meta tag: %s...", authenticity_token[:10])
                    else:
                        _LOGGER.error("Could not find authenticity token in login page")
                        _LOGGER.debug("Login page excerpt (first 500 chars): %s", content[:500])
                        self._mark_authentication_failure()
                        return False

            # Step 2: Submit login form
            _LOGGER.debug("Step 2: Submitting login form for user: %s", self.username)
            login_data = {
                "user[email]": self.username,
                "user[password]": self.password,
                "authenticity_token": authenticity_token,
                "commit": "Přihlásit se"
            }

            step2_start = time.time()
            async with self.session.post(
                LOGIN_URL, 
                data=login_data, 
                allow_redirects=False,
                timeout=timeout
            ) as response:
                request_time = time.time() - step2_start
                _LOGGER.debug(
                    "Login form response: status=%d, time=%.2fs",
                    response.status,
                    request_time
                )
                
                # Check if login was successful
                if response.status == 302:
                    # Successful login should redirect
                    location = response.headers.get('Location', '')
                    _LOGGER.debug("Login redirect location: %s", location)
                    
                    # Try to extract installation ID from the initial redirect
                    if "/charts/" in location:
                        url_parts = location.split("/charts/")
                        if len(url_parts) > 1:
                            installation_id = url_parts[1].split('/')[0].split('?')[0]
                            _LOGGER.info(
                                "Found installation ID from login redirect: %s",
                                installation_id
                            )
                            self.installation_id = installation_id
                            self._mark_authentication_success()
                            total_time = time.time() - start_time
                            _LOGGER.info(
                                "Authentication completed successfully in %.2fs",
                                total_time
                            )
                            return True
                            
                elif response.status == 200:
                    # Status 200 usually means we stayed on the login page = failed login
                    content = await response.text()
                    _LOGGER.error("Login failed: Invalid credentials (stayed on login page)")
                    _LOGGER.debug("Response URL: %s", response.url)
                    if 'alert' in content.lower() or 'error' in content.lower():
                        _LOGGER.debug("Found error/alert message in response")
                    self._mark_authentication_failure()
                    return False
                else:
                    _LOGGER.error(
                        "Login failed: unexpected status=%d",
                        response.status
                    )
                    self._mark_authentication_failure()
                    return False

            # Step 3: Follow OAuth flow to get to dashboard
            _LOGGER.debug("Step 3: Following OAuth flow")
            oauth_url = f"{OAUTH_AUTHORIZE_URL}?client_id={self.oauth_client_id}&redirect_uri={DASHBOARD_BASE_URL}/oauth/callback%3Flocale%3Dcs&response_type=code&scope=erp_api+erp_api_remote_control+reporter_api"
            _LOGGER.debug("OAuth URL: %s", oauth_url)
            
            step3_start = time.time()
            async with self.session.get(
                oauth_url, 
                allow_redirects=True,
                timeout=timeout
            ) as response:
                request_time = time.time() - step3_start
                final_url = str(response.url)
                _LOGGER.debug(
                    "OAuth flow completed: status=%d, time=%.2fs, final_url=%s",
                    response.status,
                    request_time,
                    final_url
                )
                
                if response.status != 200:
                    _LOGGER.error("OAuth flow failed: status=%d", response.status)
                    self._mark_authentication_failure()
                    return False
                
                # Try multiple patterns to extract installation ID
                installation_id = None
                
                # Pattern 1: /charts/ in URL
                if "/charts/" in final_url:
                    url_parts = final_url.split("/charts/")
                    if len(url_parts) > 1:
                        installation_id = url_parts[1].split('/')[0].split('?')[0]
                        _LOGGER.info(
                            "Found installation ID from /charts/ URL pattern: %s",
                            installation_id
                        )
                
                # Pattern 2: Check the page content for installation ID
                if not installation_id:
                    _LOGGER.debug("Searching page content for installation ID")
                    content = await response.text()
                    _LOGGER.debug("OAuth page content length: %d bytes", len(content))
                    
                    # Look for installation ID in various places
                    id_patterns = [
                        r'installation[_-]?id["\']?\s*[=:]\s*["\']?([a-f0-9-]+)',
                        r'charts/([a-f0-9-]+)',
                        r'vmproxy\.mgrd\.cz/api/v1/([a-f0-9-]+)',
                    ]
                    
                    for pattern in id_patterns:
                        match = re.search(pattern, content, re.IGNORECASE)
                        if match:
                            installation_id = match.group(1)
                            _LOGGER.info(
                                "Found installation ID with pattern '%s': %s",
                                pattern,
                                installation_id
                            )
                            break
                
                # Pattern 3: Try to navigate directly to dashboard and look for redirects
                if not installation_id:
                    _LOGGER.debug("Step 3b: Trying direct dashboard access")
                    dashboard_url = f"{DASHBOARD_BASE_URL}/cs"
                    
                    step3b_start = time.time()
                    async with self.session.get(
                        dashboard_url, 
                        allow_redirects=True,
                        timeout=timeout
                    ) as dash_response:
                        request_time = time.time() - step3b_start
                        dash_url = str(dash_response.url)
                        _LOGGER.debug(
                            "Dashboard access: status=%d, time=%.2fs, url=%s",
                            dash_response.status,
                            request_time,
                            dash_url
                        )
                        
                        if "/charts/" in dash_url:
                            url_parts = dash_url.split("/charts/")
                            if len(url_parts) > 1:
                                installation_id = url_parts[1].split('/')[0].split('?')[0]
                                _LOGGER.info(
                                    "Found installation ID from dashboard redirect: %s",
                                    installation_id
                                )
                        else:
                            # If we're on the general dashboard, try to extract from page content
                            content = await dash_response.text()
                            _LOGGER.debug("Dashboard content length: %d bytes", len(content))
                            
                            # Look for installation/chart IDs in the HTML content
                            chart_patterns = [
                                r'/charts/([a-f0-9-]{36})',  # UUID format
                                r'charts/([a-f0-9-]+)',
                                r'installation[_-]?id["\']?\s*[=:]\s*["\']?([a-f0-9-]+)',
                                r'vmproxy\.mgrd\.cz/api/v1/([a-f0-9-]+)',
                                r'data-installation-id["\']?\s*=\s*["\']([a-f0-9-]+)',
                            ]
                            
                            for pattern in chart_patterns:
                                matches = re.findall(pattern, content, re.IGNORECASE)
                                if matches:
                                    installation_id = matches[0]
                                    _LOGGER.info(
                                        "Found installation ID with dashboard pattern '%s': %s",
                                        pattern,
                                        installation_id
                                    )
                                    break
                
                self.installation_id = installation_id
                
                if not self.installation_id:
                    _LOGGER.error("Could not extract installation ID from authentication flow")
                    _LOGGER.error("Final URL was: %s", final_url)
                    _LOGGER.error("This might mean:")
                    _LOGGER.error("  1. Login credentials are incorrect")
                    _LOGGER.error("  2. Account doesn't have access to any installations")
                    _LOGGER.error("  3. The authentication flow has changed")
                    self._mark_authentication_failure()
                    return False

            self._mark_authentication_success()
            total_time = time.time() - start_time
            _LOGGER.info(
                "Authentication completed successfully in %.2fs, installation_id=%s",
                total_time,
                self.installation_id
            )
            return True

        except aiohttp.ClientError as exception:
            total_time = time.time() - start_time
            _LOGGER.error(
                "Authentication network error after %.2fs: %s",
                total_time,
                exception,
                exc_info=True
            )
            self._mark_authentication_failure()
            return False
        except Exception as exception:
            total_time = time.time() - start_time
            _LOGGER.error(
                "Authentication unexpected error after %.2fs: %s",
                total_time,
                exception,
                exc_info=True
            )
            self._mark_authentication_failure()
            return False

    async def async_get_device_list(self) -> list[dict[str, Any]]:
        """Get list of devices from the HTML page."""
        # Check session validity first
        if not self._is_session_valid():
            _LOGGER.info("Session invalid or expired, re-authenticating...")
            if not await self.async_authenticate():
                _LOGGER.error("Re-authentication failed")
                return []

        start_time = time.time()
        _LOGGER.debug("Fetching device list for installation: %s", self.installation_id)
        
        try:
            dashboard_url = f"{DASHBOARD_BASE_URL}/cs/charts/{self.installation_id}"
            timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
            
            async with self.session.get(dashboard_url, timeout=timeout) as response:
                request_time = time.time() - start_time
                self._request_count += 1
                
                _LOGGER.debug(
                    "Device list response: status=%d, time=%.2fs",
                    response.status,
                    request_time
                )
                
                if response.status == 401 or response.status == 403:
                    _LOGGER.warning(
                        "Authentication error (status=%d), session may have expired",
                        response.status
                    )
                    self._mark_authentication_failure()
                    # Retry with fresh authentication
                    if await self.async_authenticate():
                        return await self.async_get_device_list()
                    return []
                
                if response.status != 200:
                    _LOGGER.error(
                        "Failed to get dashboard: status=%d, url=%s",
                        response.status,
                        response.url
                    )
                    self._failed_request_count += 1
                    return []
                
                content = await response.text()
                _LOGGER.debug("Dashboard content length: %d bytes", len(content))
                
                # Extract device information from the HTML
                devices = []
                
                # Look for device UUIDs with complete metadata (UUID + label + model/hw_part)
                # Only include devices where we can determine the actual model
                device_uuid_patterns = [
                    r'"([a-f0-9-]{36})"\s*:\s*{[^{}]*"label"\s*:\s*"([^"]+)"[^{}]*"hw_part"\s*:\s*"([^"]+)"',
                    r'"id"\s*:\s*"([a-f0-9-]{36})"[^}]*"label"\s*:\s*"([^"]+)"[^}]*"hw_part"\s*:\s*"([^"]+)"',
                    r'"device_id"\s*:\s*"([a-f0-9-]{36})"[^}]*"label"\s*:\s*"([^"]+)"[^}]*"model"\s*:\s*"([^"]+)"',
                    r'"([a-f0-9-]{36})"\s*:\s*{[^{}]*"hw_part"\s*:\s*"([^"]+)"[^{}]*"label"\s*:\s*"([^"]+)"'  # Alternative order
                ]
                
                device_data = {}
                
                # Extract UUID -> label/name mappings (only for devices with proper metadata)
                for pattern in device_uuid_patterns:
                    matches = re.findall(pattern, content, re.IGNORECASE)
                    for match in matches:
                        if len(match) >= 3:  # UUID, label, hw_part/model
                            uuid, label, hw_part = match[0], match[1], match[2]
                            # Only include devices with meaningful names and valid model info
                            if (label.strip() and 
                                hw_part.strip() and 
                                hw_part.strip().lower() not in ['unknown', 'null', 'none', ''] and
                                len(hw_part.strip()) > 2):  # Valid model name
                                device_data[uuid] = {
                                    "uuid": uuid,
                                    "name": label.strip(),
                                    "model": hw_part.strip(),
                                    "id": uuid
                                }
                                _LOGGER.debug(
                                    "Found device: uuid=%s, name='%s', model='%s'",
                                    uuid[:8] + "...",
                                    label.strip(),
                                    hw_part.strip()
                                )
                
                devices = list(device_data.values())
                
                total_time = time.time() - start_time
                _LOGGER.info(
                    "Found %d devices with determined models in %.2fs",
                    len(devices),
                    total_time
                )
                
                if not devices:
                    _LOGGER.warning("No devices found in dashboard - this may be an issue")
                    _LOGGER.debug("Content excerpt (first 500 chars): %s", content[:500])
                
                return devices

        except aiohttp.ClientError as exception:
            request_time = time.time() - start_time
            self._failed_request_count += 1
            _LOGGER.error(
                "Network error getting device list after %.2fs: %s",
                request_time,
                exception,
                exc_info=True
            )
            return []
        except Exception as exception:
            request_time = time.time() - start_time
            _LOGGER.error(
                "Unexpected error getting device list after %.2fs: %s",
                request_time,
                exception,
                exc_info=True
            )
            return []

    async def async_get_sensor_data(self, device_id: str, metric: str, start_time: int | None = None, end_time: int | None = None) -> dict[str, Any]:
        """Get sensor data for a specific device and metric."""
        # Check session validity first
        if not self._is_session_valid():
            _LOGGER.debug("Session invalid, re-authenticating before fetching sensor data")
            if not await self.async_authenticate():
                _LOGGER.error("Re-authentication failed for sensor data fetch")
                return {}

        if not start_time:
            start_time = int(time.time()) - 3600  # Last hour
        if not end_time:
            end_time = int(time.time())

        _LOGGER.debug(
            "Fetching sensor data: device=%s..., metric=%s, time_range=%d-%d",
            device_id[:8],
            metric,
            start_time,
            end_time
        )

        async def _fetch_sensor_data():
            """Internal function to fetch sensor data (used with retry logic)."""
            try:
                # Build the query based on the metric type
                if metric == "moisture":
                    # Special handling for moisture sensors with different models
                    query = f'round(avg(label_del((moisture_humidity_pct{{device_id="{device_id}",device_model="MHT02"}} or moisture_resistance_pct{{device_id="{device_id}",device_model!="MHT02"}} or moisture_pct{{device_id="{device_id}",device_model!="MHT02"}}),"scrape_id"))by(device_id),0.01)'
                else:
                    query = f'round(avg(label_del({metric}{{device_id="{device_id}"}},"scrape_id"))by(device_id),0.01)'

                url = f"{VMPROXY_BASE_URL}/{self.installation_id}/query_range"
                params = {
                    "query": query,
                    "start": start_time,
                    "end": end_time,
                    "step": 300  # 5 minute intervals
                }

                timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
                request_start = time.time()
                
                async with self.session.get(url, params=params, timeout=timeout) as response:
                    request_time = time.time() - request_start
                    self._request_count += 1
                    
                    _LOGGER.debug(
                        "Sensor data response: device=%s..., metric=%s, status=%d, time=%.2fs",
                        device_id[:8],
                        metric,
                        response.status,
                        request_time
                    )
                    
                    if response.status == 401 or response.status == 403:
                        _LOGGER.warning(
                            "Authentication error (status=%d) fetching sensor data",
                            response.status
                        )
                        self._mark_authentication_failure()
                        raise aiohttp.ClientResponseError(
                            request_info=response.request_info,
                            history=response.history,
                            status=response.status,
                            message="Authentication required"
                        )
                    
                    if response.status != 200:
                        _LOGGER.error(
                            "Failed to get sensor data: device=%s..., metric=%s, status=%d",
                            device_id[:8],
                            metric,
                            response.status
                        )
                        self._failed_request_count += 1
                        return {}
                    
                    data = await response.json()
                    
                    # Validate response structure
                    if not isinstance(data, dict):
                        _LOGGER.warning(
                            "Invalid sensor data response format for device=%s..., metric=%s: expected dict, got %s",
                            device_id[:8],
                            metric,
                            type(data).__name__
                        )
                        return {}
                    
                    # Log success with data size
                    result_count = 0
                    if data.get("data", {}).get("result"):
                        result_count = len(data["data"]["result"])
                    
                    _LOGGER.debug(
                        "Successfully fetched sensor data: device=%s..., metric=%s, results=%d",
                        device_id[:8],
                        metric,
                        result_count
                    )
                    
                    return data

            except aiohttp.ClientError as exc:
                self._failed_request_count += 1
                _LOGGER.warning(
                    "Network error fetching sensor data: device=%s..., metric=%s, error=%s",
                    device_id[:8],
                    metric,
                    exc
                )
                raise

        try:
            # Use retry logic for sensor data fetching
            return await self._retry_with_backoff(_fetch_sensor_data)
        except Exception as exception:
            _LOGGER.error(
                "Error getting sensor data after retries: device=%s..., metric=%s, error=%s",
                device_id[:8],
                metric,
                exception,
                exc_info=True
            )
            return {}

    async def async_get_data(self) -> dict[str, Any]:
        """Get all sensor data."""
        start_time = time.time()
        _LOGGER.debug("Starting data fetch cycle")
        
        # Check session validity first
        if not self._is_session_valid():
            _LOGGER.info("Session invalid or expired, re-authenticating before data fetch...")
            if not await self.async_authenticate():
                _LOGGER.error("Re-authentication failed, cannot fetch data")
                return {}

        try:
            devices = await self.async_get_device_list()
            if not devices:
                _LOGGER.warning("No devices available to fetch data from")
                return {}

            _LOGGER.debug("Fetching data for %d devices", len(devices))
            result = {"devices": [], "sensors": {}}

            # Get current data for all metrics for each device
            metrics = [
                "temperature_ambient_celsius",
                "rel_humidity_ambient_pct", 
                "abs_humidity_ambient_gm3",
                "moisture"
            ]

            successful_devices = 0
            failed_devices = 0

            for device in devices:
                # Validate device structure
                if not isinstance(device, dict):
                    _LOGGER.warning("Invalid device structure: expected dict, got %s", type(device).__name__)
                    failed_devices += 1
                    continue
                
                if "uuid" not in device:
                    _LOGGER.warning("Device missing 'uuid' field: %s", device)
                    failed_devices += 1
                    continue
                    
                device_id = device["uuid"]
                device_name = device.get("name", "Unknown")
                _LOGGER.debug("Fetching metrics for device: %s (%s...)", device_name, device_id[:8])
                
                device_data = {}
                successful_metrics = 0
                failed_metrics = 0

                for metric in metrics:
                    try:
                        metric_start = time.time()
                        data = await self.async_get_sensor_data(device_id, metric)
                        metric_time = time.time() - metric_start
                        
                        # Defensive validation of response structure
                        if not isinstance(data, dict):
                            _LOGGER.debug(
                                "Invalid data type for device=%s..., metric=%s: got %s",
                                device_id[:8],
                                metric,
                                type(data).__name__
                            )
                            failed_metrics += 1
                            continue
                        
                        # Extract the latest value
                        if data.get("data", {}).get("result"):
                            result_data = data["data"]["result"]
                            if result_data and len(result_data) > 0:
                                values = result_data[0].get("values", [])
                                if values:
                                    # Get the latest value
                                    latest_value = values[-1][1] if len(values) > 0 else None
                                    if latest_value is not None:
                                        try:
                                            device_data[metric] = float(latest_value)
                                            successful_metrics += 1
                                            _LOGGER.debug(
                                                "Got %s for device %s: %.2f (%.2fs)",
                                                metric,
                                                device_name,
                                                float(latest_value),
                                                metric_time
                                            )
                                        except (ValueError, TypeError) as exc:
                                            _LOGGER.warning(
                                                "Invalid sensor value for device=%s..., metric=%s, value=%s: %s",
                                                device_id[:8],
                                                metric,
                                                latest_value,
                                                exc
                                            )
                                            failed_metrics += 1
                                    else:
                                        _LOGGER.debug(
                                            "No value in latest data for device=%s..., metric=%s",
                                            device_id[:8],
                                            metric
                                        )
                                        failed_metrics += 1
                                else:
                                    _LOGGER.debug(
                                        "No values array for device=%s..., metric=%s",
                                        device_id[:8],
                                        metric
                                    )
                                    failed_metrics += 1
                            else:
                                _LOGGER.debug(
                                    "Empty result data for device=%s..., metric=%s",
                                    device_id[:8],
                                    metric
                                )
                                failed_metrics += 1
                        else:
                            _LOGGER.debug(
                                "No result data for device=%s..., metric=%s",
                                device_id[:8],
                                metric
                            )
                            failed_metrics += 1

                    except Exception as exception:
                        failed_metrics += 1
                        _LOGGER.error(
                            "Error getting %s for device %s (%s...): %s",
                            metric,
                            device_name,
                            device_id[:8],
                            exception,
                            exc_info=True
                        )

                # Only include devices that have actual sensor data
                if device_data:
                    result["devices"].append(device)
                    result["sensors"][device["id"]] = device_data
                    successful_devices += 1
                    _LOGGER.debug(
                        "Device %s: %d metrics successful, %d failed",
                        device_name,
                        successful_metrics,
                        failed_metrics
                    )
                else:
                    failed_devices += 1
                    _LOGGER.warning(
                        "No sensor data available for device %s (%s...) - all metrics failed",
                        device_name,
                        device_id[:8]
                    )

            total_time = time.time() - start_time
            _LOGGER.info(
                "Data fetch complete: %d devices successful, %d failed, %.2fs total, "
                "requests=%d, failed_requests=%d",
                successful_devices,
                failed_devices,
                total_time,
                self._request_count,
                self._failed_request_count
            )
            
            return result

        except Exception as exception:
            total_time = time.time() - start_time
            _LOGGER.error(
                "Unexpected error in async_get_data after %.2fs: %s",
                total_time,
                exception,
                exc_info=True
            )
            return {} 