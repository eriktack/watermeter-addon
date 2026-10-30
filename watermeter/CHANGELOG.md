# Changelog

## 0.2.0

- Settings page in the add-on: capture, recognition and validation settings apply at once without a restart (the Configuration tab keeps only the connection). New max jump rule. Set current value on the Live page

## 0.1.9

- Regions: digit width per digit, gap between digits, y counted from the bottom, live update while an arrow is held. Log and Live: local times, the raw flow next to the volume

## 0.1.8

- Recognition: contrast enhancement on the digit crops (option enhance_contrast) and dig-class11_1701 as the default model; much better on the LCD

## 0.1.7

- Live, Log and Labels pages: frames are shown turned by the rotation offset, as the reading sees them

## 0.1.6

- Web: the pages load the new script after an update (the Regions page ran a cached old one)

## 0.1.5

- Regions: digits and decimals as groups that move and resize together, separate counts for the flow line, rotation offset

## 0.1.4

- Capture: the first image of a burst is thrown away (it was the stale buffered frame, sometimes black)

## 0.1.3

- Fixes MQTT: the add-on now gets its broker from the Supervisor (the token was lost at startup)

## 0.1.2

- Fixes the release build (test fixtures were missing). First published version.

## 0.1.1

- First release: reads the meter from the ESP32-CAM, validates the reading and publishes it to Home Assistant over MQTT.

## 0.1.0

- First packaged version: the add-on installs and starts. Reading, validation and the web pages are added step by step.
