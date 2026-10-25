# Water meter

Reads the water meter with an ESP32-CAM (ESPHome), checks every reading and publishes it to Home Assistant over MQTT.
Everything runs locally.

## First start

1. Flash the camera with the ESPHome package from this repository and add it to your Wi-Fi.
2. In **Configuration**, set the camera's address (**ESPHome host**) and its API encryption key.
3. Start the add-on and open **Water meter** in the sidebar.

## Configuration

| Option | Meaning |
|---|---|
| ESPHome host / port / encryption key | The camera. Port 6053 is ESPHome's default. |
| MQTT host / port / username / password | Leave empty to use the broker the Mosquitto add-on provides. Fill in only for another broker. |
| Log level | `info` normally; `debug` when something does not work. |

Capture, recognition and validation settings are in this same Configuration tab. Changing one restarts the add-on.
To lower the published water volume (for example after a meter swap), send the new value in m³, such as `170.861`,
to the "Set current value" number entity in Home Assistant.

## Your data

Settings, state and images are kept in the add-on's own data folder and are included in Home Assistant backups.
Images of the meter never leave your Home Assistant.
