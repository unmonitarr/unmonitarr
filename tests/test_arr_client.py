import logging
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import requests

from common import arr_client
from tests.fakes import FakeResponse

log = logging.getLogger("test_arr_client")


class TestRequest(unittest.TestCase):
    def test_live_request_sends_api_key_and_full_url(self):
        seen = {}

        def fake_request(session, method, url, **kw):
            seen.update(method=method, url=url, key=session.headers.get("X-Api-Key"), timeout=kw.get("timeout"))
            return FakeResponse([])

        with patch("requests.Session.request", fake_request):
            arr_client.request("http://arr.test", "abc", "get", "/api/v3/tag", dry_run=False, log=log)
        self.assertEqual(seen, {"method": "GET", "url": "http://arr.test/api/v3/tag", "key": "abc", "timeout": 30})

    def test_dry_run_write_is_logged_not_sent(self):
        with patch("requests.Session.request") as sent, self.assertLogs(log, level="INFO") as cm:
            r = arr_client.request("http://arr.test", "abc", "PUT", "/api/v3/x", dry_run=True, log=log,
                                   json={"a": 1})
        sent.assert_not_called()
        self.assertTrue(r.ok)
        self.assertEqual(r.json(), {})
        self.assertIn('[DRY] PUT /api/v3/x -> {"a": 1}', cm.output[0])

    def test_dry_run_still_sends_reads(self):
        with patch("requests.Session.request", return_value=FakeResponse([])) as sent:
            arr_client.request("http://arr.test", "abc", "GET", "/api/v3/tag", dry_run=True, log=log)
        sent.assert_called_once()


class TestTags(unittest.TestCase):
    def test_fetch_tags_builds_both_maps(self):
        req = MagicMock(return_value=FakeResponse([{"id": 1, "label": "Auto-Unmonitored"}]))
        id_to_label, label_to_id = arr_client.fetch_tags(req)
        self.assertEqual(id_to_label, {1: "Auto-Unmonitored"})
        self.assertEqual(label_to_id, {"auto-unmonitored": 1})

    def test_ensure_tag_returns_existing_id_case_insensitively(self):
        req = MagicMock()
        self.assertEqual(arr_client.ensure_tag(req, "Ignore", {"ignore": 7}, dry_run=False, log=log), 7)
        req.assert_not_called()

    def test_ensure_tag_creates_missing_tag(self):
        req = MagicMock(return_value=FakeResponse({"id": 9, "label": "new"}, 201))
        with self.assertLogs(log, level="INFO"):
            self.assertEqual(arr_client.ensure_tag(req, "new", {}, dry_run=False, log=log), 9)
        req.assert_called_once_with("POST", "/api/v3/tag", json={"label": "new"})

    def test_ensure_tag_dry_run_returns_placeholder(self):
        req = MagicMock()
        with self.assertLogs(log, level="INFO"):
            tid = arr_client.ensure_tag(req, "new", {}, dry_run=True, log=log)
        self.assertEqual(tid, arr_client.DRY_RUN_TAG_ID)
        req.assert_not_called()

    def test_ensure_tag_failure_names_the_tag_and_keeps_server_message(self):
        def req(method, path, **kw):
            arr_client.raise_for_status(method, path, FakeResponse(
                [{"propertyName": "Label", "errorMessage": "Allowed characters a-z, 0-9 and -"}], 400))
        with self.assertRaises(arr_client.ArrApiError) as cm:
            arr_client.ensure_tag(req, "auto_unmonitored", {}, dry_run=False, log=log)
        self.assertIn("auto_unmonitored", str(cm.exception))
        self.assertIn("Allowed characters a-z, 0-9 and -", str(cm.exception))
        self.assertFalse(cm.exception.transient)


