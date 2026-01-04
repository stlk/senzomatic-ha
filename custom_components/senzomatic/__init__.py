"""The Senzomatic integration."""
from __future__ import annotations

import asyncio
import certifi
import logging
import ssl
from datetime import timedelta

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import SenzomaticAPI
from .const import DOMAIN, CONF_OAUTH_CLIENT_ID

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Senzomatic from a config entry."""
    _LOGGER.info("Setting up Senzomatic integration for entry: %s", entry.entry_id)
    
    try:
        # Create custom session with up-to-date SSL context
        ssl_context = ssl.create_default_context(cafile=certifi.where())
        connector = aiohttp.TCPConnector(ssl=ssl_context)
        session = aiohttp.ClientSession(connector=connector)
        _LOGGER.debug("Created custom ClientSession with certifi CA bundle: %s", certifi.where())
        
        api = SenzomaticAPI(
            session, 
            entry.data["username"], 
            entry.data["password"],
            entry.data[CONF_OAUTH_CLIENT_ID]
        )
        
        coordinator = SenzomaticDataUpdateCoordinator(hass, api)
        
        _LOGGER.debug("Performing initial data refresh...")
        await coordinator.async_config_entry_first_refresh()
        _LOGGER.info("Initial data refresh completed successfully")
        
        hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
        
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        
        _LOGGER.info("Senzomatic integration setup completed successfully")
        return True
    except Exception as exception:
        _LOGGER.error(
            "Failed to set up Senzomatic integration: %s",
            exception,
            exc_info=True
        )
        raise

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.info("Unloading Senzomatic integration for entry: %s", entry.entry_id)
    
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        coordinator = hass.data[DOMAIN].pop(entry.entry_id)
        
        # Close the custom session
        await coordinator.api.session.close()
        _LOGGER.debug("Closed custom ClientSession")
        
        _LOGGER.info(
            "Senzomatic integration unloaded successfully (requests: %d, failed: %d)",
            coordinator.api._request_count,
            coordinator.api._failed_request_count
        )
    else:
        _LOGGER.error("Failed to unload Senzomatic integration platforms")
    
    return unload_ok

class SenzomaticDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching data from the Senzomatic API."""

    def __init__(self, hass: HomeAssistant, api: SenzomaticAPI) -> None:
        """Initialize."""
        self.api = api
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=5),
        )

    async def _async_update_data(self):
        """Update data via library."""
        try:
            _LOGGER.debug("Starting coordinator data update")
            data = await self.api.async_get_data()
            
            # Log summary of what we got
            if data:
                device_count = len(data.get("devices", []))
                sensor_count = len(data.get("sensors", {}))
                _LOGGER.debug(
                    "Coordinator update successful: %d devices, %d sensor sets",
                    device_count,
                    sensor_count
                )
            else:
                _LOGGER.warning("Coordinator update returned empty data")
            
            return data
        except Exception as exception:
            _LOGGER.error(
                "Failed to update data from Senzomatic API: %s",
                exception,
                exc_info=True
            )
            raise UpdateFailed(f"Error communicating with API: {exception}") from exception 