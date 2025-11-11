# Migration Guide: v0.10.0 → v0.11.0

This guide explains the breaking changes in v0.11.0 and how to migrate your setup.

---

## What Changed

### Sonarr Re-monitoring Logic (Breaking Change)

**v0.10.0 and earlier:**
- Re-monitored ANY unmonitored episode after air date + delay
- Did not check if unmonitarr was the one who unmonitored it
- Could re-monitor episodes you manually unmonitored or deleted

**v0.11.0:**
- Only re-monitors episodes if the parent series has the `auto-unmonitored` tag
- Only re-monitors episodes that aired within `SONARR_REMONITOR_WINDOW_DAYS` (default: 14 days)
- Removes the `auto-unmonitored` tag after re-monitoring
- **This matches Radarr's existing behavior**

### New Configuration Variables

```bash
# Time windows for re-monitoring (set to 0 to disable)
RADARR_REMONITOR_WINDOW_DAYS=30  # Default: 30 days
SONARR_REMONITOR_WINDOW_DAYS=14  # Default: 14 days
```

---

## Impact on Existing Users

### Issue: Series Without Auto-Tag Won't Be Re-monitored

If you've been using unmonitarr before v0.11.0, many of your series may not have the `auto-unmonitored` tag due to a bug that was fixed in v0.10.0.

**Symptoms:**
- Episodes that should be re-monitored stay unmonitored
- No changes appear in logs

**Solution:** Choose one of the options below.

---

## Migration Options

### Option 1: Manual Tag Addition (Recommended)

Manually add the `auto-unmonitored` tag to series that unmonitarr should manage.

**Steps:**
1. In Sonarr, go to **Library**
2. Use **Mass Editor** (top right)
3. Select series you want unmonitarr to manage
4. Click **Edit** → **Tags** → Add `auto-unmonitored`
5. Save

**When to use:** You want precise control over which series unmonitarr manages.

---

### Option 2: Wait for Natural Tag Application

Let unmonitarr add the tag automatically the next time it unmonitors an episode.

**How it works:**
- When unmonitarr unmonitors a future episode, it adds the tag
- From that point forward, it can re-monitor episodes for that series

**When to use:** You're not in a hurry and prefer zero manual work.

**Drawback:** Episodes that air before the tag is applied won't be re-monitored.

---

### Option 3: Disable Time Window Check

Set the time window to 0 to rely on auto-tag only (no time restriction).

```bash
SONARR_REMONITOR_WINDOW_DAYS=0
RADARR_REMONITOR_WINDOW_DAYS=0
```

**When to use:** You want unlimited re-monitoring for any content with the auto-tag.

**Drawback:** Could re-monitor very old content if it has the tag.

---

### Option 4: Increase Time Window

Increase the time window to catch more episodes.

```bash
SONARR_REMONITOR_WINDOW_DAYS=90  # 3 months
RADARR_REMONITOR_WINDOW_DAYS=90
```

**When to use:** You have many recent series that need re-monitoring.

**Drawback:** Might re-monitor recently watched/deleted episodes.

---

## Verification

After upgrading, check the logs to verify behavior:

```bash
docker compose logs -f unmonitarr
```

**Expected behavior:**
- Episodes re-monitored: Series has tag + aired within window
- Episodes NOT re-monitored: Series missing tag OR outside window
- Tag removed: After successful re-monitoring

**Dry-run mode recommended:**
Set `DRY_RUN=1` first to preview changes before applying.

---

## Why This Change?

This change solves [Issue #4](https://github.com/unmonitarr/unmonitarr/issues/4) where unmonitarr would re-monitor episodes that users had manually unmonitored or deleted (via notifiarr/maintainerr).

**Benefits:**
- No more re-monitoring of watched/deleted episodes
- Consistent behavior between Sonarr and Radarr
- User control via auto-tag and time window settings

---

## Rollback

If you need to rollback to v0.10.0:

```bash
# In docker-compose.yml, change image tag
image: ghcr.io/unmonitarr/unmonitarr:v0.10.0

# Recreate container
docker compose down
docker compose up -d
```

---

## Need Help?

- Check logs: `docker compose logs unmonitarr`
- Test in dry-run: `DRY_RUN=1`
- Report issues: https://github.com/unmonitarr/unmonitarr/issues
