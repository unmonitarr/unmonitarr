<div align="center">
  <img src="assets/unmonitarr-logo.png" width="140" alt="unmonitarr logo" />
  <h1>unmonitarr</h1>
  <p><strong>Wait for real releases, skip the fakes.</strong></p>
  <p>Intelligent monitoring automation for Sonarr & Radarr</p>

  <p>
    <a href="https://github.com/unmonitarr/unmonitarr/releases"><img src="https://img.shields.io/github/v/release/unmonitarr/unmonitarr?style=flat-square" alt="Release" /></a>
    <a href="https://github.com/unmonitarr/unmonitarr/blob/main/LICENSE"><img src="https://img.shields.io/github/license/unmonitarr/unmonitarr?style=flat-square&v=2" alt="License" /></a>
    <a href="https://github.com/unmonitarr/unmonitarr/stargazers"><img src="https://img.shields.io/github/stars/unmonitarr/unmonitarr?style=flat-square" alt="Stars" /></a>
  </p>
</div>

---

## The Problem

When monitoring upcoming content, Sonarr and Radarr can search for and download releases before they're actually available, leading to fake pre-release files.

**Why existing features don't fully solve this:**

**Sonarr's Delay Profiles** only apply after a release is detected. They delay the decision to grab between Usenet and torrents, not the start of monitoring itself. Sonarr will still begin searching for unreleased episodes as soon as they're added to your library.

**Radarr's Minimum Availability** setting should prevent early searches, but it doesn't always behave consistently. Depending on the indexer or tracker, it can still grab early or incorrectly labeled releases.

If you use public indexers where fake releases are common, you're left manually managing monitoring status or accepting the occasional fake download.

## The Solution

unmonitarr manages monitoring status automatically based on air dates and release dates.

**How it works:**

1. Content is unmonitored before its air/release date, preventing any searches
2. After the air/release date plus a configurable delay (default 2 hours), content is automatically re-monitored
3. Webhook support allows instant processing when you add new content
4. Tag-based controls let you exclude specific items from automation

This approach waits until legitimate releases are expected before allowing Sonarr and Radarr to search, preventing most fake pre-release downloads.

---

## Key Features

- Time-delayed monitoring based on actual air/release dates
- Automatic re-monitoring after a configurable delay
- Webhook triggers for instant updates when adding content
- Separate handling for movies (release dates) and TV shows (episode air dates)
- Smart tag system to track managed items and exclude others
- Dry-run mode for testing changes before applying them
- Docker and Docker Compose ready
- Health check endpoint for monitoring

---

## Quick Start

### Prerequisites

- Docker and Docker Compose installed
- Running Sonarr and/or Radarr instance(s)
- API keys from Sonarr/Radarr (Settings → General → API Key)

### Installation

**1. Create a docker-compose.yml file:**

```yaml
services:
  unmonitarr:
    image: ghcr.io/unmonitarr/unmonitarr:latest
    container_name: unmonitarr
    ports:
      - "5099:5099"  # Webhook server port
    healthcheck:
      test: ["CMD-SHELL", "curl -f http://localhost:5099/health || exit 1"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 10s
    environment:
      # General Settings
      - TZ=Australia/Melbourne           # Your timezone
      - LOG_LEVEL=INFO                   # DEBUG, INFO, WARNING, ERROR
      - SLEEP_MINUTES=30                 # Interval between scheduled checks
      - DELAY_MINUTES=120                # Minutes after air/release to re-monitor
      - DRY_RUN=1                        # Set to 0 to apply changes, 1 to preview only

      # Tagging
      - AUTO_TAG_NAME=auto-unmonitored   # Tag for items managed by unmonitarr
      - IGNORE_TAG_NAME=ignore           # Tag to exclude items from management
      - SKIP_IF_FILE=1                   # Skip items with existing files (1=yes, 0=no)

      # Radarr Configuration
      - ENABLE_RADARR=1                  # Enable Radarr integration (1=yes, 0=no)
      - RADARR_URL=http://radarr:7878    # Radarr URL (use container name or IP)
      - RADARR_API_KEY=your_api_key_here # Your Radarr API key
      - PREFERRED_RELEASE=either         # either, digital, or physical
      - IGNORE_INCINEMAS=0               # Ignore cinema release dates (1=yes, 0=no)

      # Sonarr Configuration
      - ENABLE_SONARR=1                  # Enable Sonarr integration (1=yes, 0=no)
      - SONARR_URL=http://sonarr:8989    # Sonarr URL (use container name or IP)
      - SONARR_API_KEY=your_api_key_here # Your Sonarr API key

    restart: unless-stopped
```

