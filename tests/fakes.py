"""Stateful fakes for the Sonarr and Radarr APIs.

Tests patch an app module's `_req` with one of these. Writes are applied to the fake's
own data, so tests can assert on the end state (what is monitored, which tags are set)
rather than on exact call sequences. That keeps tests stable when the code switches
between equivalent endpoints, e.g. a full-object PUT versus a bulk editor call.
"""
import copy
import re
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace


def iso(dt):
    """Sonarr-style UTC timestamp."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def hours_from_now(hours):
    return iso(datetime.now(timezone.utc) + timedelta(hours=hours))


def make_config(**overrides):
    """A complete config object. Every attribute the apps read is set explicitly."""
    values = dict(
        TZ="UTC",
        SLEEP_MINUTES=30,
        AUTO_TAG_NAME="auto-unmonitored",
        IGNORE_TAG_NAME="ignore",
        DELAY_MINUTES=120,
        SKIP_IF_FILE=True,
        ENABLE_RADARR=True,
        RADARR_URL="http://radarr.test",
        RADARR_API_KEY="radarr-key",
        PREFERRED_RELEASE="either",
        IGNORE_INCINEMAS=False,
        ENABLE_SONARR=True,
        SONARR_URL="http://sonarr.test",
        SONARR_API_KEY="sonarr-key",
        SEASON_PACK_MODE=False,
        SEASON_PACK_MODE_TAG="season-pack",
        SONARR_REFRESH_TBA=False,
        RADARR_REMONITOR_WINDOW_DAYS=30,
        SONARR_REMONITOR_WINDOW_DAYS=14,
        DRY_RUN=False,
        LOG_LEVEL="INFO",
    )
    values.update(overrides)
    return SimpleNamespace(**values)


class FakeResponse:
    def __init__(self, data=None, status_code=200, text=""):
        self._data = data
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self.text = text

    def json(self):
        return copy.deepcopy(self._data)


class _FakeArrBase:
    def __init__(self, tags):
        self.tags = [dict(t) for t in tags]
        self.calls = []  # (method, path, json, params)

    def __call__(self, method, path, **kw):
        method = method.upper()
        self.calls.append((method, path, kw.get("json"), kw.get("params")))
        return self._route(method, path, kw.get("json"), kw.get("params") or {})

    @property
    def writes(self):
        return [c for c in self.calls if c[0] != "GET"]

    def tag_id(self, label):
        for t in self.tags:
            if t["label"].lower() == label.lower():
                return t["id"]
        return None

    def _tags_route(self, method, body):
        if method == "GET":
            return FakeResponse(self.tags)
        if method == "POST":
            new = {"id": max([t["id"] for t in self.tags] or [0]) + 1, "label": body["label"]}
            self.tags.append(new)
            return FakeResponse(new, 201)
        raise AssertionError(f"Unexpected {method} /tag")

    @staticmethod
    def _apply_tags(current, tag_ids, mode):
        current = list(current)
        if mode == "add":
            for t in tag_ids:
                if t not in current:
                    current.append(t)
        elif mode == "remove":
            current = [t for t in current if t not in tag_ids]
        elif mode == "replace":
            current = list(tag_ids)
        else:
            raise AssertionError(f"Unknown applyTags {mode!r}")
        return current


class FakeSonarr(_FakeArrBase):
    """series: list of series dicts. episodes: {(series_id, season_number): [episode dicts]}."""

    def __init__(self, series, episodes, tags=({"id": 1, "label": "auto-unmonitored"},)):
        super().__init__(tags)
        self.series = {s["id"]: copy.deepcopy(s) for s in series}
        self.episodes = {k: copy.deepcopy(v) for k, v in episodes.items()}

    def episode(self, episode_id):
        for eps in self.episodes.values():
            for e in eps:
                if e["id"] == episode_id:
                    return e
        raise KeyError(episode_id)

    def _route(self, method, path, body, params):
        if path == "/api/v3/tag":
            return self._tags_route(method, body)
        if path == "/api/v3/series" and method == "GET":
            return FakeResponse(list(self.series.values()))
        if path == "/api/v3/series/editor" and method == "PUT":
            for sid in body["seriesIds"]:
                s = self.series[sid]
                if body.get("tags") is not None:
                    s["tags"] = self._apply_tags(s.get("tags", []), body["tags"], body.get("applyTags", "add"))
                if body.get("monitored") is not None:
                    s["monitored"] = body["monitored"]
            return FakeResponse([self.series[sid] for sid in body["seriesIds"]], 202)
        m = re.fullmatch(r"/api/v3/series/(\d+)", path)
        if m:
            sid = int(m.group(1))
            if method == "GET":
                return FakeResponse(self.series[sid])
            if method == "PUT":
                self.series[sid] = copy.deepcopy(body)
                return FakeResponse(body, 202)
        if path == "/api/v3/episode" and method == "GET":
            key = (int(params["seriesId"]), int(params["seasonNumber"]))
            return FakeResponse(self.episodes.get(key, []))
        if path == "/api/v3/episode/monitor" and method == "PUT":
            for eid in body["episodeIds"]:
                self.episode(eid)["monitored"] = body["monitored"]
            return FakeResponse([], 202)
        if path == "/api/v3/command" and method == "POST":
            return FakeResponse({"id": 1, "name": body["name"]}, 201)
        raise AssertionError(f"Unexpected Sonarr call {method} {path}")


class FakeRadarr(_FakeArrBase):
    def __init__(self, movies, tags=({"id": 1, "label": "auto-unmonitored"},)):
        super().__init__(tags)
        self.movies = {m["id"]: copy.deepcopy(m) for m in movies}

    def _route(self, method, path, body, params):
        if path == "/api/v3/tag":
            return self._tags_route(method, body)
        if path == "/api/v3/movie" and method == "GET":
            return FakeResponse(list(self.movies.values()))
        if path == "/api/v3/movie/editor" and method == "PUT":
            for mid in body["movieIds"]:
                mv = self.movies[mid]
                if body.get("monitored") is not None:
                    mv["monitored"] = body["monitored"]
                if body.get("tags") is not None:
                    mv["tags"] = self._apply_tags(mv.get("tags", []), body["tags"], body.get("applyTags", "add"))
            return FakeResponse([], 200)
        raise AssertionError(f"Unexpected Radarr call {method} {path}")


def http_transport(fake, base_url, api_key, testcase):
    """A stand-in for requests.Session.request that routes to a fake API.

    Use when a test needs the app's real `_req` (DRY_RUN handling, headers, status checks):
        patch("requests.Session.request", http_transport(fake, cfg.SONARR_URL, cfg.SONARR_API_KEY, self))
    """
    def request(session, method, url, **kw):
        testcase.assertTrue(url.startswith(base_url), url)
        testcase.assertEqual(session.headers.get("X-Api-Key"), api_key)
        kw.pop("timeout", None)
        return fake(method, url[len(base_url):], **kw)
    return request
