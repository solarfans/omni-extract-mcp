from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import apify_main


class _FakeResp:
    def __init__(self, status: int = 200):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class TestApifyMainPPE(unittest.TestCase):
    def test_actor_run_id_precedence_and_legacy_fallback(self) -> None:
        seen_urls: list[str] = []

        def fake_urlopen(req, timeout=10):
            seen_urls.append(req.full_url)
            return _FakeResp(200)

        with mock.patch.dict(
            os.environ,
            {
                "ACTOR_RUN_ID": "run_new_123",
                "APIFY_ACTOR_RUN_ID": "run_old_999",
                "APIFY_TOKEN": "tok_test",
                "APIFY_API_PUBLIC_BASE_URL": "https://api.apify.com",
            },
            clear=False,
        ), mock.patch.object(apify_main.urllib.request, "urlopen", side_effect=fake_urlopen):
            ok, err = apify_main._charge_apify_ppe_event("content_item_extracted", 1)
            self.assertTrue(ok)
            self.assertIsNone(err)
            self.assertIn("/v2/actor-runs/run_new_123/charge", seen_urls[-1])

        with mock.patch.dict(
            os.environ,
            {
                "ACTOR_RUN_ID": "",
                "APIFY_ACTOR_RUN_ID": "run_old_999",
                "APIFY_TOKEN": "tok_test",
                "APIFY_API_PUBLIC_BASE_URL": "https://api.apify.com",
            },
            clear=False,
        ), mock.patch.object(apify_main.urllib.request, "urlopen", side_effect=fake_urlopen):
            ok, err = apify_main._charge_apify_ppe_event("content_item_extracted", 1)
            self.assertTrue(ok)
            self.assertIsNone(err)
            self.assertIn("/v2/actor-runs/run_old_999/charge", seen_urls[-1])

    def test_charge_failure_emits_stderr_and_summary_counts(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            storage_dir = Path(td) / "storage"
            fake_results = [
                {"ok": True, "url": "https://x.com/a/status/1", "title": "A", "transcript": None},
            ]
            with mock.patch.dict(
                os.environ,
                {
                    "ACTOR_RUN_ID": "run_fail_1",
                    "APIFY_TOKEN": "tok_test",
                    "APIFY_INPUT_JSON": json.dumps({"urls": ["https://x.com/a/status/1"]}),
                    "APIFY_LOCAL_STORAGE_DIR": str(storage_dir),
                },
                clear=False,
            ), mock.patch.object(apify_main.OmniExtractEngine, "extract_batch", return_value=fake_results), mock.patch.object(
                apify_main.urllib.request, "urlopen", side_effect=RuntimeError("500 upstream error")
            ):
                out_buf = io.StringIO()
                err_buf = io.StringIO()
                with redirect_stdout(out_buf), redirect_stderr(err_buf):
                    rc = apify_main.main()

            self.assertEqual(rc, 0)
            self.assertIn("[apify_ppe_charge_error]", err_buf.getvalue())
            summary = json.loads(out_buf.getvalue().strip())
            self.assertEqual(summary["succeeded"], 1)
            self.assertEqual(summary["charged"], 0)
            self.assertEqual(summary["charge_failed"], 1)
            self.assertEqual(summary["charge_skipped"], 0)
            self.assertFalse(summary["used_fallback_url"])

    def test_empty_input_health_check_never_charges_ppe(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            storage_dir = Path(td) / "storage"
            fake_results = [
                {"ok": True, "url": "https://github.com/modelcontextprotocol/servers", "title": "MCP", "transcript": None},
            ]
            with mock.patch.dict(
                os.environ,
                {
                    "ACTOR_RUN_ID": "run_hc_1",
                    "APIFY_TOKEN": "tok_test",
                    "APIFY_INPUT_JSON": json.dumps({}),
                    "APIFY_LOCAL_STORAGE_DIR": str(storage_dir),
                },
                clear=False,
            ), mock.patch.object(apify_main.OmniExtractEngine, "extract_batch", return_value=fake_results), mock.patch.object(
                apify_main, "_charge_apify_ppe_event"
            ) as mock_charge:
                out_buf = io.StringIO()
                with redirect_stdout(out_buf):
                    rc = apify_main.main()

            self.assertEqual(rc, 0)
            mock_charge.assert_not_called()
            summary = json.loads(out_buf.getvalue().strip())
            self.assertEqual(summary["charged"], 0)
            self.assertEqual(summary["charge_failed"], 0)
            self.assertEqual(summary["charge_skipped"], 1)
            self.assertTrue(summary["used_fallback_url"])

    def test_successful_cloud_charge_summary(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            storage_dir = Path(td) / "storage"
            fake_results = [
                {"ok": True, "url": "https://youtube.com/watch?v=1", "title": "YT", "transcript": "hello world"},
            ]
            with mock.patch.dict(
                os.environ,
                {
                    "ACTOR_RUN_ID": "run_ok_1",
                    "APIFY_TOKEN": "tok_test",
                    "APIFY_INPUT_JSON": json.dumps({"urls": ["https://youtube.com/watch?v=1"]}),
                    "APIFY_LOCAL_STORAGE_DIR": str(storage_dir),
                },
                clear=False,
            ), mock.patch.object(apify_main.OmniExtractEngine, "extract_batch", return_value=fake_results), mock.patch.object(
                apify_main.urllib.request, "urlopen", return_value=_FakeResp(200)
            ):
                out_buf = io.StringIO()
                with redirect_stdout(out_buf):
                    rc = apify_main.main()

            self.assertEqual(rc, 0)
            summary = json.loads(out_buf.getvalue().strip())
            self.assertEqual(summary["charged"], 1)
            self.assertEqual(summary["charge_failed"], 0)
            self.assertFalse(summary["used_fallback_url"])


if __name__ == "__main__":
    unittest.main()
