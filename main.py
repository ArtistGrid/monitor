import os
import time
import threading
import requests
import hashlib
from datetime import datetime, timezone
from flask import Flask, Response

# -----------------------------
# Global log storage
# -----------------------------
log_entries = []

def log(msg):
    now = datetime.now(timezone.utc)
    timestamp = now.strftime('%B %d, %Y at %H:%M GMT')
    entry = f"[{timestamp}] {msg}"
    print(entry)
    log_entries.append(entry)
    # Limit log size to last 1000 entries
    if len(log_entries) > 1000:
        del log_entries[0]

# -----------------------------
# Monitoring Settings
# -----------------------------
URL = "https://sheets.artistgrid.cx/artists.html"
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
CHECK_INTERVAL = 600  # seconds

def fetch_html(url):
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return response.text
    except Exception as e:
        log(f"❌ Error fetching HTML: {e}")
        return None

def hash_content(content):
    return hashlib.sha256(content.encode("utf-8")).hexdigest()

def send_discord_message(message):
    if not DISCORD_WEBHOOK_URL:
        log("⚠️ DISCORD_WEBHOOK_URL not set.")
        return
    payload = {"content": message[:1900]}  # Discord message limit
    try:
        response = requests.post(DISCORD_WEBHOOK_URL, json=payload)
        response.raise_for_status()
        log("✅ Discord message sent.")
    except Exception as e:
        log(f"❌ Error sending message: {e}")

def monitor_loop():
    log(f"🔍 Monitoring HTML content at: {URL}")
    last_html = fetch_html(URL)
    if last_html is None:
        log("❌ Failed to get initial HTML content. Exiting monitor.")
        return

    last_hash = hash_content(last_html)

    while True:
        time.sleep(CHECK_INTERVAL)
        current_html = fetch_html(URL)
        if current_html is None:
            log("⚠️ Failed to fetch. Skipping.")
            continue

        current_hash = hash_content(current_html)
        if current_hash != last_hash:
            log("⚠️ HTML content changed!")
            send_discord_message(f"⚠️ Content changed! <{URL}>")
            last_hash = current_hash

# -----------------------------
# Flask Web App
# -----------------------------
app = Flask(__name__)

@app.route("/")
@app.route("/index.html")
def show_log():
    content = "<html><head><title>Monitor Log</title></head>"
    content += "<body style='background-color:black; color:white; font-family:monospace; white-space:pre-wrap;'>"
    content += "\n".join(log_entries)
    content += "</body></html>"
    return Response(content, mimetype='text/html')

# -----------------------------
# Main entry point
# -----------------------------
if __name__ == "__main__":
    # Start monitor loop in background thread
    threading.Thread(target=monitor_loop, daemon=True).start()
    
    # Start Flask server
    app.run(host="0.0.0.0", port=8000)