**2. Start unmonitarr:**

```bash
docker-compose up -d
```

**3. Check the logs:**

```bash
docker-compose logs -f unmonitarr
```

You should see:
- Job worker started
- Scheduler started
- Webhook server running on port 5099

**4. Test in dry-run mode first!**

With `DRY_RUN=1`, unmonitarr will log what it *would* do without making actual changes. Review the logs to ensure it's working as expected.

**5. Enable live mode:**

When satisfied, set `DRY_RUN=0` and restart:

```bash
docker-compose down
docker-compose up -d
```

---

## Webhook Configuration

For instant processing when you add new content, configure webhooks in Sonarr and Radarr.

### Sonarr Webhook Setup

1. Open Sonarr → **Settings → Connect**
2. Click **Add** → **Webhook**
3. Configure:
   - **Name**: `Unmonitarr`
   - **URL**: `http://unmonitarr:5099/trigger/sonarr`
     - If on the same host: `http://localhost:5099/trigger/sonarr`
     - If using Docker Desktop: `http://host.docker.internal:5099/trigger/sonarr`
   - **Method**: `POST`
   - **Notification Triggers**: ✅ **On Series Add**
4. Click **Test** to verify, then **Save**

### Radarr Webhook Setup

1. Open Radarr → **Settings → Connect**
2. Click **Add** → **Webhook**
3. Configure:
   - **Name**: `Unmonitarr`
   - **URL**: `http://unmonitarr:5099/trigger/radarr`
     - If on the same host: `http://localhost:5099/trigger/radarr`
     - If using Docker Desktop: `http://host.docker.internal:5099/trigger/radarr`
   - **Method**: `POST`
   - **Notification Triggers**: ✅ **On Movie Add**
4. Click **Test** to verify, then **Save**

### Why Use Webhooks?

Without webhooks, unmonitarr only runs every `SLEEP_MINUTES` (default: 30 minutes). This means newly added content could start downloading before unmonitarr processes it.

With webhooks, unmonitarr processes new content **immediately** when you add it, eliminating the race condition.

---

## How It Works

### Radarr (Movies)

1. When a movie is added (or during scheduled checks), unmonitarr fetches all movies
2. For each movie, it checks the release date based on `PREFERRED_RELEASE`:
   - `either`: Uses whichever comes first (digital or physical)
   - `digital`: Prefers digital release
   - `physical`: Prefers physical release
3. **Before release + delay**: Movie is **unmonitored** and tagged with `AUTO_TAG_NAME`
4. **After release + delay**: Movie is **re-monitored** and tag is removed
5. Movies tagged with `IGNORE_TAG_NAME` are never touched

**Example Timeline:**
- Movie digital release: March 15, 2024
- `DELAY_MINUTES=120` (2 hours)
- **Before March 15, 2:00 PM**: Movie is unmonitored (no searches)
- **After March 15, 2:00 PM**: Movie is re-monitored (searches begin)

### Sonarr (TV Shows)

1. unmonitarr only manages episodes in the **latest monitored season** of each series
2. For each episode, it checks the air date:
   - Episodes without air dates are skipped
   - Episodes with existing files are skipped (if `SKIP_IF_FILE=1`)
3. **Before air date**: Episode is **unmonitored**
4. **After air date + delay**: Episode is **re-monitored**
5. Series tagged with `IGNORE_TAG_NAME` are never touched

**Example Timeline:**
- Episode airs: Wednesday, 8:00 PM EST
- `DELAY_MINUTES=120` (2 hours)
- **Before Wednesday, 10:00 PM EST**: Episode is unmonitored
- **After Wednesday, 10:00 PM EST**: Episode is re-monitored

### Scheduled Checks

Every `SLEEP_MINUTES`, unmonitarr:
1. Fetches all movies/series from enabled apps
2. Evaluates each item's monitoring status
3. Updates items that need changes
4. Logs a summary of actions taken

Combined with webhooks, this ensures items are always properly managed.

---

## Configuration Reference

