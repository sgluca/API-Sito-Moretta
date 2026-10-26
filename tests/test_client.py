import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

import requests

from moretta.client import WordPressClient, WordPressError
from moretta.config import normalize_url, save_config
from moretta.cli import main


def response(data, status=200):
    result = Mock()
    result.status_code = status
    result.ok = 200 <= status < 400
    result.json.return_value = data
    return result


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.client = WordPressClient("https://example.org", "editor", "abcd efgh ijkl")
        self.http = Mock(return_value=response({"id": 10}))
        self.client.session.request = self.http

    def test_https_and_clean_urls_required(self):
        for url in ("http://example.org", "https://user:pass@example.org", "https://example.org?q=1", "https://example.org/#x"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                normalize_url(url)
        self.assertEqual(normalize_url("example.org/wp-json/"), "https://example.org")
        self.assertEqual(normalize_url("https://example.org/blog/"), "https://example.org/blog")

    def test_application_password_and_redirect_policy(self):
        self.assertEqual(self.client.session.auth, ("editor", "abcdefghijkl"))
        self.client.get("posts", 10, edit=True)
        args, kwargs = self.http.call_args
        self.assertEqual(args, ("GET", "https://example.org/wp-json/wp/v2/posts/10"))
        self.assertEqual(kwargs["params"], {"context": "edit"})
        self.assertFalse(kwargs["allow_redirects"])
        self.assertEqual(kwargs["timeout"], 40)

    def test_new_posts_default_to_draft(self):
        self.client.create_post("Titolo", "<!-- wp:paragraph --><p>Ciao</p><!-- /wp:paragraph -->")
        payload = self.http.call_args.kwargs["json"]
        self.assertEqual(payload["status"], "draft")
        self.assertIn("<!-- wp:paragraph -->", payload["content"])

    def test_publishing_is_explicit(self):
        self.client.create_post("Titolo", status="publish", categories=[3])
        self.assertEqual(self.http.call_args.kwargs["json"]["status"], "publish")

    def test_update_post_sends_only_changed_fields(self):
        self.client.update_post(10, title="Altro")
        self.assertEqual(self.http.call_args.kwargs["json"], {"title": "Altro"})

    def test_event_creation_uses_tec_and_rome(self):
        self.client.create_event("Messa", "2026-12-01 10:00:00", "2026-12-01 11:00:00", image=42)
        self.assertTrue(self.http.call_args.args[1].endswith("tribe/events/v1/events"))
        payload = self.http.call_args.kwargs["json"]
        self.assertEqual(payload["timezone"], "Europe/Rome")
        self.assertEqual(payload["status"], "draft")
        self.assertEqual(payload["image"], 42)

    def test_invalid_event_dates_never_write(self):
        for start, end in (("bad", "2026-12-01 11:00:00"), ("2026-12-02", "2026-12-01"), ("2026-12-01T10:00:00+01:00", "2026-12-01T11:00:00+01:00")):
            with self.subTest(start=start), self.assertRaises(ValueError):
                self.client.create_event("Messa", start, end)
        self.http.assert_not_called()

    def test_event_partial_updates_preserve_implicit_defaults(self):
        existing = {"id": 10, "title": "Prima", "status": "publish", "all_day": True,
                    "show_map": True, "show_map_link": True, "sticky": True, "featured": True,
                    "hidden": True, "website": "https://example.org/incontro",
                    "start_date": "2026-12-01 10:00:00", "end_date": "2026-12-01 11:00:00"}
        self.http.side_effect = [response(existing), response({"id": 10})]
        self.client.update_event(10, title="Dopo")
        payload = self.http.call_args.kwargs["json"]
        self.assertTrue(payload["all_day"])
        self.assertTrue(payload["featured"])
        self.assertTrue(payload["hide_from_listings"])
        self.assertEqual(payload["website"], existing["website"])
        self.assertEqual(payload["title"], "Dopo")
        self.assertNotIn("description", payload)

    def test_partial_date_change_checks_unchanged_other_end(self):
        self.http.return_value = response({"start_date": "2026-12-01 10:00:00", "end_date": "2026-12-01 11:00:00"})
        with self.assertRaises(ValueError):
            self.client.update_event(10, start_date="2026-12-02 10:00:00")
        self.assertEqual(self.http.call_count, 1)

    def test_event_editor_reads_raw_gutenberg_content(self):
        self.http.side_effect = [response({"id": 10, "description": "<p>rendered</p>"}),
                                 response({"title": {"raw": "Titolo"}, "content": {"raw": "<!-- wp:test /-->"}, "excerpt": {"raw": ""}, "status": "draft"})]
        result = self.client.get("events", 10, edit=True)
        self.assertEqual(result["description"], "<!-- wp:test /-->")
        self.assertIn("wp/v2/tribe_events/10", self.http.call_args.args[1])

    def test_upload_contains_file_and_alt_text_in_single_request(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "locandina.jpg"
            path.write_bytes(b"image payload")
            seen = {}

            def upload(*args, **kwargs):
                seen["bytes"] = kwargs["files"]["file"][1].read()
                seen["mime"] = kwargs["files"]["file"][2]
                return response({"id": 42})

            self.http.side_effect = upload
            result = self.client.upload_media(path, alt_text="Descrizione", title="Locandina")
            self.assertEqual(result["id"], 42)
            self.assertEqual(seen, {"bytes": b"image payload", "mime": "image/jpeg"})
            self.assertIsNone(self.http.call_args.kwargs["json"])
            self.assertEqual(self.http.call_args.kwargs["data"]["alt_text"], "Descrizione")
            self.assertEqual(self.http.call_count, 1)

    def test_error_includes_wp_status_and_code(self):
        self.http.return_value = response({"code": "rest_cannot_create", "message": "Non autorizzato"}, 403)
        with self.assertRaises(WordPressError) as error:
            self.client.create_post("Titolo")
        self.assertEqual(error.exception.status, 403)
        self.assertEqual(error.exception.code, "rest_cannot_create")

    def test_redirects_are_not_followed(self):
        self.http.return_value = response({}, 301)
        with self.assertRaisesRegex(WordPressError, "reindirizza"):
            self.client.get("posts", 10)

    def test_non_json_response(self):
        self.http.return_value.json.side_effect = ValueError("HTML")
        with self.assertRaisesRegex(WordPressError, "JSON"):
            self.client.get("posts", 10)

    def test_timeout_does_not_retry_and_warns_about_duplicates(self):
        self.http.side_effect = requests.Timeout()
        with self.assertRaisesRegex(WordPressError, "prima di ripetere"):
            self.client.create_post("Titolo")
        self.assertEqual(self.http.call_count, 1)

    def test_cannot_permanently_delete_trashed_post(self):
        self.http.return_value = response({"id": 10, "status": "trash"})
        with self.assertRaises(ValueError):
            self.client.trash("posts", 10)
        self.assertEqual(self.http.call_count, 1)

    def test_media_deletion_is_not_supported(self):
        with self.assertRaises(ValueError):
            self.client.trash("media", 10)
        self.http.assert_not_called()

    def test_invalid_id_never_sends_request(self):
        for value in (0, -1, "abc", "1/2", True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.client.get("posts", value)
        self.http.assert_not_called()

    def test_list_preserves_pagination_and_filters(self):
        self.client.list("events", page=3, per_page=20, status="draft", search="Messa")
        self.assertEqual(self.http.call_args.kwargs["params"], {"page": 3, "per_page": 20, "status": "draft", "search": "Messa"})


class ConfigurationAndCliTests(unittest.TestCase):
    def test_password_never_saved_in_configuration_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            with patch("moretta.config.CONFIG_PATH", path), patch("moretta.config.keyring.set_password") as vault:
                save_config("example.org", "editor", "secret password")
            self.assertEqual(json.loads(path.read_text()), {"url": "https://example.org", "username": "editor"})
            self.assertNotIn("secret", path.read_text())
            vault.assert_called_once_with("moretta-wordpress:https://example.org", "editor", "secretpassword")

    def test_cli_can_load_utf8_bom_json_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.json"
            path.write_text(json.dumps({"title": "Comunità"}), encoding="utf-8-sig")
            client = Mock()
            client.create_post.return_value = {"id": 42, "status": "draft"}
            out = io.StringIO()
            with patch("moretta.cli.WordPressClient.from_config", return_value=client), redirect_stdout(out):
                main(["create", "posts", "--file", str(path)])
            self.assertEqual(json.loads(out.getvalue())["id"], 42)
            client.create_post.assert_called_once_with(title="Comunità")

    def test_cli_error_exit_and_json(self):
        err = io.StringIO()
        with patch("moretta.cli.WordPressClient.from_config", side_effect=ValueError("Non configurato")), redirect_stderr(err), self.assertRaises(SystemExit) as error:
            main(["check"])
        self.assertEqual(error.exception.code, 1)
        self.assertEqual(json.loads(err.getvalue())["error"], "Non configurato")


if __name__ == "__main__":
    unittest.main()