class TestErrors(unittest.TestCase):
    def send(self, response=None, exc=None):
        def fake_request(session, method, url, **kw):
            if exc:
                raise exc
            return response
        with patch("requests.Session.request", fake_request):
            return arr_client.request("http://arr.test", "abc", "GET", "/api/v3/series", dry_run=False, log=log)

    def test_success_returns_response(self):
        r = FakeResponse([1], 200)
        self.assertIs(self.send(r), r)

    def test_401_hints_at_api_key(self):
        with self.assertRaises(arr_client.ArrApiError) as cm:
            self.send(FakeResponse({"message": "Unauthorized"}, 401))
        self.assertIn("GET /api/v3/series failed: 401", str(cm.exception))
        self.assertIn("check the API key", str(cm.exception))
        self.assertFalse(cm.exception.transient)

    def test_404_includes_text_body(self):
        r = FakeResponse(None, 404, text="Not Found")
        r.json = MagicMock(side_effect=ValueError)
        with self.assertRaises(arr_client.ArrApiError) as cm:
            self.send(r)
        self.assertIn("404", str(cm.exception))
        self.assertIn("Not Found", str(cm.exception))

    def test_500_is_transient(self):
        with self.assertRaises(arr_client.ArrApiError) as cm:
            self.send(FakeResponse({"message": "boom"}, 500))
        self.assertTrue(cm.exception.transient)

    def test_unreachable_server_is_transient_and_names_url(self):
        with self.assertRaises(arr_client.ArrApiError) as cm:
            self.send(exc=requests.ConnectionError("refused"))
        self.assertIn("http://arr.test", str(cm.exception))
        self.assertTrue(cm.exception.transient)

    def test_timeout_is_transient(self):
        with self.assertRaises(arr_client.ArrApiError) as cm:
            self.send(exc=requests.ReadTimeout("slow"))
        self.assertIn("ReadTimeout", str(cm.exception))
        self.assertTrue(cm.exception.transient)

    def test_get_json_explains_non_json_body(self):
        r = FakeResponse(None, 200, text="<html>login</html>")
        r.json = MagicMock(side_effect=ValueError)
        with self.assertRaises(arr_client.ArrApiError) as cm:
            arr_client.get_json(MagicMock(return_value=r), "/api/v3/series")
        self.assertIn("URL base", str(cm.exception))


class TestRunWithRetries(unittest.TestCase):
    def run_it(self, fn):
        with patch("common.arr_client.time.sleep") as sleep:
            ok = arr_client.run_with_retries(fn, "Sonarr", log)
        return ok, sleep

    def test_success(self):
        fn = MagicMock()
        ok, sleep = self.run_it(fn)
        self.assertTrue(ok)
        fn.assert_called_once()
        sleep.assert_not_called()

    def test_permanent_api_error_is_not_retried(self):
        fn = MagicMock(side_effect=arr_client.ArrApiError("GET /x failed: 401", status_code=401))
        with self.assertLogs(log, level="ERROR") as cm:
            ok, sleep = self.run_it(fn)
        self.assertFalse(ok)
        fn.assert_called_once()
        self.assertIn("Sonarr run failed: GET /x failed: 401", cm.output[0])

    def test_transient_error_is_retried_then_succeeds(self):
        fn = MagicMock(side_effect=[arr_client.ArrApiError("down"), None])
        with self.assertLogs(log, level="WARNING"):
            ok, sleep = self.run_it(fn)
        self.assertTrue(ok)
        self.assertEqual(fn.call_count, 2)
        sleep.assert_called_once_with(5)

    def test_transient_error_gives_up_after_three_attempts(self):
        fn = MagicMock(side_effect=arr_client.ArrApiError("down"))
        with self.assertLogs(log, level="WARNING") as cm:
            ok, _ = self.run_it(fn)
        self.assertFalse(ok)
        self.assertEqual(fn.call_count, 3)
        self.assertTrue(any("ERROR" in l and "after 3 attempts" in l for l in cm.output))

    def test_unexpected_error_logs_traceback(self):
        fn = MagicMock(side_effect=KeyError("id"))
        with self.assertLogs(log, level="WARNING") as cm:
            self.run_it(fn)
        self.assertTrue(any("Traceback" in l for l in cm.output))


class TestIsConfigured(unittest.TestCase):
    def test_disabled_is_quiet(self):
        with self.assertNoLogs(log, level="INFO"):
            self.assertFalse(arr_client.is_configured("Sonarr", False, "", "", log))

    def test_enabled_and_configured(self):
        self.assertTrue(arr_client.is_configured("Sonarr", True, "http://x", "k", log))

    def test_enabled_but_missing_settings_warns(self):
        with self.assertLogs(log, level="WARNING") as cm:
            self.assertFalse(arr_client.is_configured("Radarr", True, "http://x", "", log))
        self.assertIn("RADARR_API_KEY is not set", cm.output[0])


class TestParseIso(unittest.TestCase):
    def test_formats(self):
        expected = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
        for value in ("2026-01-02T03:04:05Z", "2026-01-02T03:04:05.000Z", "2026-01-02T03:04:05+00:00",
                      "2026-01-02T13:04:05+10:00", "2026-01-02T03:04:05"):
            self.assertEqual(arr_client.parse_iso(value), expected, value)

    def test_missing_or_invalid(self):
        for value in (None, "", "TBA", "2026-13-45"):
            self.assertIsNone(arr_client.parse_iso(value), value)


if __name__ == "__main__":
    unittest.main()
