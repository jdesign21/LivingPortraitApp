import json
import time
import threading
import socket
from pathlib import Path
import paho.mqtt.client as mqtt
from shared.vlc_network_helper import get_role, get_primary_ip, is_enabled
from shared.vlc_helper import log, load_settings, save_settings

PORT = 1883
TOPIC_SCHEDULE = "video/schedule"
TOPIC_CONTROL = "video/control"
TOPIC_SYNC_STATUS = "video/sync_status"
TOPIC_SYNC_TAGS_ACK = "video/sync_tags_ack"
HOME = Path.home()
MQTT_STATUS_FILE = HOME / "mqtt_status.json"
sync_tag_acknowledgments = {}
sync_tag_ack_lock = threading.Lock()

def save_mqtt_status(connected):
    status = {"connected": connected}
    try:
        with open(MQTT_STATUS_FILE, "w") as f:
            json.dump(status, f)
    except Exception as e:
        log(f"Failed to save MQTT status: {e}", "ERROR")

role = get_role()
if role == "primary":
    BROKER = "localhost"
elif role == "secondary":
    BROKER = get_primary_ip()
else:
    log(f"Invalid role: {role}", "ERROR")
    raise ValueError(f"Invalid role: {role}")

def on_message(client, userdata, msg):
    if msg.topic == TOPIC_SYNC_TAGS_ACK:
        handle_sync_tags_ack(msg)
        return
    if msg.topic != TOPIC_CONTROL:
        return
    if role != "secondary":
        return
    try:
        data = json.loads(msg.payload.decode())
    except Exception as e:
        log(f"Failed to decode MQTT control message: {e}", "ERROR")
        return
    if data.get("command") != "sync_tags":
        return
    sync_tags = data.get("sync_tags", [])
    if not isinstance(sync_tags, list):
        log("Invalid Sync Tag list received.", "SYNC TAGS")
        publish_sync_tags_ack(
            success=False,
            message="Invalid Sync Tag list received."
        )
        return
    try:
        settings = load_settings()
        settings["sync_tags"] = sync_tags
        valid_tags = {
            str(tag).strip().lower()
            for tag in sync_tags
            if str(tag).strip()
        }
        order = settings.get(
            "playlist",
            {}
        ).get(
            "order",
            []
        )
        assignments_removed = 0
        for video in order:
            video_sync_tag = video.get(
                "sync_tag",
                ""
            ).strip()
            if (
                video_sync_tag
                and video_sync_tag.lower() not in valid_tags
            ):
                video["sync_tag"] = ""
                assignments_removed += 1
        settings["playlist"]["order"] = order
        save_settings(settings)
        log(
            f"Received and saved {len(sync_tags)} Sync Tag(s).",
            "SYNC TAGS"
        )
        if assignments_removed:
            log(
                f"Cleared {assignments_removed} invalid video assignment(s).",
                "SYNC TAGS"
            )
        publish_sync_tags_ack(
            success=True,
            message=f"Processed {len(sync_tags)} Sync Tag(s)."
        )
    except Exception as e:
        log(f"Failed to process Sync Tags: {e}", "ERROR")
        publish_sync_tags_ack(
            success=False,
            message=str(e)
        )

def publish_sync_tags_ack(success, message=""):
    secondary_name = socket.gethostname()
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect((BROKER, PORT))
            secondary_ip = s.getsockname()[0]
    except Exception as e:
        secondary_ip = "Unknown"
        log(
            f"Unable to determine Secondary IP for Sync Tag acknowledgment: {e}",
            "ERROR"
        )
    log(
        f"Sending Sync Tag acknowledgment from "
        f"{secondary_name} ({secondary_ip})",
        "SYNC TAGS"
    )
    data = {
        "secondary_name": secondary_name,
        "secondary_ip": secondary_ip,
        "success": success,
        "message": message
    }
    publish(TOPIC_SYNC_TAGS_ACK, data)

