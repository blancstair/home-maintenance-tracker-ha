import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import zipfile
import re
from datetime import date, timedelta
from pathlib import Path


TEST_DIR = tempfile.mkdtemp(prefix="hmt-tests-")
os.environ["HMT_DATA_DIR"] = TEST_DIR
os.environ["HMT_DISABLE_NOTIFICATION_THREAD"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as application  # noqa: E402
from scheduling import enrich_task  # noqa: E402


class TrackerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = application.app.test_client()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TEST_DIR, ignore_errors=True)

    def test_01_sample_data_is_large_and_generic(self):
        data = self.client.get("/api/bootstrap").get_json()
        self.assertGreaterEqual(len(data["assets"]), 70)
        self.assertGreaterEqual(len(data["tasks"]), 20)
        for item in data["assets"]:
            self.assertFalse({"owner", "email", "phone", "address"} & set(item["attributes"]))

    def test_02_unlimited_tree_and_cycle_prevention(self):
        parent = self.client.post("/api/assets", json={"name": "Test Parent", "attributes": {}}).get_json()
        child = self.client.post("/api/assets", json={"name": "Test Child", "parent_id": parent["id"], "attributes": {}}).get_json()
        grandchild = self.client.post("/api/assets", json={"name": "Test Grandchild", "parent_id": child["id"], "attributes": {}}).get_json()
        response = self.client.post(f"/api/assets/{parent['id']}/move", json={"parent_id": grandchild["id"]})
        self.assertEqual(response.status_code, 400)

    def test_03_archive_requires_child_decisions(self):
        parent = self.client.post("/api/assets", json={"name": "Archive Parent"}).get_json()
        child = self.client.post("/api/assets", json={"name": "Archive Child", "parent_id": parent["id"]}).get_json()
        response = self.client.post(f"/api/assets/{parent['id']}/archive", json={"reason": "test"})
        self.assertEqual(response.status_code, 400)
        response = self.client.post(f"/api/assets/{parent['id']}/archive", json={"reason": "test", "children": {child["id"]: {"action": "move", "parent_id": None}}})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.client.get(f"/api/assets/{child['id']}").get_json()["archived"])

    def test_04_replacement_links_records_and_copies_plan(self):
        old = self.client.post("/api/assets", json={"name": "Old Unit", "attributes": {"model": "OLD"}}).get_json()
        task = self.client.post("/api/tasks", json={
            "asset_id": old["id"], "title": "Inspect unit", "schedule_type": "calendar",
            "calendar_value": 6, "calendar_unit": "months", "start_date": date.today().isoformat(),
        }).get_json()
        response = self.client.post(f"/api/assets/{old['id']}/replace", json={
            "name": "New Unit", "attributes": {"model": "NEW"}, "copy_task_ids": [task["id"]], "move_child_ids": [],
        })
        self.assertEqual(response.status_code, 201)
        new_id = response.get_json()["id"]
        old_detail = self.client.get(f"/api/assets/{old['id']}").get_json()
        new_detail = self.client.get(f"/api/assets/{new_id}").get_json()
        self.assertEqual(old_detail["replaced_by"]["id"], new_id)
        self.assertEqual(new_detail["replaced_from"]["id"], old["id"])
        self.assertEqual(len(new_detail["tasks"]), 1)

    def test_05_calendar_red_threshold_is_one_point_five_intervals(self):
        with application.connect() as db:
            raw = {
                "id": "x", "title": "Weekly", "schedule_type": "calendar", "calendar_value": 1,
                "calendar_unit": "weeks", "last_completed_date": "2026-01-01", "start_date": "2026-01-01",
                "meter_id": None, "meter_interval": None, "combination_rule": None, "snoozed_until": "2026-02-01",
            }
            due = enrich_task(db, raw, today=date(2026, 1, 11))
            red = enrich_task(db, raw, today=date(2026, 1, 12))
        self.assertEqual(due["calendar_due"], "2026-01-08")
        self.assertEqual(due["calendar_red"], "2026-01-12")
        self.assertFalse(due["red"])
        self.assertTrue(red["red"])
        self.assertFalse(red["snoozed"])

    def test_06_higher_authority_resets_periodicity(self):
        asset = self.client.post("/api/assets", json={"name": "Maintained Unit"}).get_json()
        replacement = self.client.post("/api/assets", json={"name": "Replacement Component", "parent_id": asset["id"]}).get_json()
        task = self.client.post("/api/tasks", json={
            "asset_id": asset["id"], "title": "Inspect component", "schedule_type": "calendar",
            "calendar_value": 1, "calendar_unit": "months", "start_date": "2026-01-01",
        }).get_json()
        result = self.client.post(f"/api/tasks/{task['id']}/complete", json={
            "completion_date": "2026-08-29", "outcome": "higher_authority",
            "replacement_asset_id": replacement["id"], "remark_text": "Component replaced instead of inspected.",
        })
        self.assertEqual(result.status_code, 201)
        self.assertTrue(result.get_json()["reset_periodicity"])
        task_after = self.client.get(f"/api/tasks/{task['id']}").get_json()
        self.assertEqual(task_after["last_completed_date"], "2026-08-29")
        self.assertEqual(task_after["calendar_due"], "2026-09-29")
        self.assertEqual(task_after["completions"][0]["outcome"], "higher_authority")

    def test_07_attachment_round_trip(self):
        asset = self.client.post("/api/assets", json={"name": "Documented Unit"}).get_json()
        upload = self.client.post("/api/attachments", data={
            "owner_type": "asset", "owner_id": asset["id"], "category": "manual",
            "file": (io.BytesIO(b"fictional manual"), "manual.txt"),
        }, content_type="multipart/form-data")
        self.assertEqual(upload.status_code, 201)
        attachment = upload.get_json()
        download = self.client.get(f"/api/attachments/{attachment['id']}")
        self.assertEqual(download.data, b"fictional manual")
        download.close()
        self.assertEqual(self.client.delete(f"/api/attachments/{attachment['id']}").status_code, 200)

    def test_07b_backdated_meter_completion_preserves_running_total(self):
        asset = self.client.post("/api/assets", json={"name": "Meter History Unit"}).get_json()
        meter = self.client.post("/api/meters", json={"asset_id": asset["id"], "name": "Runtime", "kind": "runtime", "unit": "hours"}).get_json()
        self.client.post("/api/meters/readings", json={"readings": [
            {"meter_id": meter["id"], "reading": 100, "recorded_at": "2026-01-01T12:00:00+00:00"},
            {"meter_id": meter["id"], "reading": 200, "recorded_at": "2026-08-01T12:00:00+00:00"},
        ]})
        task = self.client.post("/api/tasks", json={
            "asset_id": asset["id"], "title": "Runtime service", "schedule_type": "meter",
            "meter_id": meter["id"], "meter_interval": 50, "start_date": "2026-01-01",
        }).get_json()
        response = self.client.post(f"/api/tasks/{task['id']}/complete", json={
            "completion_date": "2026-04-01", "outcome": "completed", "meter_reading": 150,
            "remark_text": "Backfilled prior service.",
        })
        self.assertEqual(response.status_code, 201, response.get_json())
        updated = self.client.get(f"/api/tasks/{task['id']}").get_json()
        self.assertEqual(updated["meter_due"], 200)

    def test_07c_one_time_completion_closes_task(self):
        task = self.client.post("/api/tasks", json={
            "title": "One-time demonstration", "schedule_type": "one_time", "start_date": "2026-08-29",
        }).get_json()
        self.client.post(f"/api/tasks/{task['id']}/complete", json={
            "completion_date": "2026-08-29", "outcome": "completed", "remark_text": "Done.",
        })
        self.assertFalse(self.client.get(f"/api/tasks/{task['id']}").get_json()["active"])

    def test_07d_pattern_completion_remains_calendar_anchored(self):
        task = self.client.post("/api/tasks", json={
            "title": "Annual patterned task", "schedule_type": "pattern", "calendar_value": 1,
            "calendar_unit": "years", "start_date": "2026-10-01", "fixed_month": 10, "fixed_day": 1,
        }).get_json()
        self.client.post(f"/api/tasks/{task['id']}/complete", json={
            "completion_date": "2026-09-15", "outcome": "completed", "remark_text": "Completed early.",
        })
        updated = self.client.get(f"/api/tasks/{task['id']}").get_json()
        self.assertEqual(updated["calendar_due"], "2027-10-01")

    def test_08_sample_removal_preserves_user_data(self):
        user_asset = self.client.post("/api/assets", json={"name": "Keep Me"}).get_json()
        response = self.client.post("/api/sample-data/remove")
        self.assertEqual(response.status_code, 200)
        bootstrap = self.client.get("/api/bootstrap").get_json()
        self.assertTrue(any(item["id"] == user_asset["id"] for item in bootstrap["assets"]))
        self.assertFalse(any(item["is_sample"] for item in bootstrap["assets"]))
        self.assertEqual(self.client.post("/api/sample-data/restore").status_code, 200)

    def test_09_export_contains_database_manifest_and_attachment_folder(self):
        response = self.client.get("/api/export")
        self.assertEqual(response.status_code, 200)
        export_bytes = response.data
        response.close()
        with zipfile.ZipFile(io.BytesIO(export_bytes)) as archive:
            self.assertIn("manifest.json", archive.namelist())
            self.assertIn("database/home_maintenance.sqlite3", archive.namelist())
            manifest = json.loads(archive.read("manifest.json"))
            self.assertEqual(manifest["application"], "Home Maintenance Tracker")

    def test_09b_export_can_be_imported(self):
        exported = self.client.get("/api/export")
        export_bytes = exported.data
        exported.close()
        marker = self.client.post("/api/assets", json={"name": "Created After Export"}).get_json()["id"]
        imported = self.client.post("/api/import", data={"file": (io.BytesIO(export_bytes), "tracker-export.zip")}, content_type="multipart/form-data")
        self.assertEqual(imported.status_code, 200, imported.get_json())
        self.assertEqual(self.client.get(f"/api/assets/{marker}").status_code, 404)

    def test_10_all_reports_respond(self):
        for name in ("upcoming", "overdue", "history", "archived", "warranties", "costs", "parts", "meters"):
            response = self.client.get(f"/api/reports/{name}")
            self.assertEqual(response.status_code, 200, name)
            self.assertIsInstance(response.get_json(), list)

    def test_11_meter_lifecycle_standard_units_and_qr(self):
        asset = self.client.post("/api/assets", json={"name": "Meter Lifecycle Unit"}).get_json()
        invalid = self.client.post("/api/meters", json={
            "asset_id": asset["id"], "name": "Invalid", "kind": "runtime", "unit": "fortnights",
        })
        self.assertEqual(invalid.status_code, 400)
        meter_response = self.client.post("/api/meters", json={
            "asset_id": asset["id"], "name": "Hours", "kind": "runtime", "unit": "hours",
            "initial_reading": 10, "initial_recorded_at": "2026-08-30T12:00:00+00:00",
        })
        self.assertEqual(meter_response.status_code, 201, meter_response.get_json())
        meter = meter_response.get_json()
        listed = self.client.get("/api/meters").get_json()
        created = next(item for item in listed if item["id"] == meter["id"])
        self.assertEqual(created["reading_count"], 1)
        self.assertEqual(created["latest"]["reading"], 10)
        qr = self.client.get(f"/api/meters/{meter['id']}/qr?url=https%3A%2F%2Fexample.test%2Fmeter")
        self.assertEqual(qr.status_code, 200)
        self.assertEqual(qr.mimetype, "image/svg+xml")
        self.assertEqual(self.client.post(f"/api/meters/{meter['id']}/archive").status_code, 200)
        self.assertFalse(any(item["id"] == meter["id"] for item in self.client.get("/api/meters").get_json()))
        archived = self.client.get("/api/meters?include_archived=1").get_json()
        self.assertTrue(next(item for item in archived if item["id"] == meter["id"])["archived"])
        self.assertEqual(self.client.post(f"/api/meters/{meter['id']}/restore").status_code, 200)

    def test_12_active_task_blocks_meter_archive_and_unused_meter_deletes(self):
        asset = self.client.post("/api/assets", json={"name": "Meter Task Unit"}).get_json()
        meter = self.client.post("/api/meters", json={
            "asset_id": asset["id"], "name": "Odometer", "kind": "mileage", "unit": "miles",
        }).get_json()
        task = self.client.post("/api/tasks", json={
            "asset_id": asset["id"], "title": "Meter Task", "schedule_type": "meter",
            "meter_id": meter["id"], "meter_interval": 5000, "start_date": "2026-08-30",
        }).get_json()
        self.assertEqual(self.client.post(f"/api/meters/{meter['id']}/archive").status_code, 409)
        self.client.post(f"/api/tasks/{task['id']}/cancel", json={"reason": "Test cancellation"})
        self.assertEqual(self.client.post(f"/api/meters/{meter['id']}/archive").status_code, 200)
        unused = self.client.post("/api/meters", json={
            "asset_id": asset["id"], "name": "Starts", "kind": "cycles", "unit": "starts",
        }).get_json()
        self.assertEqual(self.client.delete(f"/api/meters/{unused['id']}").status_code, 200)

    def test_13_modal_cancel_controls_and_help_coverage(self):
        static_dir = Path(__file__).resolve().parents[1] / "static"
        html = (static_dir / "index.html").read_text()
        app_js = (static_dir / "app.js").read_text()
        help_js = (static_dir / "help.js").read_text()
        self.assertIn('id="modalClose"', html)
        self.assertIn('id="modalCancel"', html)
        self.assertNotIn('<form method="dialog" class="modal-card" id="modalForm">', html)
        entries = set(re.findall(r"^  '([^']+)': \{title:", help_js, re.MULTILINE))
        used = set(re.findall(r"helpButton\('([^']+)'\)|helpId:'([^']+)'|data-help=\"([^\"]+)\"", app_js + html))
        used_ids = {value for match in used for value in match if value}
        self.assertFalse(used_ids - entries, f"Missing Help entries: {used_ids - entries}")
        self.assertIn("screen-dashboard", entries)
        self.assertIn("meters-manage", entries)

    def test_14_companion_qr_and_tablet_sidebar_regressions(self):
        static_dir = Path(__file__).resolve().parents[1] / "static"
        html = (static_dir / "index.html").read_text()
        app_js = (static_dir / "app.js").read_text()
        help_js = (static_dir / "help.js").read_text()
        self.assertIn("homeassistant://navigate", app_js)
        self.assertNotIn("server=default", app_js)
        self.assertIn("companionNavigateUrl(appInfo.panel_path,'meter',meterId)", app_js)
        self.assertIn("companionNavigateUrl(appInfo.panel_path,'asset',assetId)", app_js)
        self.assertNotIn("`${location.origin}${appInfo.panel_path}`", app_js)
        self.assertNotIn("addEventListener('pointerup'", app_js)
        self.assertIn("event.stopPropagation()", app_js)
        self.assertIn("Download QR Code", app_js)
        self.assertIn("static/app.js?v=0.2.2", html)
        self.assertIn("static/styles.css?v=0.2.2", html)
        self.assertIn('aria-expanded="true"', html)
        self.assertIn("regenerate previously printed labels", help_js)

    def test_15_qr_download_and_cache_headers(self):
        asset = self.client.post("/api/assets", json={"name": "Download Test Asset"}).get_json()
        meter = self.client.post("/api/meters", json={
            "asset_id": asset["id"], "name": "Download Test Meter", "kind": "runtime", "unit": "hours",
        }).get_json()
        target = "homeassistant://navigate/hassio/ingress/test?meter=example"
        asset_qr = self.client.get(f"/api/assets/{asset['id']}/qr", query_string={"url": target, "download": "1"})
        meter_qr = self.client.get(f"/api/meters/{meter['id']}/qr", query_string={"url": target, "download": "1"})
        self.assertEqual(asset_qr.status_code, 200)
        self.assertEqual(meter_qr.status_code, 200)
        self.assertIn("attachment", asset_qr.headers["Content-Disposition"])
        self.assertIn("Download_Test_Asset-qr.svg", asset_qr.headers["Content-Disposition"])
        self.assertIn("Download_Test_Meter-qr.svg", meter_qr.headers["Content-Disposition"])
        index = self.client.get("/")
        script = self.client.get("/static/app.js")
        self.assertIn("no-store", index.headers["Cache-Control"])
        self.assertIn("no-store", script.headers["Cache-Control"])
        index.close()
        script.close()


if __name__ == "__main__":
    unittest.main()
