# Testing Unmonitarr Locally

This guide covers three ways to test unmonitarr before committing and building in CI/CD.

---

## Option 1: Quick Test with Python (Fastest) ⚡

This is the fastest way to test changes without Docker.

### Prerequisites
```bash
pip3 install -r requirements.txt
```

### Setup
1. Copy `.env.example` to `.env` and configure your Sonarr/Radarr settings:
```bash
cp .env.example .env
# Edit .env with your API keys and URLs
```

2. Make sure `DRY_RUN=1` is set in your `.env` to avoid making actual changes while testing.

### Run
```bash
# Export environment variables from .env
export $(cat .env | grep -v '^#' | xargs)

# Run the application
PYTHONPATH=src python3 src/main.py
```

### What to expect
You should see:
```
INFO:core.job_queue:Job worker started and waiting for jobs...
INFO:services.scheduler_service:Scheduler started (every 30 minutes)
 * Serving Flask app 'webhook_service'
 * Running on all addresses (0.0.0.0)
 * Running on http://127.0.0.1:5099
```

### Test Webhooks
Open another terminal and run:
```bash
./test_webhooks.sh
```

Or manually:
```bash
# Health check
curl http://localhost:5099/health

# Trigger Sonarr job
curl -X POST http://localhost:5099/trigger/sonarr

# Trigger Radarr job
curl -X POST http://localhost:5099/trigger/radarr
```

You should see log output showing jobs being queued and processed!

---

## Option 2: Build and Test with Docker Locally 🐳

This is the most realistic test - it runs exactly how it will in production.

### Build the image locally
```bash
docker build -t unmonitarr:test .
```

### Run with docker-compose (recommended)
1. Update `docker-compose.yml` to use your test image:
```yaml
services:
  unmonitarr:
    image: unmonitarr:test  # Changed from ghcr.io/unmonitarr/unmonitarr:latest
    # ... rest of config
```

2. Make sure your `.env` file has your actual API keys:
```bash
# Edit .env with real values
RADARR_API_KEY=your_actual_key
SONARR_API_KEY=your_actual_key
RADARR_URL=http://your_radarr_host:7878
SONARR_URL=http://your_sonarr_host:8989
```

3. Start the container:
```bash
docker-compose up -d
```

4. View logs:
```bash
docker-compose logs -f
```

### Test the webhooks
```bash
./test_webhooks.sh localhost:5099
```

Or manually:
```bash
curl http://localhost:5099/health
curl -X POST http://localhost:5099/trigger/sonarr
curl -X POST http://localhost:5099/trigger/radarr
```

### Check the logs to verify jobs ran:
```bash
docker-compose logs -f unmonitarr
```

You should see:
```
INFO:webhook_service:Sonarr trigger received via webhook.
INFO:core.job_queue:Starting sonarr job (triggered_by=webhook)
INFO:sonarr:Sonarr app starting…
...
INFO:core.job_queue:Completed sonarr job (triggered_by=webhook)
```

### Stop and clean up
```bash
docker-compose down
```

---

## Option 3: Run Docker Container Directly

If you don't want to use docker-compose:

```bash
# Build
docker build -t unmonitarr:test .

# Run with environment variables
docker run -d \
  --name unmonitarr-test \
  -p 5099:5099 \
  -e TZ=Australia/Melbourne \
  -e LOG_LEVEL=INFO \
  -e SLEEP_MINUTES=30 \
  -e DELAY_MINUTES=60 \
  -e DRY_RUN=1 \
  -e ENABLE_RADARR=1 \
  -e RADARR_URL=http://your_radarr:7878 \
  -e RADARR_API_KEY=your_key \
  -e ENABLE_SONARR=1 \
  -e SONARR_URL=http://your_sonarr:8989 \
  -e SONARR_API_KEY=your_key \
  unmonitarr:test

# View logs
docker logs -f unmonitarr-test

# Stop and remove
docker stop unmonitarr-test
docker rm unmonitarr-test
```

---

## Verification Checklist ✅

After starting unmonitarr, verify:

1. **Service starts successfully**
   - [ ] No errors in logs
   - [ ] Webhook server running on port 5099
   - [ ] Job worker started
   - [ ] Scheduler started

2. **Health endpoint works**
   ```bash
   curl http://localhost:5099/health
   # Should return: {"service":"unmonitarr","status":"healthy"}
   ```

3. **Webhook triggers work**
   - [ ] POST to `/trigger/sonarr` queues a sonarr job
   - [ ] POST to `/trigger/radarr` queues a radarr job
   - [ ] Jobs appear in logs as "triggered_by=webhook"
   - [ ] Jobs complete successfully

4. **Scheduled jobs work**
   - [ ] Wait for SLEEP_MINUTES (default 30 min) or change to 1 min for testing
   - [ ] Jobs appear in logs as "triggered_by=scheduler"

5. **Integration with Sonarr/Radarr** (if DRY_RUN=0)
   - [ ] Can fetch movies/series from APIs
   - [ ] Can fetch tags
   - [ ] Can update monitoring status (if DRY_RUN=0)

---

## Troubleshooting

### Port 5099 already in use
```bash
# Find what's using the port
lsof -i :5099

# Kill it or use a different port
# Update webhook_service.py: app.run(host="0.0.0.0", port=5099)
```

### Can't connect to Sonarr/Radarr
- If running in Docker, make sure URLs are reachable from container
- Use host.docker.internal on Mac/Windows: `http://host.docker.internal:8989`
- Or use IP address instead of localhost
- Verify API keys are correct

### Import errors
```bash
# Make sure PYTHONPATH is set
export PYTHONPATH=src
# Or use the full path
PYTHONPATH=/Users/charliecarpinteri/docker/unmonitarr/src python3 src/main.py
```

### Jobs not processing
- Check that job_worker thread started (should see log message)
- Verify no exceptions in logs
- Try posting to webhook and checking logs immediately

---

## Quick Integration Test

Want to verify everything works end-to-end quickly?

```bash
# 1. Start unmonitarr (Option 1 or 2)
# 2. In another terminal:
./test_webhooks.sh

# 3. Watch the logs - you should see:
# - "Sonarr trigger received via webhook"
# - "Starting sonarr job (triggered_by=webhook)"
# - "Sonarr app starting…"
# - "Completed sonarr job"
# Same for Radarr
```

---

## Testing with Sonarr/Radarr Webhooks

Once you've verified the local setup works:

1. **In Sonarr**: Settings → Connect → Add Webhook
   - Name: `Unmonitarr Trigger`
   - URL: `http://localhost:5099/trigger/sonarr` (or your Docker host IP)
   - Method: `POST`
   - Triggers: ✅ On Series Add, ✅ On Season Import

2. **In Radarr**: Settings → Connect → Add Webhook
   - Name: `Unmonitarr Trigger`
   - URL: `http://localhost:5099/trigger/radarr` (or your Docker host IP)
   - Method: `POST`
   - Triggers: ✅ On Movie Add, ✅ On Movie Import

3. **Test**: Add a new series/movie and watch unmonitarr logs!

---

## Performance Testing

Want to test how the queue handles multiple rapid requests?

```bash
# Fire 10 rapid requests
for i in {1..10}; do
  curl -X POST http://localhost:5099/trigger/sonarr &
done
wait

# Check logs - jobs should queue and process one at a time
# You should see locks preventing concurrent execution
```
