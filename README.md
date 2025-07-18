# Senzomatic Home Assistant Integration

This custom integration allows you to monitor your Senzomatic moisture guard sensors in Home Assistant.

## Features

- **Temperature monitoring** - Ambient temperature from all sensors
- **Humidity monitoring** - Both relative and absolute humidity measurements  
- **Moisture monitoring** - Wood moisture content (for compatible sensors)
- **Automatic device discovery** - Finds all sensors in your installation
- **Real-time updates** - Data refreshed every 5 minutes
- **Native Home Assistant entities** - Proper device classes and units

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
           └── strings.json
   ```

2. Restart Home Assistant

3. Go to Configuration > Integrations

4. Click the "+" button and search for "Senzomatic"

5. Enter your Senzomatic login credentials (same as for erp.mgrd.cz)

## How it Works

The integration works by:

1. **Authentication**: Logs into the Senzomatic web portal using your credentials
2. **OAuth Flow**: Follows the same OAuth flow as the web interface  
3. **Device Discovery**: Parses the dashboard HTML to find your sensors
4. **Data Retrieval**: Queries the VictoriaMetrics API endpoints for sensor data
5. **Entity Creation**: Creates Home Assistant sensor entities for each measurement type

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

## Configuration

The integration is configured through the Home Assistant UI. You only need to provide:

- **Email**: Your Senzomatic account email
- **Password**: Your Senzomatic account password

## API Details

This integration reverse-engineers the Senzomatic web interface:

### Authentication Flow
1. `GET https://erp.mgrd.cz/users/sign_in` - Get login form with CSRF token
2. `POST https://erp.mgrd.cz/cs/users/sign_in` - Submit credentials  
3. OAuth redirect to `https://dashboards.mgrd.cz/oauth/callback`
4. Final redirect to dashboard with installation ID

### Data Retrieval
- Base URL: `https://vmproxy.mgrd.cz/api/v1/{installation_id}/query_range`
- Uses Prometheus/VictoriaMetrics query format
- Queries specific metrics by device UUID

### Example Queries
```
# Temperature
round(avg(label_del(temperature_ambient_celsius{device_id="uuid"},"scrape_id"))by(device_id),0.01)

# Relative Humidity  
round(avg(label_del(rel_humidity_ambient_pct{device_id="uuid"},"scrape_id"))by(device_id),0.01)

# Wood Moisture (complex query for different device types)
round(avg(label_del((moisture_humidity_pct{device_id="uuid",device_model="MHT02"} or moisture_resistance_pct{device_id="uuid",device_model!="MHT02"} or moisture_pct{device_id="uuid",device_model!="MHT02"}),"scrape_id"))by(device_id),0.01)
```

## Troubleshooting

### Authentication Issues
- Verify your credentials work on the Senzomatic web portal
- Check Home Assistant logs for authentication errors
- The integration uses the same login as https://erp.mgrd.cz

### No Sensors Found
- Ensure your account has access to moisture monitoring devices
- Check that devices are online and reporting data
- Look for device parsing errors in logs

### Data Not Updating
- Integration polls every 5 minutes by default
- Check network connectivity to mgrd.cz domains
- Verify authentication hasn't expired (automatically re-authenticates)

## Development Notes

This integration was created by analyzing network traffic from the Senzomatic web interface:

1. **Login analyzed**: Forms, CSRF tokens, redirects
2. **API endpoints discovered**: VictoriaMetrics queries  
3. **Device discovery**: HTML parsing for device information
4. **Data format**: JSON responses with time series data

The integration mimics browser behavior to access the private API endpoints.

## License

This project is licensed under the MIT License.

## Disclaimer

This integration is not officially supported by MoistureGuard or Senzomatic. Use at your own risk. 