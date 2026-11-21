"""Helpers shared by the Sonarr and Radarr apps.

Both apps speak the same v3 API conventions for requests and tags, so the logic lives
here once. Each app keeps a thin `_req` wrapper that passes in its own URL, API key and
DRY_RUN setting. That wrapper is also the seam tests patch.
"""
import json
import re
import time
from datetime import datetime, timedelta, timezone

import requests

WRITE_METHODS = ("POST", "PUT", "PATCH", "DELETE")

# Placeholder id returned for a tag that would be created in a dry run
DRY_RUN_TAG_ID = 999999

# delayby-<minutes>, e.g. delayby-60 or delayby--30. Sonarr v5 and Radarr 6+ only allow
# a-z, 0-9 and - in tag labels. The older delayby_<minutes> form is still read, so
# existing tags keep working.
_DELAY_TAG_RE = re.compile(r"delayby[-_](-?[0-9]+)", re.IGNORECASE)

# Overrides beyond a year are almost certainly typos, and large enough values overflow
# the date maths and would fail every run
MAX_DELAY_OVERRIDE_MINUTES = 365 * 24 * 60


class ArrApiError(Exception):
    """A Sonarr/Radarr API call failed. The message says which call and why."""

    def __init__(self, message, status_code=None, transient=None):
        super().__init__(message)
        self.status_code = status_code
        self._transient = transient

    @property
    def transient(self):
        """True for failures worth retrying: no response at all, or a server-side error."""
        if self._transient is not None:
            return self._transient
        return self.status_code is None or self.status_code >= 500


def _describe_body(response, limit=300):
    """The useful part of an error response, e.g. Sonarr/Radarr validation messages."""
    try:
        body = response.json()
    except ValueError:
        return (response.text or "").strip()[:limit]
    if isinstance(body, list):
        messages = [b.get("errorMessage") for b in body if isinstance(b, dict) and b.get("errorMessage")]
        if messages:
            return "; ".join(messages)[:limit]
    if isinstance(body, dict) and body.get("message"):
        return str(body["message"])[:limit]
    return json.dumps(body)[:limit]


class DryRunResponse:
    """Stands in for a write response when DRY_RUN is on."""
    ok = True
    status_code = 200
    text = ""

    def json(self):
        return {}


def request(base_url, api_key, method, path, *, dry_run, log, timeout=30, **kw):
    """Send a request to a Sonarr/Radarr API. Writes are logged, not sent, in a dry run.

    Raises ArrApiError if the server can't be reached or answers with a non-2xx status.
    """
    method = method.upper()
    if method in WRITE_METHODS and dry_run:
        payload = kw.get("json") or kw.get("data")
        log.info("[DRY] %s %s -> %s", method, path, json.dumps(payload) if payload else "(no body)")
        return DryRunResponse()
    try:
        with requests.Session() as session:
            session.headers.update({"X-Api-Key": api_key})
            response = session.request(method, f"{base_url}{path}", timeout=timeout, **kw)
    except requests.exceptions.InvalidProxyURL as e:
        raise ArrApiError(f"{method} {path} failed: the proxy URL in HTTP_PROXY/HTTPS_PROXY isn't valid "
                          f"({e})", transient=False) from e
    except (requests.exceptions.InvalidURL, requests.exceptions.MissingSchema,
            requests.exceptions.InvalidSchema) as e:
        raise ArrApiError(f"{method} {path} failed: {base_url} isn't a valid URL. Include http:// or https:// "
                          f"({e.__class__.__name__}: {e})", transient=False) from e
    except requests.RequestException as e:
        raise ArrApiError(f"{method} {path} failed: no response from {base_url} ({e.__class__.__name__}: {e})") from e
    raise_for_status(method, path, response)
    return response


def raise_for_status(method, path, response):
    """Raise ArrApiError for a non-2xx response, including the server's explanation."""
    if 200 <= response.status_code < 300:
        return
    reason = getattr(response, "reason", "") or ""
    hint = " (check the API key)" if response.status_code == 401 else ""
    detail = _describe_body(response)
    message = f"{method} {path} failed: {response.status_code} {reason}".rstrip() + hint
    if detail:
        message += f": {detail}"
    raise ArrApiError(message, status_code=response.status_code)


def get_json(req, path, **kw):
    """GET a path and decode the JSON body, with a clear error if it isn't JSON."""
    response = req("GET", path, **kw)
    try:
        return response.json()
    except ValueError as e:
        raise ArrApiError(
            f"GET {path} returned something other than JSON. Check the URL, including any URL base.",
            transient=False,
        ) from e