### General Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `TZ` | `UTC` | Timezone for date calculations (e.g., `Australia/Melbourne`) |
| `LOG_LEVEL` | `INFO` | Logging verbosity: `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `SLEEP_MINUTES` | `30` | Minutes between scheduled checks |
| `DELAY_MINUTES` | `120` | Minutes after air/release date before re-monitoring |
| `DRY_RUN` | `1` | Preview mode: `1` = log only, `0` = apply changes |
| `SKIP_IF_FILE` | `1` | Skip items with existing files: `1` = yes, `0` = no |
| `AUTO_TAG_NAME` | `auto-unmonitored` | Tag applied to items managed by unmonitarr |
| `IGNORE_TAG_NAME` | `ignore` | Tag to exclude items from management |

### Radarr Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `ENABLE_RADARR` | `1` | Enable Radarr integration: `1` = yes, `0` = no |
| `RADARR_URL` | *required* | Full URL to Radarr instance (e.g., `http://radarr:7878`) |
| `RADARR_API_KEY` | *required* | Radarr API key (Settings → General → Security) |
| `PREFERRED_RELEASE` | `either` | Release type: `either`, `digital`, or `physical` |
| `IGNORE_INCINEMAS` | `0` | Ignore cinema release dates: `1` = yes, `0` = no |

### Sonarr Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `ENABLE_SONARR` | `1` | Enable Sonarr integration: `1` = yes, `0` = no |
| `SONARR_URL` | *required* | Full URL to Sonarr instance (e.g., `http://sonarr:8989`) |
| `SONARR_API_KEY` | *required* | Sonarr API key (Settings → General → Security) |

---

## Common Use Cases

### Use Case 1: Prevent All Pre-Release Downloads

**Goal**: Only download content after it has officially released and had time to seed.

**Configuration**:
```yaml
- DELAY_MINUTES=120        # Wait 2 hours after release
- SKIP_IF_FILE=1           # Don't re-process existing downloads
- DRY_RUN=0                # Apply changes
```

**Result**: All new content is unmonitored until 2 hours after air/release date.

---

### Use Case 2: Aggressive - Wait Longer for Quality Releases

**Goal**: Wait 24 hours after release to ensure high-quality releases are available.

**Configuration**:
```yaml
- DELAY_MINUTES=1440       # Wait 24 hours (1440 minutes)
- PREFERRED_RELEASE=digital # Prefer digital releases
```

**Result**: Content isn't re-monitored until a full day after release, giving time for proper scene releases.

---

### Use Case 3: Conservative - Short Delay

**Goal**: Minimize delay but still avoid pre-release fakes.

**Configuration**:
```yaml
- DELAY_MINUTES=30         # Just 30 minutes after release
```

**Result**: Content is re-monitored quickly, but still avoids pre-release fakes.

---

### Use Case 4: Exclude Specific Series/Movies

**Goal**: Some content should always be monitored immediately.

**Steps**:
1. In Sonarr/Radarr, add the tag `ignore` to specific items
2. unmonitarr will never touch items with this tag

**Configuration**:
```yaml
- IGNORE_TAG_NAME=ignore
```

---

## Testing & Validation

### Testing in Dry-Run Mode

Before applying changes, test with dry-run mode:

1. Set `DRY_RUN=1` in your configuration
2. Start unmonitarr and watch the logs:
   ```bash
   docker-compose logs -f unmonitarr
   ```
3. Look for log entries like:
   ```
   [DRY RUN] Would unmonitor: Movie Name (2024)
   [DRY RUN] Would re-monitor: Another Movie (2023)
   ```
4. Verify the logic is correct
5. Set `DRY_RUN=0` to enable live changes

### Testing Webhooks

Manually trigger webhooks to verify they work:

```bash
# Test Sonarr webhook
curl -X POST http://localhost:5099/trigger/sonarr

# Test Radarr webhook
curl -X POST http://localhost:5099/trigger/radarr

# Check health
curl http://localhost:5099/health
```

Expected responses:
- Triggers: `{"status": "queued", "job": "sonarr"}`
- Health: `{"status": "healthy", "service": "unmonitarr"}`

---

## Troubleshooting

### Items aren't being managed

**Check:**
- ✅ Items aren't tagged with `IGNORE_TAG_NAME` (default: `ignore`)
- ✅ Items have air/release dates set in Sonarr/Radarr
- ✅ API keys are correct
- ✅ `DRY_RUN=0` (not in preview mode)
- ✅ Check logs for errors: `docker-compose logs unmonitarr`

### Webhooks not triggering

**Check:**
- ✅ Port 5099 is accessible from Sonarr/Radarr
- ✅ Correct URL (use container name if same Docker network)
- ✅ Test manually: `curl -X POST http://localhost:5099/trigger/sonarr`
- ✅ Check unmonitarr logs when webhook fires

### Connection errors to Sonarr/Radarr

