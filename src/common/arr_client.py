"""Helpers shared by the Sonarr and Radarr apps.

Both apps speak the same v3 API conventions for requests and tags, so the logic lives
here once. Each app keeps a thin `_req` wrapper that passes in its own URL, API key and
DRY_RUN setting. That wrapper is also the seam tests patch.
"""
import json
import re
from datetime import timedelta

import requests

WRITE_METHODS = ("POST", "PUT", "PATCH", "DELETE")

# Placeholder id returned for a tag that would be created in a dry run
DRY_RUN_TAG_ID = 999999

_DELAY_TAG_RE = re.compile(r"^delayby_(-?\d+)$", re.IGNORECASE)


class DryRunResponse:
    """Stands in for a write response when DRY_RUN is on."""
    ok = True
    status_code = 200
    text = ""

    def json(self):
        return {}


def request(base_url, api_key, method, path, *, dry_run, log, timeout=30, **kw):
    """Send a request to a Sonarr/Radarr API. Writes are logged, not sent, in a dry run."""
    method = method.upper()
    if method in WRITE_METHODS and dry_run:
        payload = kw.get("json") or kw.get("data")
        log.info("[DRY] %s %s -> %s", method, path, json.dumps(payload) if payload else "(no body)")
        return DryRunResponse()
    with requests.Session() as session:
        session.headers.update({"X-Api-Key": api_key})
        return session.request(method, f"{base_url}{path}", timeout=timeout, **kw)


def fetch_tags(req):
    """Return ({id: label}, {lowercase label: id}) for all tags."""
    items = req("GET", "/api/v3/tag").json()
    id_to_label = {int(t["id"]): t["label"] for t in items}
    label_to_id = {t["label"].lower(): int(t["id"]) for t in items}
    return id_to_label, label_to_id


def ensure_tag(req, label, label_to_id, *, dry_run, log):
    """Return the id of a tag, creating it if needed."""
    if label.lower() in label_to_id:
        return label_to_id[label.lower()]
    if dry_run:
        log.info("[DRY] POST /api/v3/tag -> {\"label\": \"%s\"}", label)
        return DRY_RUN_TAG_ID
    r = req("POST", "/api/v3/tag", json={"label": label})
    if r.ok:
        _, label_to_id = fetch_tags(req)
        return label_to_id.get(label.lower())
    raise RuntimeError("Failed to ensure tag")


def get_delay_override(tag_ids, id_to_label, title, log):
    """Return a timedelta from a delayby_<N> tag, or None.

    More than one delayby tag on the same item is ambiguous, so it falls back to None
    (the global delay) and logs it.
    """
    matches = []
    for tid in tag_ids:
        m = _DELAY_TAG_RE.match(id_to_label.get(int(tid), ""))
        if m:
            matches.append(int(m.group(1)))
    if len(matches) > 1:
        log.info("Multiple delayby_ tags found for %s, falling back to default delay", title)
        return None
    if matches:
        log.debug("Using delay override of %d min for %s", matches[0], title)
        return timedelta(minutes=matches[0])
    return None
