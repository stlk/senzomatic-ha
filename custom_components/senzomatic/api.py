"""API client for Senzomatic moisture monitoring system."""
from __future__ import annotations

import asyncio
import logging
import re
import time
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

    async def async_authenticate(self) -> bool:
        """Authenticate with the Senzomatic system."""
        try:
            # Step 1: Get login page to extract authenticity token
            _LOGGER.debug("Getting login page...")
            async with self.session.get(LOGIN_URL) as response:
                if response.status != 200:
                    _LOGGER.error("Failed to get login page: %s", response.status)
                    return False
                
                content = await response.text()
                # Extract authenticity token from the form
                token_match = re.search(r'name="authenticity_token" value="([^"]*)"', content)
                if not token_match:
                    _LOGGER.error("Could not find authenticity token")
                    _LOGGER.error("Content: %s", content)
                    return False
                
                authenticity_token = token_match.group(1)
                _LOGGER.debug("Found authenticity token: %s", authenticity_token[:10] + "...")

            # Step 2: Submit login form
            _LOGGER.debug("Submitting login form...")
            login_data = {
                "user[email]": self.username,
                "user[password]": self.password,
                "authenticity_token": authenticity_token,
                "commit": "Přihlásit se"
            }

            async with self.session.post(LOGIN_URL, data=login_data, allow_redirects=False) as response:
                _LOGGER.debug("Login response status: %s", response.status)
                _LOGGER.debug("Login response headers: %s", dict(response.headers))
                
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
                            _LOGGER.info("Found installation ID from login redirect: %s", installation_id)
                            self.installation_id = installation_id
                            self.authenticated = True
                            return True
                            
                elif response.status == 200:
                    # Status 200 usually means we stayed on the login page = failed login
                    content = await response.text()
                    if 'sign_in' in str(response.url).lower() or 'alert' in content.lower() or 'error' in content.lower():
                        _LOGGER.error("Login failed: Invalid credentials (stayed on login page)")
                        return False
                else:
                    _LOGGER.error("Login failed: %s", response.status)
                    return False

            # Step 3: Follow OAuth flow to get to dashboard
            # The system will redirect through OAuth authorization
            oauth_url = f"{OAUTH_AUTHORIZE_URL}?client_id={self.oauth_client_id}&redirect_uri={DASHBOARD_BASE_URL}/oauth/callback%3Flocale%3Dcs&response_type=code&scope=erp_api+erp_api_remote_control+reporter_api"
            _LOGGER.debug("OAuth URL: %s", oauth_url)
            
            async with self.session.get(oauth_url, allow_redirects=True) as response:
                final_url = str(response.url)
                _LOGGER.debug("OAuth final URL: %s", final_url)
                _LOGGER.debug("OAuth response status: %s", response.status)
                
                if response.status != 200:
                    _LOGGER.error("OAuth flow failed: %s", response.status)
                    return False
                
                # Try multiple patterns to extract installation ID
                installation_id = None
                
                # Pattern 1: /charts/ in URL
                if "/charts/" in final_url:
                    url_parts = final_url.split("/charts/")
                    if len(url_parts) > 1:
                        installation_id = url_parts[1].split('/')[0].split('?')[0]
                        _LOGGER.info("Found installation ID from /charts/: %s", installation_id)
                
                # Pattern 2: Check the page content for installation ID
                if not installation_id:
                    content = await response.text()
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
                            _LOGGER.info("Found installation ID with pattern '%s': %s", pattern, installation_id)
                            break
                
                # Pattern 3: Try to navigate directly to dashboard and look for redirects
                if not installation_id:
                    _LOGGER.debug("Trying direct dashboard access...")
                    dashboard_url = f"{DASHBOARD_BASE_URL}/cs"
                    async with self.session.get(dashboard_url, allow_redirects=True) as dash_response:
                        dash_url = str(dash_response.url)
                        _LOGGER.debug("Dashboard redirect URL: %s", dash_url)
                        
                        if "/charts/" in dash_url:
                            url_parts = dash_url.split("/charts/")
                            if len(url_parts) > 1:
                                installation_id = url_parts[1].split('/')[0].split('?')[0]
                                _LOGGER.info("Found installation ID from dashboard redirect: %s", installation_id)
                        else:
                            # If we're on the general dashboard, try to extract from page content
                            content = await dash_response.text()
                            _LOGGER.debug("Dashboard content length: %d", len(content))
                            
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
                                    _LOGGER.info("Found installation ID with dashboard pattern '%s': %s", pattern, installation_id)
                                    break
                
                self.installation_id = installation_id
                
                if not self.installation_id:
                    _LOGGER.error("Could not extract installation ID from URL: %s", final_url)
                    _LOGGER.error("This might mean:")
                    _LOGGER.error("  1. Login credentials are incorrect")
                    _LOGGER.error("  2. Account doesn't have access to any installations")
                    _LOGGER.error("  3. The authentication flow has changed")
                    return False

            self.authenticated = True
            return True

        except Exception as exception:
            _LOGGER.error("Authentication error: %s", exception)
            return False

    async def async_get_device_list(self) -> list[dict[str, Any]]:
        """Get list of devices from the HTML page."""
        if not self.authenticated:
            if not await self.async_authenticate():
                return []

        try:
            dashboard_url = f"{DASHBOARD_BASE_URL}/cs/charts/{self.installation_id}"
            async with self.session.get(dashboard_url) as response:
                if response.status != 200:
                    _LOGGER.error("Failed to get dashboard: %s", response.status)
                    return []
                
                content = await response.text()
                
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
                
                devices = list(device_data.values())
                
                _LOGGER.debug("Extracted %d devices with determined models", len(devices))
                for device in devices:
                    _LOGGER.debug("Device: %s (%s) - Model: %s", 
                                device['name'], device.get('uuid', 'NO UUID'), device['model'])

                _LOGGER.info("Found %d devices with determined models", len(devices))
                return devices

        except Exception as exception:
            _LOGGER.error("Error getting device list: %s", exception)
            return []

    async def async_get_sensor_data(self, device_id: str, metric: str, start_time: int | None = None, end_time: int | None = None) -> dict[str, Any]:
        """Get sensor data for a specific device and metric."""
        if not self.authenticated:
            if not await self.async_authenticate():
                return {}

        if not start_time:
            start_time = int(time.time()) - 3600  # Last hour
        if not end_time:
            end_time = int(time.time())

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

            async with self.session.get(url, params=params) as response:
                if response.status != 200:
                    _LOGGER.error("Failed to get sensor data: %s", response.status)
                    return {}
                
                data = await response.json()
                return data

        except Exception as exception:
            _LOGGER.error("Error getting sensor data: %s", exception)
            return {}

    async def async_get_data(self) -> dict[str, Any]:
        """Get all sensor data."""
        if not self.authenticated:
            if not await self.async_authenticate():
                return {}

        devices = await self.async_get_device_list()
        if not devices:
            return {}

        result = {"devices": [], "sensors": {}}

        # Get current data for all metrics for each device
        metrics = [
            "temperature_ambient_celsius",
            "rel_humidity_ambient_pct", 
            "abs_humidity_ambient_gm3",
            "moisture"
        ]

        for device in devices:
            if "uuid" not in device:
                continue
                
            device_id = device["uuid"]
            device_data = {}

            for metric in metrics:
                try:
                    data = await self.async_get_sensor_data(device_id, metric)
                    
                    # Extract the latest value
                    if data.get("data", {}).get("result"):
                        result_data = data["data"]["result"]
                        if result_data and len(result_data) > 0:
                            values = result_data[0].get("values", [])
                            if values:
                                # Get the latest value
                                latest_value = values[-1][1] if len(values) > 0 else None
                                if latest_value is not None:
                                    device_data[metric] = float(latest_value)

                except Exception as exception:
                    _LOGGER.error("Error getting %s for device %s: %s", metric, device_id, exception)

            # Only include devices that have actual sensor data
            if device_data:
                result["devices"].append(device)
                result["sensors"][device["id"]] = device_data

        return result 