def parse_iso(value):
    """Parse an API timestamp to an aware UTC datetime, or None if missing or invalid."""
    if not value:
        return None
    value = value.strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def run_with_retries(fn, app_name, log, attempts=3, delay_seconds=5):
    """Run one pass, retrying failures that might be temporary.

    API errors that won't fix themselves (bad API key, validation errors) are logged once
    without retrying. Unexpected exceptions are logged with a traceback.
    """
    for attempt in range(1, attempts + 1):
        try:
            fn()
            return True
        except ArrApiError as e:
            if not e.transient:
                log.error("%s run failed: %s", app_name, e)
                return False
            if attempt < attempts:
                log.warning("%s run attempt %d/%d failed, retrying in %ds: %s",
                            app_name, attempt, attempts, delay_seconds, e)
                time.sleep(delay_seconds)
            else:
                log.error("%s run failed after %d attempts: %s", app_name, attempts, e)
        except Exception as e:
            if attempt < attempts:
                log.warning("%s run attempt %d/%d failed, retrying in %ds: %s",
                            app_name, attempt, attempts, delay_seconds, e)
                time.sleep(delay_seconds)
            else:
                log.error("%s run failed after %d attempts: %s", app_name, attempts, e, exc_info=True)
    return False


_warned_unconfigured = set()


def is_configured(app_name, enabled, url, api_key, log):
    """True if the app should run. Warns (once per process) when it's enabled but missing settings."""
    if not enabled:
        log.debug("%s is disabled, skipping", app_name)
        return False
    missing = [name for name, value in ((f"{app_name.upper()}_URL", url), (f"{app_name.upper()}_API_KEY", api_key))
               if not value]
    if missing:
        if app_name in _warned_unconfigured:
            log.debug("%s is enabled but not configured, skipping", app_name)
            return False
        _warned_unconfigured.add(app_name)
        log.warning("%s is enabled but %s not set, skipping. Set ENABLE_%s=0 to silence this.",
                    app_name, " and ".join(missing) + (" is" if len(missing) == 1 else " are"), app_name.upper())
        return False
    return True


def fetch_tags(req):
    """Return ({id: label}, {lowercase label: id}) for all tags."""
    items = get_json(req, "/api/v3/tag")
    id_to_label = {int(t["id"]): t["label"] for t in items}
    label_to_id = {t["label"].lower(): int(t["id"]) for t in items}
    return id_to_label, label_to_id


def ensure_tag(req, label, label_to_id, *, dry_run, log):
    """Return the id of a tag, creating it if needed.

    Sonarr v5 and Radarr 6+ only accept a-z, 0-9 and - in tag labels; if the label is
    rejected, the ArrApiError carries the server's validation message.
    """
    if label.lower() in label_to_id:
        return label_to_id[label.lower()]
    if dry_run:
        log.info("[DRY] POST /api/v3/tag -> {\"label\": \"%s\"}", label)
        return DRY_RUN_TAG_ID
    try:
        created = req("POST", "/api/v3/tag", json={"label": label}).json()
    except ArrApiError as e:
        raise ArrApiError(f"Couldn't create tag '{label}': {e}", status_code=e.status_code,
                          transient=e.transient) from e
    log.info("Created tag '%s'", label)
    return int(created["id"])


def bulk_edit(req, path, id_field, ids, changes):
    """Apply the same change to many items with one editor call.

    The editors validate every item and reject the whole batch if any one is invalid, so
    a rejected batch is retried one item at a time to let the rest through. Temporary
    failures are raised (the caller's whole pass is retried). Returns {id: ArrApiError}
    for items that couldn't be changed.
    """
    ids = sorted(ids)
    if not ids:
        return {}
    try:
        req("PUT", path, json={id_field: ids, **changes})
        return {}
    except ArrApiError as e:
        if e.transient:
            raise
        if len(ids) == 1:
            return {ids[0]: e}
    failed = {}
    for item_id in ids:
        try:
            req("PUT", path, json={id_field: [item_id], **changes})
        except ArrApiError as e:
            if e.transient:
                raise
            failed[item_id] = e
    return failed


def get_delay_override(tag_ids, id_to_label, title, log):
    """Return a timedelta from a delayby-<N> (or legacy delayby_<N>) tag, or None.

    More than one delayby tag on the same item is ambiguous, so it falls back to None
    (the global delay) and logs it.
    """
    matches = []
    for tid in tag_ids:
        label = id_to_label.get(int(tid), "")
        m = _DELAY_TAG_RE.fullmatch(label)
        if not m:
            continue
        minutes = int(m.group(1))
        if abs(minutes) > MAX_DELAY_OVERRIDE_MINUTES:
            log.warning("Ignoring tag %s on %s: delay overrides are limited to %d minutes (one year)",
                        label, title, MAX_DELAY_OVERRIDE_MINUTES)
            continue
        matches.append(minutes)
    if len(matches) > 1:
        log.info("Multiple delayby tags found for %s, falling back to default delay", title)
        return None
    if matches:
        log.debug("Using delay override of %d min for %s", matches[0], title)
        return timedelta(minutes=matches[0])
    return None
