"""Constants for the Senzomatic integration."""

DOMAIN = "senzomatic"

# Configuration
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_OAUTH_CLIENT_ID = "oauth_client_id"

# API URLs based on the network analysis
LOGIN_URL = "https://erp.mgrd.cz/cs/users/sign_in"
OAUTH_AUTHORIZE_URL = "https://erp.mgrd.cz/oauth/authorize"
DASHBOARD_BASE_URL = "https://dashboards.mgrd.cz"
VMPROXY_BASE_URL = "https://vmproxy.mgrd.cz/api/v1"

# Device models
DEVICE_MODEL_MHT02 = "MHT02"
DEVICE_MODEL_HT03 = "HT03"
DEVICE_MODEL_MHT04 = "MHT04"

# Sensor types
SENSOR_TEMPERATURE = "temperature_ambient_celsius"
SENSOR_REL_HUMIDITY = "rel_humidity_ambient_pct"
SENSOR_ABS_HUMIDITY = "abs_humidity_ambient_gm3"
SENSOR_MOISTURE = "moisture"

# Units
UNIT_CELSIUS = "°C"
UNIT_PERCENT = "%"
UNIT_GRAMS_PER_M3 = "g/m³" 