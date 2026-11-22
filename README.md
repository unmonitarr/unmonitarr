<div align="center">
  <img src="assets/unmonitarr-logo.png" width="140" alt="unmonitarr logo" />
  <h1>unmonitarr</h1>
  <p><strong>Wait for real releases, skip the fakes.</strong></p>
  <p>Air-date and release-date monitoring for Sonarr and Radarr</p>

  <p>
    <a href="https://github.com/unmonitarr/unmonitarr/releases"><img src="https://img.shields.io/github/v/release/unmonitarr/unmonitarr?style=flat-square" alt="Release" /></a>
    <a href="https://github.com/unmonitarr/unmonitarr/blob/main/LICENSE"><img src="https://img.shields.io/github/license/unmonitarr/unmonitarr?style=flat-square&v=2" alt="License" /></a>
    <a href="https://github.com/unmonitarr/unmonitarr/stargazers"><img src="https://img.shields.io/github/stars/unmonitarr/unmonitarr?style=flat-square" alt="Stars" /></a>
  </p>
</div>

---

## The Problem

Sonarr and Radarr start looking for an episode or movie as soon as it's monitored, even if it hasn't aired or been released yet. On public indexers, that window is when fake releases turn up: files with the right name and none of the right content. You end up with junk downloads to clean up by hand.

## What unmonitarr Does

unmonitarr keeps upcoming content unmonitored until its air or release date plus a delay you choose, then monitors it again so Sonarr and Radarr pick it up as normal.

- Episodes and movies are unmonitored until air/release date + `DELAY_MINUTES`
- After that, they're monitored again automatically
- A tag marks what unmonitarr is managing, so it only re-monitors what it unmonitored. For Sonarr the tag is on the series, so while a series is tagged, an aired episode you unmonitored yourself can be re-monitored too
- Webhooks let it act the moment you add something, before Sonarr or Radarr can search

### Do you need it?

Sonarr and Radarr have been adding their own versions of this. Here's an honest comparison so you can decide.

**Radarr** has long had a built-in equivalent: set a movie's **Minimum Availability** to *Released* and set **Availability Delay** under Settings → Indexers. Radarr then won't grab a movie automatically until the earlier of its digital and physical release dates, plus the delay. With neither date, it waits until 90 days after the cinema release, and unmonitarr does the same. It doesn't apply to searches you start yourself. If that covers you, you don't need unmonitarr for movies. unmonitarr adds:

- Delays in minutes rather than whole days
- Per-movie delays via tags, on top of your default
- A choice of digital or physical release date

**Sonarr v5** (in beta at the time of writing) adds **Reject Unaired Releases** and an **Air Date Grace Period** (hours, can be negative) to Release Profiles. It checks each release's publish date against the episode's air date, which also blocks a fake uploaded before air even after the episode has aired. unmonitarr can't do that. It's scoped by tags, and where several profiles apply to a series, the longest grace period wins. unmonitarr adds:

