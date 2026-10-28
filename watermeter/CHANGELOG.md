# Changelog

## 0.1.3

- Fixes MQTT: the add-on now gets its broker from the Supervisor (the token was lost at startup)

## 0.1.2

- Fixes the release build (test fixtures were missing). First published version.

## 0.1.1

- First release: reads the meter from the ESP32-CAM, validates the reading and publishes it to Home Assistant over MQTT.

## 0.1.0

- First packaged version: the add-on installs and starts. Reading, validation and the web pages are added step by step.
