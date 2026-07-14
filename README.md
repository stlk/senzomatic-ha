# Senzomatic Home Assistant Integration

This custom integration allows you to monitor your Senzomatic moisture guard sensors in Home Assistant.

## Features

- **Temperature monitoring** - Ambient temperature from all sensors
- **Humidity monitoring** - Both relative and absolute humidity measurements
- **Moisture monitoring** - Wood moisture content (for compatible sensors)
- **Automatic device discovery** - Reads the device list straight from your Central Unit
- **Real-time updates** - Data refreshed every 5 minutes
- **Native Home Assistant entities** - Proper device classes and units

## Requirements

- A Senzomatic **Central Unit** reachable on your local network (you'll need its IP address).
- The Central Unit must have been activated and be online (it needs internet access to push data to the cloud, which this integration reads back).

> Tip: give the Central Unit a static IP or DHCP reservation on your router. If its IP changes you can update it via **Reconfigure** without losing history.

## Installation

### HACS Installation (Recommended)

1. Add this repository to HACS as a custom repository:

   [![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=stlk&repository=senzomatic-ha&category=integration)

2. Search for "Senzomatic" in HACS and install
3. Restart Home Assistant
4. Add the integration via Settings → Devices & Services

### Manual Installation

1. Copy the `custom_components/senzomatic` directory to your Home Assistant `custom_components` directory:
   ```
   config/
   └── custom_components/
       └── senzomatic/
           ├── __init__.py
           ├── api.py
           ├── config_flow.py
           ├── const.py
           ├── manifest.json
           ├── sensor.py
           ├── strings.json
           ├── brand/
           │   ├── icon.png
           │   └── logo.png
           └── translations/
               └── en.json
   ```

2. Restart Home Assistant

3. Go to Settings → Devices & Services

4. Click **Add Integration** and search for "Senzomatic"

5. Enter the **IP address** of your Central Unit (e.g. `192.168.1.230`)

## Configuration

The integration is configured through the Home Assistant UI. You only need to provide:

- **IP address**: the local address of your Senzomatic Central Unit.

### Changing the IP address

If the Central Unit's address changes, open the integration and choose **Reconfigure** to enter the new IP. The device identity is tracked by its Central Unit ID (not the IP), so your entities and their history are preserved.

## How it Works

1. **Bootstrap**: fetches `http://<central-unit-ip>/var/config.json`, which exposes the unit's long-lived access token (JWT) and the list of attached devices.
2. **Device discovery**: builds Home Assistant devices from that config (UUID, model, and the display name you set in the Senzomatic portal).
3. **Data retrieval**: queries the cloud VictoriaMetrics proxy for each metric, authenticating with the unit's JWT.
4. **Entity creation**: creates a Home Assistant sensor entity per measurement type, per device.

> **Note:** while the token and device list come from the Central Unit on your LAN, sensor *values* are read from Senzomatic's cloud (VictoriaMetrics). The Central Unit does not expose historical values locally, so this integration still requires internet access. It is classified as `cloud_polling`.

## Supported Sensors

- **HT03** - Temperature and humidity sensors
- **MHT04** - Multi-sensor units with temperature, humidity, and moisture
- **MHT02** - Older moisture sensors

## Sensor Types

For each device, the following sensors may be available:

- **Temperature** (°C) - Ambient temperature
- **Relative Humidity** (%) - Relative humidity percentage
- **Absolute Humidity** (g/m³) - Absolute humidity in grams per cubic meter
- **Wood Moisture** (%) - Moisture content in wood (MHT units only)

## API Details

### Bootstrap (local)
- `GET http://<central-unit-ip>/var/config.json`
- Provides `global.jwt_token` (the access token) and the `devices` map (UUID, `type`, `display_name`).
- The Central Unit UUID (parsed from the config's cloud URLs) is used as the stable Home Assistant unique ID.

### Data Retrieval (cloud)
- Base URL: `https://vmproxy.senzomatic.com/api/v1/query_range`
- Auth: `Authorization: Bearer <jwt_token>` (tenant scoping is embedded in the token)
- Uses Prometheus/VictoriaMetrics query format, filtered by device UUID

### Example Queries
```
# Temperature
round(avg(label_del(temperature_ambient_celsius{device_id="uuid"},"scrape_id"))by(device_id),0.01)

# Relative Humidity
round(avg(label_del(rel_humidity_ambient_pct{device_id="uuid"},"scrape_id"))by(device_id),0.01)

# Wood Moisture (source metric differs by device model)
round(avg(label_del((moisture_humidity_pct{device_id="uuid",device_model="MHT02"} or moisture_resistance_pct{device_id="uuid",device_model!="MHT02"} or moisture_pct{device_id="uuid",device_model!="MHT02"}),"scrape_id"))by(device_id),0.01)
```

## Troubleshooting

### Cannot connect
- Verify the IP address is correct and the Central Unit is reachable: open `http://<central-unit-ip>/` in a browser — you should see the unit's web page.
- Make sure Home Assistant and the Central Unit are on the same network / VLAN.

### No sensors found
- Confirm devices are online and reporting in the Senzomatic portal.
- Only devices that return data for at least one metric are added.

### Data not updating
- The integration polls every 5 minutes.
- Because values come from the cloud, check the Central Unit has internet access and Home Assistant can reach `vmproxy.senzomatic.com`.
- If the unit's token is rotated, the integration drops the cached token and re-reads it from the Central Unit on the next cycle.

### Upgrading from 1.x
Version 1.x used your Senzomatic account credentials. On upgrade, the integration will prompt you to **re-authenticate** — just enter the Central Unit's IP address.

## License

This project is licensed under the MIT License.

## Disclaimer

This integration is not officially supported by Senzomatic. Use at your own risk.
