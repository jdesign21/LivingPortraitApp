# mqtt_client.py
import json
import time
import paho.mqtt.client as mqtt

from shared.vlc_network_helper import get_role, get_primary_ip, is_enabled

PORT = 1883
TOPIC_SCHEDULE = "video/schedule"
TOPIC_CONTROL = "video/control"

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
        print(f"MQTT Connected successfully to {BROKER}")
    else:
        print(f"MQTT Connection failed with code {rc}")


# --------------------------------------------------
# MQTT client setup
# --------------------------------------------------
try:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
except AttributeError:
    client = mqtt.Client()

client.on_connect = on_connect

if is_enabled():
    print(f"Connecting MQTT to {BROKER}:{PORT}...")

    client.connect(BROKER, PORT, 60)

    # Keep MQTT network traffic running
    client.loop_start()

    # Give the connection callback/network loop time to complete
    for _ in range(20):
        if client.is_connected():
            break
        time.sleep(0.1)

    print(f"MQTT connection status: {client.is_connected()}")

else:
    print("MQTT is disabled in Network Settings.")


# --------------------------------------------------
# Publish
# --------------------------------------------------
def publish(topic, data):
    """Publish JSON or text to a topic."""

    if not is_enabled():
        print("MQTT disabled; skipping publish.")
        return

    if isinstance(data, (dict, list)):
        data = json.dumps(data)

    # Make sure we are connected before publishing
    for _ in range(20):
        if client.is_connected():
            break
        time.sleep(0.1)

    if not client.is_connected():
        print(f"MQTT not connected; skipping publish to {topic}")
        return

    info = client.publish(topic, data)

    print(f"MQTT publish result: {info.rc}")

    return info