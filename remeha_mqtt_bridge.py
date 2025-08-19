import can
import paho.mqtt.client as mqtt
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import time

CONFIG_FILE = "/home/pi/remeha_mqtt_bridge/remeha_mqtt_bridge.conf"

# Set timezone
local_tz = ZoneInfo(time.tzname[0])

# Read Config
config = {
    "broker": "localhost",
    "port": 1883,
    "username": None,
    "password": None
}

with open(CONFIG_FILE, "r") as f:
    for line in f:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, val = line.split("=", 1)
            config[key.strip()] = val.strip()

broker = config.get("broker")
port = int(config.get("port", 1883))
username = config.get("username")
password = config.get("password")

# MQTT setup
client = mqtt.Client(client_id="remeha_bridge")
if username and password:
    client.username_pw_set(username, password)

client.connect(broker, port)
client.loop_start()

# Home Assistant MQTT discovery
DEVICE = {
    "identifiers": ["remeha_cv_ketel"],
    "name": "Remeha CV Ketel",
    "manufacturer": "Remeha",
    "model": "CAN-bus ketel"
}

DISCOVERY_PREFIX = "homeassistant"
STATE_PREFIX = "remeha"

SENSOR_CONFIGS = {
    "power": {"unit": "%", "name": "Vermogen", "icon": "mdi:fire"},
    "flowtemperature": {"unit": "°C", "device_class": "temperature", "name": "Flowtemperatuur", "icon": "mdi:thermometer"},
    "setpoint": {"unit": "°C", "device_class": "temperature", "name": "Setpoint", "icon": "mdi:target"},
    "pressure": {"unit": "bar", "device_class": "pressure", "name": "Druk", "icon": "mdi:gauge"},
    "statusid": {"unit": None, "name": "Status ID", "icon": "mdi:numeric"},
    "statusdescription": {"unit": None, "name": "Statusomschrijving", "icon": "mdi:text"},
    "datetime": {"unit": None, "device_class": "timestamp", "name": "Datum/tijd", "icon": "mdi:calendar-clock"},
}

for sensor, cfg in SENSOR_CONFIGS.items():
    discovery_topic = f"{DISCOVERY_PREFIX}/sensor/remeha_{sensor}/config"
    state_topic = f"{STATE_PREFIX}/{sensor}"
    payload = {
        "name": cfg["name"],
        "unique_id": f"remeha_{sensor}",
        "state_topic": state_topic,
        "unit_of_measurement": cfg.get("unit"),
        "device_class": cfg.get("device_class"),
        "icon": cfg.get("icon"),
        "device": DEVICE
    }
    client.publish(discovery_topic, json.dumps(payload), retain=True)

# Status map
status_map = {
    0: "stand-by", 1: "demand", 2: "start generator", 3: "heat active",
    4: "dhw active", 5: "stop generator", 6: "pump active", 8: "delay",
    9: "block", 10: "lock", 11: "test heat min", 12: "test heat max",
    13: "test DWH max", 15: "manual heat", 16: "frost protection",
    19: "reset", 21: "paused", 200: "service mode"
}

# Current state
state = {
    "power": -1.0,
    "flowtemperature": -1.0,
    "setpoint": -1.0,
    "roomsetpoint": -1.0,
    "pressure": -1.0,
    "statusid": 254,
    "statusdescription": "unknown",
    "datetime": "1984-01-01T00:00:00"
}

expect_pressure_next = False
remeha_date = "1984-01-01"
remeha_time = "00:00:00"

def publish(sensor, value):
    topic = f"{STATE_PREFIX}/{sensor}"
    client.publish(topic, json.dumps(value), retain=True)

# CAN bus setup
bus = can.interface.Bus(channel='can0', bustype='socketcan')

print("Starting CAN read loop...")

while True:
    msg = bus.recv()

    if msg is None:
        continue

    can_id = msg.arbitration_id
    data = list(msg.data)

    # Date/time from CAN ID 0x100, 6 bytes little endian
    if can_id == 0x100 and len(data) == 6:
        ms = data[0] + (data[1]<<8) + (data[2]<<16) + (data[3]<<24)
        seconds = ms // 1000
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60

        days = data[4] + (data[5]<<8)
        date_obj = datetime(1984, 1, 1) + timedelta(days=days)

        # Fix for 24:00:00
        if hours == 24:
            hours = 0
            date_obj += timedelta(days=1)

        remeha_time = f"{hours:02d}:{minutes:02d}:{secs:02d}"
        remeha_date = date_obj.strftime("%Y-%m-%d")

        dt_obj = datetime.strptime(f"{remeha_date} {remeha_time}", "%Y-%m-%d %H:%M:%S").replace(tzinfo=local_tz)
        state["datetime"] = dt_obj
        client.publish("remeha/datetime", dt_obj.isoformat(), retain=True)

    elif can_id == 0x282 and len(data) >= 5:
        power = data[0]
        flow_temp_raw = data[1] + (data[2]<<8)
        flowtemperature = round(flow_temp_raw / 100.0, 2)

        if state["power"] != power:
            state["power"] = power
            publish("power", power)

        if abs(state["flowtemperature"] - flowtemperature) > 0.01:
            state["flowtemperature"] = flowtemperature
            publish("flowtemperature", flowtemperature)

    elif can_id == 0x382 and len(data) >= 3:
        setpoint_raw = data[1] + (data[2]<<8)
        setpoint = round(setpoint_raw / 100.0, 2)
        if abs(state["setpoint"] - setpoint) > 0.01:
            state["setpoint"] = setpoint
            publish("setpoint", setpoint)

    elif can_id == 0x1C1 and len(data) >= 8:
        if expect_pressure_next:
            pressure = round(data[5] / 10.0, 2)
            if abs(state["pressure"] - pressure) > 0.01:
                state["pressure"] = pressure
                publish("pressure", pressure)
            expect_pressure_next = False
        elif data[0:3] == [0x41, 0x3F, 0x50]:
            expect_pressure_next = True

    elif can_id == 0x481 and len(data) >= 1:
        sid = data[0]
        if state["statusid"] != sid:
            state["statusid"] = sid
            state["statusdescription"] = status_map.get(sid, "unknown")
            publish("statusid", sid)
            statedescr = state["statusdescription"]
            client.publish("remeha/statusdescription", f"{statedescr}", retain=True)
