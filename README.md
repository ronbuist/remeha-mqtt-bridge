# remeha-mqtt-bridge
A bridge to translate CAN messages from a Remeha Calenta Ace (or similar) boiler to MQTT messages for Home Assistant

This is basically the Python version of the Bash shell script in [this repository](https://github.com/ronbuist/remeha-can-interface). I have added MQTT discovery messages so Home Assistant will automatically add the entities.

## Prerequisites

Please make sure you have [paho-mqtt](https://pypi.org/project/paho-mqtt/) and [python-can](https://pypi.org/project/python-can/) installed.

## Services

### can0.service
```
[Unit]
Description=CAN0 interface setup
Before=remeha_can.service
Wants=network.target

[Service]
Type=oneshot
ExecStart=/sbin/ip link set dev can0 up type can bitrate 1000000
ExecStop=/sbin/ip link set dev can0 down
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
```

### remeha_can.service
```
[Unit]
Description=Remeha CAN Bus to MQTT Service
After=network.target can0.service

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/remeha
ExecStart=/usr/bin/python3 /home/pi/remeha/remeha_can.py
Restart=on-failure
RestartSec=5s

[Install]
WantedBy=multi-user.target
```
