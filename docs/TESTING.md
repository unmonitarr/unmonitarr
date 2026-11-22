# Testing unmonitarr

How to test changes before opening a pull request.

## Unit tests

```bash
pip install -r requirements.txt
PYTHONPATH=src python3 -m unittest discover tests
```

To run one file: `PYTHONPATH=src python3 -m unittest tests.test_sonarr_run`.

If you have pytest installed, `PYTHONPATH=src pytest tests` also works and reports the same count.
CI runs the unittest command on every push (including `main`), pull request to `main` and release
tag. Images are only published from branches other than `main` and from release tags, and only if
the tests pass. Pull requests build the image without publishing it.

Write new tests as `unittest.TestCase` subclasses. `unittest discover` silently skips bare
`def test_*` functions and pytest fixtures, so pytest-style tests never run under the documented
command.

Things worth knowing when writing tests:

- Sonarr/Radarr tests patch `Config` and `_req`, not `requests`. Because `Config` becomes a
  `MagicMock`, set every attribute the code path reads, or it will be truthy and flip a branch.
- Importing `core.job_queue` starts a real worker thread. Use a fresh `JobQueueWrapper()` instead
  of putting jobs on the global queue.
- `Config` reads the environment at import time. Testing non-default values needs
  `importlib.reload(core.config)` with cleanup.
- Never use real show or movie names in fixtures. Use generic ones like `Test Series`.

## Running locally against real Sonarr/Radarr

```bash
cp .env.example .env    # add your URLs and API keys, keep DRY_RUN=1
./scripts/run_local.sh
```

`.env` is loaded as shell, so quote any value that contains spaces.

With `DRY_RUN=1` nothing is changed. Every write is logged with a `[DRY]` prefix instead, so you
can check exactly what unmonitarr would do.

In another terminal, trigger the webhooks:

```bash
./scripts/test_webhooks.sh              # defaults to localhost:5099
./scripts/test_webhooks.sh myhost:5099
```

You should see each job queued, started and completed in the logs:

```text
INFO:webhook_service:Sonarr trigger received via webhook.
INFO:core.job_queue:Starting sonarr job (triggered_by=webhook)
...
INFO:core.job_queue:Completed sonarr job (triggered_by=webhook)
```

## Testing a Docker build

```bash
docker build -t unmonitarr:test .
```

Point `image:` in `docker-compose.yml` at `unmonitarr:test` and set your real URLs and API keys.
Inside the container `localhost` is the container itself, so use your host's IP or, on
Docker Desktop, `http://host.docker.internal:8989`. Then:

```bash
docker compose up -d
docker compose logs -f unmonitarr
```

Branches pushed to the main repository also build a dev image, e.g. `feature/my-change`
publishes `ghcr.io/unmonitarr/unmonitarr:dev-feature-my-change`. Forks don't publish there.

## Before opening a pull request

- Unit tests pass
- A dry run against your own Sonarr/Radarr logs the changes you expect
- README updated if behaviour or configuration changed