**Check:**
- ✅ URLs are correct (include `http://` or `https://`)
- ✅ If using Docker, use container names or Docker network IPs
- ✅ API keys are valid (copy from Settings → General in each app)
- ✅ Firewalls aren't blocking connections

### Items re-monitored too early/late

**Check:**
- ✅ `TZ` environment variable matches your timezone
- ✅ `DELAY_MINUTES` is set correctly
- ✅ Air/release dates are correct in Sonarr/Radarr
- ✅ Check logs for timing decisions

### Health check failing

```bash
# Test health endpoint
curl http://localhost:5099/health

# Should return:
{"status": "healthy", "service": "unmonitarr"}
```

If failing:
- ✅ Check container is running: `docker ps`
- ✅ Check logs for startup errors: `docker logs unmonitarr`
- ✅ Verify port 5099 is exposed

---

## Advanced Configuration

### Custom Docker Compose Network

If Sonarr/Radarr are on a custom Docker network:

```yaml
services:
  unmonitarr:
    image: ghcr.io/unmonitarr/unmonitarr:latest
    container_name: unmonitarr
    ports:
      - "5099:5099"
    healthcheck:
      test: ["CMD-SHELL", "curl -f http://localhost:5099/health || exit 1"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 10s
    networks:
      - media
    environment:
      - TZ=Australia/Melbourne
      - RADARR_URL=http://radarr:7878  # Use container name
      - SONARR_URL=http://sonarr:8989
      # ... other config ...
    restart: unless-stopped

networks:
  media:
    external: true  # Or define it here
```

### Using Environment File

Store configuration in a `.env` file:

**docker-compose.yml:**
```yaml
services:
  unmonitarr:
    image: ghcr.io/unmonitarr/unmonitarr:latest
    container_name: unmonitarr
    ports:
      - "5099:5099"
    healthcheck:
      test: ["CMD-SHELL", "curl -f http://localhost:5099/health || exit 1"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 10s
    env_file:
      - .env
    restart: unless-stopped
```

**.env:**
```env
TZ=Australia/Melbourne
LOG_LEVEL=INFO
DELAY_MINUTES=120
DRY_RUN=0
RADARR_URL=http://radarr:7878
RADARR_API_KEY=your_key_here
# ... etc
```

### Running Multiple Instances

To manage multiple Sonarr/Radarr instances, run multiple unmonitarr containers with different configs and ports.

---

## FAQ

### Does this delete or modify my content files?

**No.** unmonitarr only changes monitoring status in Sonarr/Radarr. It never touches your actual media files.

### What happens if I stop unmonitarr?

Nothing breaks. Items will remain in whatever monitoring state they were last set to. When you restart unmonitarr, it will resume managing them.

### Can I use this with both Sonarr v3 and v4?

Yes. unmonitarr uses standard API endpoints that work with both versions.

### Does this work with Lidarr or other *arr apps?

Currently only Sonarr and Radarr are supported. Other apps may be added in the future.

### Will this slow down my downloads?

Only by the configured `DELAY_MINUTES`. This is intentional - you're trading a small delay for eliminating fake downloads entirely.

### Can I exclude specific movies or shows?

Yes. Tag them with your `IGNORE_TAG_NAME` (default: `ignore`) in Sonarr/Radarr.

---

## Contributing

Contributions are welcome! Here's how you can help:

- 🐛 **Report bugs** - Open an issue with details and logs
- 💡 **Suggest features** - Share your ideas in discussions
- 🔧 **Submit pull requests** - Fix bugs or add features
- 📖 **Improve documentation** - Help others understand the project
- ⭐ **Star the repo** - Show your support!

### Development Setup

```bash
# Clone the repo
git clone https://github.com/unmonitarr/unmonitarr.git
cd unmonitarr

# Install dependencies
pip install -r requirements.txt

# Copy example config
cp .env.example .env
# Edit .env with your settings

# Run locally
PYTHONPATH=src python3 src/main.py

# Run tests
PYTHONPATH=src python3 -m unittest discover tests
```

---

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.

---

## Acknowledgments

- The [Sonarr](https://sonarr.tv) and [Radarr](https://radarr.video) teams for building excellent media management tools
- The self-hosted community for inspiration and feedback
- Everyone who has dealt with fake pre-release downloads and wanted a better solution

---

<div align="center">
  <p><strong>If unmonitarr helps you, consider giving it a ⭐!</strong></p>
  <p>Made with ❤️ for the self-hosted community</p>
</div>