- Sonarr v4 support
- Per-series delays that can be shorter or longer than your default
- [Season pack mode](#season-pack-mode) for shows released all at once
- [TBA metadata refresh](#tba-metadata-refresh)

You can use both side by side.

---

## Key Features

- Unmonitors episodes and movies until their air/release date plus a delay, then re-monitors them
- Per-item delay overrides via tags (e.g. `delayby-60`)
- Webhook triggers for instant processing when you add content
- Season pack mode for shows Sonarr lists weekly but that are released all at once
- Optional TBA metadata refresh so episodes don't import with `TBA` in the filename
- Ignore tag to exclude items
- Dry-run mode, on by default
- Clear errors in the logs when something fails, naming the item and the reason
- Docker image for `linux/amd64` and `linux/arm64`, with a health check endpoint

---

## Quick Start

### Prerequisites

- Docker with Docker Compose
- Sonarr and/or Radarr
- API keys from Sonarr/Radarr (Settings → General → Security → API Key)

### Installation

**1. Create a `docker-compose.yml`:**

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
      # General
      - TZ=Australia/Melbourne           # Timezone for log timestamps
      - LOG_LEVEL=INFO                   # DEBUG, INFO, WARNING, ERROR
      - SLEEP_MINUTES=30                 # Minutes between scheduled runs
      - DELAY_MINUTES=120                # Minutes after air/release before re-monitoring
      - DRY_RUN=1                        # 1 = log only, 0 = apply changes

      # Tags
      - AUTO_TAG_NAME=auto-unmonitored   # Marks items unmonitarr is managing
      - IGNORE_TAG_NAME=ignore           # Items with this tag are left alone
      - SKIP_IF_FILE=1                   # Leave items that already have a file

      # Radarr
      - ENABLE_RADARR=1
      - RADARR_URL=http://radarr:7878    # Container name or IP, not localhost
      - RADARR_API_KEY=your_api_key_here
      - PREFERRED_RELEASE=either         # either, digital or physical
      - IGNORE_INCINEMAS=0               # 1 = wait for a digital/physical date, never use cinema + 90 days

      # Sonarr
      - ENABLE_SONARR=1
      - SONARR_URL=http://sonarr:8989    # Container name or IP, not localhost
      - SONARR_API_KEY=your_api_key_here

    restart: unless-stopped
```

Inside the container, `localhost` is the container itself. Use the Sonarr/Radarr container name if they share a Docker network, otherwise the host's IP.

**2. Start it:**

```bash
docker compose up -d
docker compose logs -f unmonitarr
```

**3. Check the dry run.** With `DRY_RUN=1`, nothing is changed. Each decision and each write is logged instead, so you can see exactly what it would do (see [Testing in dry-run mode](#testing-in-dry-run-mode)).

**4. Go live.** Set `DRY_RUN=0` and recreate the container:

```bash
docker compose up -d --force-recreate
```

Environment variables are read when a container is created, so `docker compose restart` won't pick up the change.

---

## Webhook Configuration

Without webhooks, unmonitarr runs every `SLEEP_MINUTES` (default 30). Something you add could be searched before the next run. Webhooks close that gap by triggering a run the moment you add content.

### Sonarr webhook

1. Settings → **Connect** → **Add** → **Webhook**
2. **Name**: `unmonitarr`
3. **URL**: `http://unmonitarr:5099/trigger/sonarr`
   - Same host, not on a shared Docker network: `http://<host-ip>:5099/trigger/sonarr`
   - Docker Desktop: `http://host.docker.internal:5099/trigger/sonarr`
4. **Method**: `POST`
5. **Notification Triggers**: **On Series Add**
6. **Test**, then **Save**

### Radarr webhook

Same steps, with URL `http://unmonitarr:5099/trigger/radarr` and trigger **On Movie Added**.

unmonitarr ignores the webhook's contents. Any POST to the trigger URL queues a full run for that app.

---

## How It Works

Each run fetches everything from Sonarr/Radarr, decides what should change, then applies it in a few batched API calls. Runs come from the schedule (every `SLEEP_MINUTES`) and from webhooks, and never overlap for the same app.

unmonitarr doesn't trigger searches itself. Once something is monitored again, Sonarr/Radarr find it through their normal RSS sync and searches.

### Sonarr (TV)

For every episode in every **monitored season** of every **monitored series** (skipping series with the ignore tag):

- **Before air date + delay**: a monitored episode is **unmonitored**, and the series gets the auto-tag
- **No air date yet**: a monitored episode is **unmonitored**, and the series gets the auto-tag, until it has a date
- **After air date + delay**: an unmonitored episode is **re-monitored**, if the series has the auto-tag and the episode aired within `SONARR_REMONITOR_WINDOW_DAYS`
- Episodes that already have a file are left alone when `SKIP_IF_FILE=1`

The auto-tag stays on a series while any episode is still waiting, and is removed once nothing is.

Example with `DELAY_MINUTES=120` and `SLEEP_MINUTES=30`: an episode airs Wednesday at 8:00 PM. Until 10:00 PM it's unmonitored, so nothing is searched. It's monitored again on the first scheduled run after 10:00 PM, so by 10:30 PM at the latest.

### Radarr (movies)

For every movie (skipping those with the ignore tag):

- The release date is chosen by `PREFERRED_RELEASE`:
  - `either`: the earlier of the digital and physical dates
  - `digital`: digital, falling back to physical
  - `physical`: physical, falling back to digital
  - If neither exists, 90 days after the cinema release is used, matching Radarr. With `IGNORE_INCINEMAS=1`, the movie waits for a digital or physical date instead. To have a particular movie monitored from its cinema release, tag it with the ignore tag
- **Before release date + delay**, or **no release date**: a monitored movie is **unmonitored** and tagged
- **After release date + delay**: an unmonitored movie with the auto-tag is **re-monitored** and the tag removed, if it was released within `RADARR_REMONITOR_WINDOW_DAYS`
- Movies that already have a file are left alone when `SKIP_IF_FILE=1`

### Re-monitor windows

The windows stop unmonitarr from re-monitoring old content, such as a movie you watched and deleted years ago. Something still unmonitored when its window passes stays unmonitored. Monitor it by hand if you still want it, or set the window to `0` for no limit.

The window is counted from the air/release date (for a movie with only a cinema date, from 90 days after it), not from the end of the delay. **Keep delays shorter than the window** (14 days for Sonarr and 30 for Radarr by default), or the item will never be re-monitored.

---

## Configuration Reference

### General

| Variable | Default | Description |
|----------|---------|-------------|
| `TZ` | `UTC` | Timezone for log timestamps. All date calculations use UTC, so this doesn't affect timing |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING` or `ERROR` |
| `SLEEP_MINUTES` | `30` | Minutes between scheduled runs |
| `DELAY_MINUTES` | `120` | Minutes after air/release before re-monitoring. Negative values re-monitor early (e.g. `-60`) |
| `DRY_RUN` | `1` | `1` = log what would change, `0` = apply changes |
| `SKIP_IF_FILE` | `1` | Leave items that already have a file |
| `AUTO_TAG_NAME` | `auto-unmonitored` | Tag marking items unmonitarr is managing. Created if missing |
| `IGNORE_TAG_NAME` | `ignore` | Items with this tag are never touched |
| `RADARR_REMONITOR_WINDOW_DAYS` | `30` | Only re-monitor movies released within this many days (`0` = no limit) |
| `SONARR_REMONITOR_WINDOW_DAYS` | `14` | Only re-monitor episodes aired within this many days (`0` = no limit) |

**Tag names:** Sonarr v5 and Radarr 6 and later only allow `a-z`, `0-9` and `-` in tag names. Keep custom `AUTO_TAG_NAME`, `IGNORE_TAG_NAME` and `SEASON_PACK_MODE_TAG` values to those characters.

### Radarr settings

| Variable | Default | Description |
|----------|---------|-------------|
| `ENABLE_RADARR` | `1` | `1` = enabled, `0` = disabled |
| `RADARR_URL` | *required* | e.g. `http://radarr:7878`, including any URL base |
| `RADARR_API_KEY` | *required* | Settings → General → Security |
| `PREFERRED_RELEASE` | `either` | `either`, `digital` or `physical` |
| `IGNORE_INCINEMAS` | `0` | With no digital or physical date, a movie counts as released 90 days after its cinema release. `1` = wait for a real digital or physical date instead |

### Sonarr settings

| Variable | Default | Description |
|----------|---------|-------------|
| `ENABLE_SONARR` | `1` | `1` = enabled, `0` = disabled |
| `SONARR_URL` | *required* | e.g. `http://sonarr:8989`, including any URL base |
| `SONARR_API_KEY` | *required* | Settings → General → Security |
| `SEASON_PACK_MODE` | `0` | `1` = enable [season pack mode](#season-pack-mode) |
| `SEASON_PACK_MODE_TAG` | `season-pack` | Tag for series that use season pack mode |
| `SONARR_REFRESH_TBA` | `0` | `1` = enable [TBA metadata refresh](#tba-metadata-refresh) |

### Per-item delay overrides

Tag a series or movie with `delayby-<minutes>` to override `DELAY_MINUTES` for just that item. Create the tag in Sonarr/Radarr (Settings → Tags) and apply it.

- `delayby-30`: re-monitor 30 minutes after air/release
- `delayby-1440`: wait a full day
- `delayby--30`: re-monitor 30 minutes *before* air/release (note the double dash)

If an item has more than one `delayby` tag, unmonitarr uses `DELAY_MINUTES` for it and logs that it did. Overrides are limited to one year either way; larger values are ignored with a warning. An override longer than the [re-monitor window](#re-monitor-windows) means the item is never re-monitored. Tags in the older `delayby_60` format still work, but Sonarr v5 and Radarr 6 and later won't let you create new ones.

Useful for news or sport you want quickly, or a hyped release where fakes are common.

### Choosing a delay

- **30 to 120 minutes** suits most libraries: long enough for legitimate releases to appear, short enough that you barely notice.
- **A day or more** if you'd rather wait for better-quality releases.
- **Negative values** catch releases that appear before the official time, but they also let more fakes through. Use them knowingly, ideally per item with a `delayby--<N>` tag rather than globally.

---

## Season Pack Mode

For shows where Sonarr lists weekly air dates but the whole season is actually released on day one, which is common with streaming services.

Tag the series with `SEASON_PACK_MODE_TAG` (default `season-pack`) and set `SEASON_PACK_MODE=1`. When the season's first episode passes its air date + delay, unmonitarr re-monitors **every episode in that season** that has an air date, instead of waiting weeks for each one's listed date.

Example: Sonarr lists a season weekly from 1 November, but all of it is released on 1 November. With season pack mode, the whole season is monitored from 1 November + delay.

**Check Sonarr will accept the pack.** Sonarr rejects full-season packs while any episode's listed air date is more than 24 hours away, or any episode has no air date. With season pack mode on, it can still grab the individual episodes, but not the pack itself.

- **Sonarr v4**: this can't be turned off, so expect individual episodes.
- **Sonarr v5**: enable **Allow Season Pack Before All Episodes Have Aired** on a Release Profile tagged for the series. If several profiles apply, the more restrictive one wins, so it must be on for all of them. If you also use **Reject Unaired Releases**, exclude these series from that profile, since it checks every episode in the pack against its listed date.

---

## TBA Metadata Refresh

Some shows don't publish episode titles to TheTVDB until after the episode airs. Sonarr refreshes series metadata on its own cycle, roughly every 12 hours, so an episode can be imported while its title is still `TBA`, and that ends up in the filename.

With `SONARR_REFRESH_TBA=1`, unmonitarr asks Sonarr to refresh a series when it has monitored episodes that have aired but are still titled `TBA`, `TBD` or blank:

- One refresh per series, not per episode
- Retried each run until the title lands, for up to 72 hours after air, at most once an hour per series
- Episodes that already have a file are included, so the title is right in Sonarr's database

**Check this Sonarr setting:** Settings → Media Management → Importing → **Episode Title Required**. If your episode naming format includes the title, `Always` makes Sonarr hold an import while the title is still `TBA`, for up to 48 hours after air, and the refresh gets the title there sooner. `Only for Bulk Season Releases` does this only for seasons released all at once. `Never` imports straight away with `TBA` in the filename.

Sonarr doesn't rename files when metadata changes, so anything already imported as `TBA` needs renaming by hand.

---

## Testing in Dry-Run Mode

With `DRY_RUN=1`, decisions are logged as normal and every write is logged with a `[DRY]` prefix instead of being sent. For example (timestamps removed):

```text
INFO:radarr:[DRY] UNMONITOR: Example Movie until 2026-12-01T02:00:00+00:00
INFO:radarr:[DRY] PUT /api/v3/movie/editor -> {"movieIds": [12], "monitored": false, "tags": [3], "applyTags": "add"}
INFO:radarr:SUMMARY: Assessed 20, Managed 1, Unmonitored 1, Monitored 0
INFO:sonarr:UNMONITOR: Example Series – S02E05 – Episode Title (airDate: 2026-12-03T09:00:00Z)
INFO:sonarr:[DRY] PUT /api/v3/series/editor -> {"seriesIds": [87], "tags": [3], "applyTags": "add"}
INFO:sonarr:[DRY] PUT /api/v3/episode/monitor -> {"episodeIds": [4521], "monitored": false}
INFO:sonarr:SUMMARY: Assessed 447, Managed 1, Unmonitored 1, Monitored 0
```

Check the decisions look right, then set `DRY_RUN=0`.

To test the webhook and health endpoints:

```bash
curl -X POST http://localhost:5099/trigger/sonarr   # {"job":"sonarr","status":"queued"}
curl -X POST http://localhost:5099/trigger/radarr   # {"job":"radarr","status":"queued"}
curl http://localhost:5099/health                   # {"service":"unmonitarr","status":"healthy"}
```

---

## Troubleshooting

Start with the logs: `docker compose logs unmonitarr`. Failed API calls are logged as errors that name the call and the reason Sonarr/Radarr gave.

| Log message | What to check |
|-------------|---------------|
| `401 Unauthorized (check the API key)` | The API key for that app |
| `no response from http://...` | The URL, and that Sonarr/Radarr is reachable from the container. Each run makes 3 attempts |
| `isn't a valid URL` | Include `http://` or `https://` in the URL |
| `returned something other than JSON` | The URL, including any URL base (e.g. `http://radarr:7878/radarr`) |
| `Couldn't create tag ...: Allowed characters a-z, 0-9 and -` | A tag name with `_` or other characters newer versions reject. See [tag names](#general) |
| `is enabled but ... not set` | The missing URL or API key, or set `ENABLE_SONARR=0` / `ENABLE_RADARR=0` |
| `Couldn't add auto-tag to <series>` | Sonarr rejected an edit to that series. Its episodes are left monitored; the reason follows in the message |

**Nothing is changing:** check `DRY_RUN=0`, the item isn't tagged with the ignore tag, and its season (for Sonarr) is monitored.

**Allowed Hosts:** recent Sonarr v4 releases, Sonarr v5 and Radarr 6.4.3 and later have an Allowed Hosts setting. If you've filled it in, add the host name from your `SONARR_URL`/`RADARR_URL`, or unmonitarr's requests will be rejected.

**Re-monitored at the wrong time:** check the air/release dates in Sonarr/Radarr and any `delayby` tags on the item. `TZ` only affects log timestamps.

**Webhooks not arriving:** check port 5099 is reachable from Sonarr/Radarr, test with `curl` as above, and watch the logs when you press **Test** in Sonarr/Radarr.

**Config changes not applying:** recreate the container with `docker compose up -d --force-recreate`. A restart keeps the old environment.

---

## Advanced Configuration

### Shared Docker network

If Sonarr/Radarr run on a custom Docker network, join it and use their container names:

```yaml
services:
  unmonitarr:
    image: ghcr.io/unmonitarr/unmonitarr:latest
    container_name: unmonitarr
    ports:
      - "5099:5099"
    networks:
      - media
    environment:
      - RADARR_URL=http://radarr:7878
      - SONARR_URL=http://sonarr:8989
      # ... other settings ...
    restart: unless-stopped

networks:
  media:
    external: true
```

### Environment file

Keep settings in a `.env` file next to `docker-compose.yml` and reference it with `env_file`:

```yaml
services:
  unmonitarr:
    image: ghcr.io/unmonitarr/unmonitarr:latest
    container_name: unmonitarr
    ports:
      - "5099:5099"
    env_file:
      - .env
    restart: unless-stopped
```

See [`.env.example`](.env.example) for every setting.

### Multiple instances

Run one unmonitarr container per Sonarr/Radarr instance, each with its own settings and port.

---

## FAQ

### Which Sonarr and Radarr versions are supported?

Sonarr v4 and v5, and Radarr 5 to 7. All of them serve the `/api/v3` API unmonitarr uses. Sonarr v5 is in beta and has been checked against its source rather than a live instance.

### Does it touch my media files?

No. It only changes monitored status and tags in Sonarr/Radarr.

### What happens if I stop it?

Everything stays as it was last left. Anything unmonitarr unmonitored stays unmonitored until it runs again, so if you remove it for good, re-monitor anything still carrying the auto-tag.

### Does it work with Lidarr or other *arr apps?

Not currently. Only Sonarr and Radarr are supported.

### Will it slow down my downloads?

Only by your chosen delay, plus up to `SLEEP_MINUTES` until the next scheduled run notices it has passed. That's the trade: a short wait for fewer fakes.

### Can I exclude specific shows or movies?

Yes. Tag them with `IGNORE_TAG_NAME` (default `ignore`).

---

## Contributing

Contributions are welcome:

- **Bugs**: open an issue with your logs (`LOG_LEVEL=DEBUG` helps)
- **Features**: open an issue or discussion
- **Pull requests**: bug fixes, features and documentation

### Development Setup

```bash
git clone https://github.com/unmonitarr/unmonitarr.git
cd unmonitarr
pip install -r requirements.txt

cp .env.example .env    # fill in your settings, keep DRY_RUN=1
./scripts/run_local.sh

PYTHONPATH=src python3 -m unittest discover tests
```

See [docs/TESTING.md](docs/TESTING.md) for writing tests, dry runs against your own Sonarr/Radarr, and testing Docker builds.

---

## License

MIT. See [LICENSE](LICENSE).

---

## Acknowledgements

- The [Sonarr](https://sonarr.tv) and [Radarr](https://radarr.video) teams
- The self-hosted community for feedback and ideas
- Everyone who's had to clean up one fake pre-release download too many

---

<div align="center">
  <p>If unmonitarr helps you, consider giving it a star.</p>
</div>
