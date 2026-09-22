# mqtt_client.py
import json
import time
import threading
from pathlib import Path

import paho.mqtt.client as mqtt

from shared.vlc_network_helper import get_role, get_primary_ip, is_enabled
from shared.vlc_helper import log

PORT = 1883
TOPIC_SCHEDULE = "video/schedule"
TOPIC_CONTROL = "video/control"

HOME = Path.home()
MQTT_STATUS_FILE = HOME / "mqtt_status.json"


# --------------------------------------------------
# MQTT status
# --------------------------------------------------
def save_mqtt_status(connected):
    status = {
        "connected": connected
    }

    try:
        with open(MQTT_STATUS_FILE, "w") as f:
            json.dump(status, f)
    except Exception as e:
        log(f"Failed to save MQTT status: {e}")


# --------------------------------------------------
# Determine MQTT broker from Network Settings
# --------------------------------------------------
role = get_role()

if role == "primary":
    BROKER = "localhost"
elif role == "secondary":
    BROKER = get_primary_ip()
else:
    raise ValueError(f"Invalid role: {role}")


# --------------------------------------------------
# MQTT callbacks
# --------------------------------------------------
def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        log(f"MQTT Connected successfully to {BROKER}")

        save_mqtt_status(True)

        if role == "secondary":
            client.subscribe(TOPIC_CONTROL)
            log(f"Subscribed to {TOPIC_CONTROL}")

    else:
        log(f"MQTT Connection failed with code {rc}")
        save_mqtt_status(False)


def on_disconnect(client, userdata, flags, rc, properties=None):
    save_mqtt_status(False)
    log(f"MQTT disconnected from {BROKER}")


# --------------------------------------------------
# MQTT client setup
# --------------------------------------------------
try:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
except AttributeError:
    client = mqtt.Client()

client.on_connect = on_connect
client.on_disconnect = on_disconnect


# --------------------------------------------------
# Secondary MQTT connection thread
# --------------------------------------------------
def secondary_mqtt_worker():

    log("Starting Secondary MQTT worker.")

    # Start MQTT network loop once.
    client.loop_start()

    while True:

        if not is_enabled():
            save_mqtt_status(False)
            log("MQTT disabled. Checking again in 30 seconds.")
            time.sleep(30)
            continue

        if client.is_connected():
            time.sleep(30)
            continue

        try:
            log(f"Connecting MQTT to {BROKER}:{PORT}...")

            client.connect(BROKER, PORT, 60)

            # Give the MQTT callback time to run.
            for _ in range(20):
                if client.is_connected():
                    break
                time.sleep(0.1)

            if client.is_connected():
                log("MQTT connection established.")
            else:
                save_mqtt_status(False)
                log("MQTT connection not established.")

        except Exception as e:
            save_mqtt_status(False)
            log(f"MQTT connection failed: {e}")

        if not client.is_connected():
            save_mqtt_status(False)
            log("MQTT unavailable. Retrying in 30 seconds.")
            time.sleep(30)


# --------------------------------------------------
# Start MQTT
# --------------------------------------------------
if is_enabled():

    if role == "primary":

        log(f"Connecting MQTT to {BROKER}:{PORT}...")

        client.connect(BROKER, PORT, 60)

        # Keep MQTT network traffic running.
        client.loop_start()

        for _ in range(20):
            if client.is_connected():
                break
            time.sleep(0.1)

        log(f"MQTT connection status: {client.is_connected()}")

        if not client.is_connected():
            save_mqtt_status(False)

    elif role == "secondary":

        # Secondary must not block VLC startup.
        mqtt_thread = threading.Thread(
            target=secondary_mqtt_worker,
            daemon=True
        )

        mqtt_thread.start()

else:
    save_mqtt_status(False)
    log("MQTT is disabled in Network Settings.")


# --------------------------------------------------
# Publish
# --------------------------------------------------
def publish(topic, data):
    """Publish JSON or text to a topic."""

    if not is_enabled():
        log("MQTT disabled; skipping publish.")
        return

    if isinstance(data, (dict, list)):
        data = json.dumps(data)

    # Make sure we are connected before publishing.
    for _ in range(20):
        if client.is_connected():
            break
        time.sleep(0.1)

    if not client.is_connected():
        log(f"MQTT not connected; skipping publish to {topic}")
        return

    info = client.publish(topic, data)

    log(f"MQTT publish result: {info.rc}")

    return info