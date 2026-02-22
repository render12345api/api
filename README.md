# ⚡ SMS Burst API — Simple Edition

No database. No complex auth. Just fire and stop.

## Files needed
```
sms-burst-api/
├── app.py           ← Main API
├── apidata.json     ← SMS service definitions (copy from original)
├── requirements.txt
├── render.yaml
└── runtime.txt
```

## Deploy to Render
1. Push all files to GitHub (include your `apidata.json`)
2. Go to render.com → New → Blueprint → connect repo
3. Change `MASTER_API_KEY` in `render.yaml` to something secret
4. Deploy — done!

---

## API Usage

### ✅ Start a burst
```bash
curl -X POST https://YOUR-APP.onrender.com/api/job/start \
  -H "X-API-Key: render12345" \
  -H "Content-Type: application/json" \
  -d '{
    "targets": ["9977885544"],
    "mode": "Normal",
    "delay": 0.5,
    "max_requests": 10
  }'
```
**Response:**
```json
{
  "job_id": "a1b2c3d4e5f6g7h8",
  "status": "running",
  "targets": 1,
  "mode": "Normal",
  "delay": 0.5,
  "max_requests": 10
}
```

---

### 🔍 Check job status
```bash
curl https://YOUR-APP.onrender.com/api/job/a1b2c3d4e5f6g7h8 \
  -H "X-API-Key: render12345"
```
**Response:**
```json
{
  "job_id": "a1b2c3d4e5f6g7h8",
  "status": "running",
  "sent": 7,
  "max_requests": 10,
  "logs": ["✅ vedantu OK", "✅ kredbee OK"],
  "started_at": "2026-02-22T10:00:00"
}
```
`status` will be `running`, `done`, or `stopped`.

---

### 🛑 Stop a running job
```bash
curl -X POST https://YOUR-APP.onrender.com/api/job/a1b2c3d4e5f6g7h8/stop \
  -H "X-API-Key: render12345"
```
**Response:**
```json
{ "job_id": "a1b2c3d4e5f6g7h8", "status": "stopped" }
```

---

### 📋 List all jobs
```bash
curl https://YOUR-APP.onrender.com/api/jobs \
  -H "X-API-Key: render12345"
```

---

### ❤️ Health check
```bash
curl https://YOUR-APP.onrender.com/health
```

---

## Modes
| Mode | Behaviour |
|------|-----------|
| `Normal` | One pass through all services per target, then stops |
| `Ghost` | Same as Normal |
| `Nuclear` | Loops continuously until `max_requests` hit or stopped |

## Notes
- Jobs are stored in memory — they reset if the server restarts
- `max_requests` is capped at 1000 per job
- `delay` is clamped between 0.1s and 60s
