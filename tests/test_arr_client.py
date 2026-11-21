import logging
import unittest
from unittest.mock import MagicMock, patch

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
        responses = {"POST": FakeResponse({"id": 9, "label": "new"}, 201),
                     "GET": FakeResponse([{"id": 9, "label": "new"}])}
        req = MagicMock(side_effect=lambda method, path, **kw: responses[method])
        self.assertEqual(arr_client.ensure_tag(req, "new", {}, dry_run=False, log=log), 9)

    def test_ensure_tag_dry_run_returns_placeholder(self):
        req = MagicMock()
        with self.assertLogs(log, level="INFO"):
            tid = arr_client.ensure_tag(req, "new", {}, dry_run=True, log=log)
        self.assertEqual(tid, arr_client.DRY_RUN_TAG_ID)
        req.assert_not_called()

    def test_ensure_tag_raises_when_create_fails(self):
        req = MagicMock(return_value=FakeResponse({}, 400))
        with self.assertRaises(RuntimeError):
            arr_client.ensure_tag(req, "new", {}, dry_run=False, log=log)


if __name__ == "__main__":
    unittest.main()