def handle_sync_tags_ack(msg):
    if role != "primary":
        return
    try:
        data = json.loads(msg.payload.decode())
        secondary_name = data.get("secondary_name", "Unknown")
        secondary_ip = data.get("secondary_ip", "Unknown")
        success = data.get("success", False)
        message = data.get("message", "")
        with sync_tag_ack_lock:
            sync_tag_acknowledgments[secondary_ip] = {
                "secondary_name": secondary_name,
                "secondary_ip": secondary_ip,
                "success": success,
                "message": message
            }
        if success:
            log(
                f"{secondary_name} ({secondary_ip}) successfully processed Sync Tags.",
                "SYNC TAGS"
            )
        else:
            log(
                f"{secondary_name} ({secondary_ip}) failed to process "
                f"Sync Tags: {message}",
                "SYNC TAGS"
            )
    except Exception as e:
        log(
            f"Failed to process Sync Tag acknowledgment: {e}",
            "ERROR"
        )

def clear_sync_tag_acknowledgments():
    with sync_tag_ack_lock:
        sync_tag_acknowledgments.clear()

def get_sync_tag_acknowledgments():
    with sync_tag_ack_lock:
        return dict(sync_tag_acknowledgments)

def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        log(f"MQTT connected successfully to {BROKER}.", "MQTT")
        save_mqtt_status(True)
        if role == "secondary":
            client.subscribe(TOPIC_CONTROL)
            log(f"Subscribed to {TOPIC_CONTROL}.", "MQTT")
        elif role == "primary":
            client.subscribe(TOPIC_SYNC_STATUS)
            client.subscribe(TOPIC_SYNC_TAGS_ACK)
            log(f"Subscribed to {TOPIC_SYNC_STATUS}.", "MQTT")
            log(f"Subscribed to {TOPIC_SYNC_TAGS_ACK}.", "MQTT")
    else:
        log(f"MQTT connection failed with code {rc}.", "ERROR")
        save_mqtt_status(False)

def on_disconnect(client, userdata, flags, rc, properties=None):
    save_mqtt_status(False)
    log(f"MQTT disconnected from {BROKER}.", "MQTT")

try:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
except AttributeError:
    client = mqtt.Client()

client.on_connect = on_connect
client.on_disconnect = on_disconnect
client.on_message = on_message

def secondary_mqtt_worker():
    log("Starting Secondary MQTT worker.", "MQTT")
    client.loop_start()
    while True:
        if not is_enabled():
            save_mqtt_status(False)
            log("MQTT disabled. Checking again in 30 seconds.", "MQTT")
            time.sleep(30)
            continue
        if client.is_connected():
            time.sleep(30)
            continue
        try:
            log(f"Connecting MQTT to {BROKER}:{PORT}...", "MQTT")
            client.connect(BROKER, PORT, 60)
            for _ in range(20):
                if client.is_connected():
                    break
                time.sleep(0.1)
            if client.is_connected():
                log("MQTT connection established.", "MQTT")
            else:
                save_mqtt_status(False)
                log("MQTT connection not established.", "ERROR")
        except Exception as e:
            save_mqtt_status(False)
            log(f"MQTT connection failed: {e}", "ERROR")
        if not client.is_connected():
            save_mqtt_status(False)
            log("MQTT unavailable. Retrying in 30 seconds.", "MQTT")
            time.sleep(30)

if is_enabled():
    if role == "primary":
        log(f"Connecting MQTT to {BROKER}:{PORT}...", "MQTT")
        client.connect(BROKER, PORT, 60)
        client.loop_start()
        for _ in range(20):
            if client.is_connected():
                break
            time.sleep(0.1)
        log(
            f"MQTT connection status: {client.is_connected()}",
            "MQTT"
        )
        if not client.is_connected():
            save_mqtt_status(False)
    elif role == "secondary":
        mqtt_thread = threading.Thread(
            target=secondary_mqtt_worker,
            daemon=True
        )
        mqtt_thread.start()
else:
    save_mqtt_status(False)
    log("MQTT is disabled in Network Settings.", "MQTT")

def publish(topic, data):
    """Publish JSON or text to a topic."""
    if not is_enabled():
        log("MQTT disabled; skipping publish.", "MQTT")
        return
    if isinstance(data, (dict, list)):
        data = json.dumps(data)
    for _ in range(20):
        if client.is_connected():
            break
        time.sleep(0.1)
    if not client.is_connected():
        log(
            f"MQTT not connected; skipping publish to {topic}.",
            "ERROR"
        )
        return
    info = client.publish(topic, data)
    log(
        f"MQTT publish result: {info.rc}",
        "MQTT"
    )
    return info