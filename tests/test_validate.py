"""Tests for scripts/validate.py. Run: python3 -m unittest discover -s tests"""
import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("validate", ROOT / "scripts" / "validate.py")
v = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(v)

FEED = {
    "updated": "2026-10-13T23:04:44+00:00",
    "outputs": [{
        "id": "a", "ts": "2026-10-13T15:44:23+00:00", "project": "p",
        "title": "T", "type": "link", "url": "https://example.com/x", "summary": "s",
    }],
}
STATUS = {
    "updated_utc": "2026-10-22T03:53:56Z",
    "vms": [{"name": "atlas", "reachable": True, "load1": 0.1, "mem": "100/200"},
            {"name": "butler", "reachable": False, "load1": None, "mem": None}],
    "cron_count": 3,
    "outputs": {"total": 5, "public": 1},
    "world2_soak_tick": None,
    "shadow_last_run": None,
}


class RepoFiles(unittest.TestCase):
    def test_committed_snapshots_are_valid(self):
        errors, _ = v.validate_dir(ROOT)
        self.assertEqual(errors, [])


class Feed(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(v.validate_feed(FEED), [])

    def test_duplicate_ids(self):
        f = copy.deepcopy(FEED)
        f["outputs"].append(copy.deepcopy(f["outputs"][0]))
        self.assertTrue(any("duplicated" in e for e in v.validate_feed(f)))

    def test_naive_timestamp_rejected(self):
        f = copy.deepcopy(FEED)
        f["outputs"][0]["ts"] = "2026-10-13T15:44:23"
        self.assertTrue(any(".ts" in e for e in v.validate_feed(f)))

    def test_http_url_rejected(self):
        f = copy.deepcopy(FEED)
        f["outputs"][0]["url"] = "http://example.com"
        self.assertTrue(any(".url" in e for e in v.validate_feed(f)))

    def test_missing_fields(self):
        f = {"updated": "nope", "outputs": [{}]}
        errs = v.validate_feed(f)
        self.assertTrue(any("'updated'" in e for e in errs))
        for key in ("id", "project", "title", "type", "summary", "ts", "url"):
            self.assertTrue(any(f".{key}" in e for e in errs), key)


class Status(unittest.TestCase):
    def test_valid_including_unreachable_vm(self):
        self.assertEqual(v.validate_status(STATUS), [])

    def test_non_utc_rejected(self):
        s = dict(STATUS, updated_utc="2026-10-22T03:53:56-04:00")
        self.assertTrue(any("UTC" in e for e in v.validate_status(s)))

    def test_bad_vm_fields(self):
        s = copy.deepcopy(STATUS)
        s["vms"][0].update(reachable="yes", load1=-1, mem="300/200")
        errs = v.validate_status(s)
        self.assertTrue(any("reachable" in e for e in errs))
        self.assertTrue(any("load1" in e for e in errs))
        self.assertTrue(any("inconsistent" in e for e in errs))

    def test_bool_is_not_an_integer(self):
        s = dict(STATUS, cron_count=True)
        self.assertTrue(any("cron_count" in e for e in v.validate_status(s)))

    def test_public_cannot_exceed_total(self):
        s = dict(STATUS, outputs={"total": 1, "public": 2})
        self.assertTrue(any("exceeds" in e for e in v.validate_status(s)))


class LeakGuard(unittest.TestCase):
    def leaks(self, text):
        errors = []
        v.check_leaks("x", text, errors)
        return errors

    def test_flags_private_addresses_and_paths(self):
        for text in ("100.106.20.67", "10.0.0.5", "192.168.1.1", "172.20.0.1",
                     "/home/ubuntu/crawler", "/Users/lucas/x", "ghp_" + "a" * 30):
            self.assertTrue(self.leaks(text), text)

    def test_allows_public_content(self):
        self.assertEqual(self.leaks(json.dumps(FEED) + json.dumps(STATUS)), [])
        self.assertEqual(self.leaks("load 100.5 and version 1.0.0.1"), [])


class Directory(unittest.TestCase):
    def write(self, d, feed, status):
        (Path(d) / "feed.json").write_text(feed, encoding="utf-8")
        (Path(d) / "live-status.json").write_text(status, encoding="utf-8")

    def test_invalid_json_and_main_exit_code(self):
        with tempfile.TemporaryDirectory() as d:
            self.write(d, "{", json.dumps(STATUS))
            errors, _ = v.validate_dir(d)
            self.assertTrue(any("invalid JSON" in e for e in errors))
            self.assertEqual(v.main(["validate.py", d]), 1)

    def test_public_count_mismatch_is_only_a_warning(self):
        with tempfile.TemporaryDirectory() as d:
            s = dict(STATUS, outputs={"total": 5, "public": 3})
            self.write(d, json.dumps(FEED), json.dumps(s))
            errors, warnings = v.validate_dir(d)
            self.assertEqual(errors, [])
            self.assertEqual(len(warnings), 1)
            self.assertEqual(v.main(["validate.py", d]), 0)


try:
    import jsonschema
except ImportError:  # optional: CI installs it
    jsonschema = None


@unittest.skipIf(jsonschema is None, "jsonschema not installed")
class SchemasMatchValidator(unittest.TestCase):
    def check(self, schema_file, data_file):
        schema = json.loads((ROOT / "schema" / schema_file).read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator.check_schema(schema)
        data = json.loads((ROOT / data_file).read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator(
            schema, format_checker=jsonschema.FormatChecker()).validate(data)

    def test_feed_schema(self):
        self.check("feed.schema.json", "feed.json")

    def test_live_status_schema(self):
        self.check("live-status.schema.json", "live-status.json")

    def test_fixtures_match_schemas(self):
        for name, data in (("feed.schema.json", FEED), ("live-status.schema.json", STATUS)):
            schema = json.loads((ROOT / "schema" / name).read_text(encoding="utf-8"))
            jsonschema.Draft202012Validator(schema).validate(data)


if __name__ == "__main__":
    unittest.main()
