from common.logger import get_logger
from flask import Flask, request, jsonify
from core.job_queue import add_job

app = Flask(__name__)
log = get_logger("webhook_service")

@app.route("/trigger/sonarr", methods=["POST"])
def trigger_sonarr():
    log.info("Sonarr trigger received via webhook.")
    add_job("sonarr", triggered_by="webhook")
    return jsonify({"status": "queued", "job": "sonarr"}), 202

@app.route("/trigger/radarr", methods=["POST"])
def trigger_radarr():
    log.info("Radarr trigger received via webhook.")
    add_job("radarr", triggered_by="webhook")
    return jsonify({"status": "queued", "job": "radarr"}), 202

@app.route("/health", methods=["GET"])
def health_check():
    return jsonify({"status": "healthy", "service": "unmonitarr"}), 200

def start_webhook_server():
    app.run(host="0.0.0.0", port=5099)