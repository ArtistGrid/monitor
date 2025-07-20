import os
import time
import threading
import requests
import hashlib
from datetime import datetime, timezone, timedelta
from flask import Flask, Response

# -----------------------------
# Global State
# -----------------------------
log_entries = []
cooldown_until = None
cooldown_lock = threading.Lock()

# -----------------------------
# Configuration
# -----------------------------
URL_TO_MONITOR = "https://sheets.artistgrid.cx/artists.html"
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
CHECK_INTERVAL = 600  # seconds for HTML change check

env_urls = os.environ.get("ARCHIVE_URLS")
URLS_TO_ARCHIVE = [url.strip() for url in env_urls.split(",") if url.strip()] if env_urls else [
    "https://sheets.artistgrid.cx/artists.html",
    "https://sheets.artistgrid.cx/artists.xlsx",
    "https://docs.google.com/spreadsheets/d/1S6WwM05O277npQbaiNk-jZlXK3TdooSyWtqaWUvAI78/htmlview",
]

BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/115.0.0.0 Safari/537.36"
)

# -----------------------------
# Logging
# -----------------------------
def log(msg):
    now = datetime.now(timezone.utc)
    timestamp = now.strftime('%B %d, %Y at %H:%M GMT')
    entry = f"[{timestamp}] {msg}"
    print(entry)
    log_entries.append(entry)
    if len(log_entries) > 1000:
        del log_entries[0]

# -----------------------------
# Cooldown Management
# -----------------------------
def in_cooldown():
    global cooldown_until
    with cooldown_lock:
        return cooldown_until and datetime.now(timezone.utc) < cooldown_until

def enter_cooldown():
    global cooldown_until
    with cooldown_lock:
        cooldown_until = datetime.now(timezone.utc) + timedelta(hours=1)
        log(f"🛑 Entering cooldown until {cooldown_until.strftime('%H:%M:%S')} UTC")

# -----------------------------
# HTML Monitoring
# -----------------------------
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
    try:
        payload = {"content": message[:1900]}
        response = requests.post(DISCORD_WEBHOOK_URL, json=payload)
        response.raise_for_status()
        log("✅ Discord message sent.")
    except Exception as e:
        log(f"❌ Error sending message: {e}")

# -----------------------------
# Archiving
# -----------------------------
def is_recent_snapshot(url, max_age_seconds=3600):
    try:
        response = requests.get("https://archive.org/wayback/available", params={"url": url}, timeout=30)
        data = response.json()
        snapshot = data.get("archived_snapshots", {}).get("closest")
        if not snapshot:
            return False, None
        timestamp = snapshot["timestamp"]
        snapshot_time = datetime.strptime(timestamp, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - snapshot_time).total_seconds()
        return age <= max_age_seconds, snapshot["url"]
    except Exception as e:
        log(f"⚠️ Failed to check snapshot recency: {e}")
        return False, None

def archive_url(url):
    if in_cooldown():
        log(f"🚫 Skipping {url} — system is in cooldown.")
        return

    headers = {"User-Agent": BROWSER_USER_AGENT}
    try:
        log(f"📤 Submitting URL: {url}")
        response = requests.get("https://web.archive.org/save/" + url, headers=headers, timeout=60)
        log(f"📦 Status code: {response.status_code}")
        log(f"🌐 Archive/Status URL: {response.url}")

        if response.status_code in [429, 503]:
            log(f"🚷 Rate limited or service unavailable for {url} (status {response.status_code})")
            enter_cooldown()
            return

        time.sleep(5)
        recent, snapshot_url = is_recent_snapshot(url)
        if recent:
            log(f"✅ Archived successfully and snapshot is recent: {snapshot_url}")
        else:
            log("⚠️ Snapshot not recent (older than 1 hour). Rate-limited or error?")
            if snapshot_url:
                log(f"🕓 Last available snapshot: {snapshot_url}")
    except requests.exceptions.Timeout:
        log("⏰ Timeout occurred.")
        enter_cooldown()
    except requests.exceptions.RequestException as e:
        log(f"❌ Request error: {e}")
        enter_cooldown()

def archive_all_urls():
    log("🚀 Archiving all configured URLs due to detected content change.")
    for url in URLS_TO_ARCHIVE:
        archive_url(url)

# -----------------------------
# Monitor + Archive on Change Loop
# -----------------------------
def monitor_and_archive_loop():
    log(f"🔍 Monitoring HTML content at: {URL_TO_MONITOR}")
    last_html = fetch_html(URL_TO_MONITOR)
    if last_html is None:
        log("❌ Failed to get initial HTML content. Exiting monitor.")
        return

    last_hash = hash_content(last_html)

    while True:
        time.sleep(CHECK_INTERVAL)
        current_html = fetch_html(URL_TO_MONITOR)
        if current_html is None:
            log("⚠️ Failed to fetch. Skipping.")
            continue

        current_hash = hash_content(current_html)
        if current_hash != last_hash:
            log("⚠️ HTML content changed!")
            send_discord_message(f"⚠️ Content changed! <{URL_TO_MONITOR}>")
            archive_all_urls()
            last_hash = current_hash

# -----------------------------
# Flask Web App
# -----------------------------
app = Flask(__name__)

@app.route("/")
@app.route("/index.html")
def show_log():
    content = "<html><head><title>Monitor & Archiver Log</title></head>"
    content += "<body style='background-color:black; color:white; font-family:monospace; white-space:pre-wrap;'>"
    content += "\n".join(log_entries)
    content += "</body></html>"
    return Response(content, mimetype='text/html')

# -----------------------------
# Main Entry Point
# -----------------------------
if __name__ == "__main__":
    threading.Thread(target=monitor_and_archive_loop, daemon=True).start()
    app.run(host="0.0.0.0", port=8000)
