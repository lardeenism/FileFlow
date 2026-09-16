"""Integration tests for routes, file safety, and real concurrent processing."""

import io
import os
import shutil
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from fileflow import create_app
from fileflow import db
from fileflow.processing import synchronization_demo


class FileFlowTests(unittest.TestCase):
    def setUp(self):
        test_database_url = os.getenv("FILEFLOW_TEST_DB_URL", "").strip()
        production_database_url = os.getenv("SUPABASE_DB_URL", "").strip()
        if not test_database_url:
            self.skipTest("FILEFLOW_TEST_DB_URL is not configured")
        if test_database_url == production_database_url:
            self.fail("FILEFLOW_TEST_DB_URL must not match SUPABASE_DB_URL")
        root = Path(__file__).parent / '.runtime' / self._testMethodName
        if root.exists():
            shutil.rmtree(root)
        root.mkdir(parents=True)
        self.runtime_root = root
        self.app = create_app({
            "TESTING": True,
            "SUPABASE_DB_URL": test_database_url,
            "STORAGE_ROOT": str(root / "storage"),
        })
        self.client = self.app.test_client()

    def tearDown(self):
        manager = self.app.extensions["processing_manager"]
        if manager.coordinator_thread:
            manager.coordinator_thread.join(timeout=15)
        shutil.rmtree(self.runtime_root, ignore_errors=True)

    def wait_for_batch(self, timeout=15):
        manager = self.app.extensions["processing_manager"]
        deadline = time.time() + timeout
        while manager.snapshot()["active"] and time.time() < deadline:
            time.sleep(0.04)
        self.assertFalse(manager.snapshot()["active"], "processing batch did not finish")

    def test_all_pages_render(self):
        for path in ("/", "/files", "/queue", "/threads", "/history", "/logs", "/reports", "/settings", "/about"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)
            self.assertIn(b"FileFlow", response.data)
            if path != "/":
                self.assertIn(b"HOW FILEFLOW WORKS", response.data)

    def test_upload_limit_defaults_to_one_gigabyte_and_is_shown_consistently(self):
        self.assertEqual(self.app.config["MAX_UPLOAD_MB"], 1024)
        self.assertEqual(self.app.config["MAX_CONTENT_LENGTH"], 1024 * 1024 * 1024)
        files_page = self.client.get("/files")
        settings_page = self.client.get("/settings")
        self.assertIn(b"up to 1 GB per request", files_page.data)
        self.assertIn(b"1 GB request limit", settings_page.data)

    def test_upload_processing_thread_ids_and_duplicate_detection(self):
        payload = b"identical content for SHA-256 duplicate detection"
        response = self.client.post("/api/upload", data={
            "files": [(io.BytesIO(payload), "first.txt"), (io.BytesIO(payload), "second.txt")]
        }, content_type="multipart/form-data")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(len(response.get_json()["created"]), 2)

        started = self.client.post("/api/process/start")
        self.assertEqual(started.status_code, 202)
        self.wait_for_batch()

        with self.app.app_context():
            files = db.fetch_all("SELECT * FROM files ORDER BY id")
            joins = db.fetch_all("SELECT * FROM processing_logs WHERE event_type='join'")
        self.assertTrue(all(item["status"] == "completed" for item in files))
        self.assertTrue(all(item["thread_id"] for item in files))
        self.assertEqual(sum(item["is_duplicate"] for item in files), 1)
        self.assertTrue(any("worker join() completed" in item["message"] for item in joins))
        self.assertTrue(Path(files[0]["organized_path"]).is_file())
        self.assertTrue(Path(files[1]["organized_path"]).is_file())

    def test_reports_use_persisted_completed_file_metrics(self):
        first, second = b"report alpha", b"report beta beta"
        response = self.client.post("/api/upload", data={
            "files": [(io.BytesIO(first), "alpha.txt"), (io.BytesIO(second), "beta.txt")]
        }, content_type="multipart/form-data")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(self.client.post("/api/process/start").status_code, 202)
        self.wait_for_batch()

        response = self.client.get("/api/reports")
        self.assertEqual(response.status_code, 200)
        report = response.get_json()
        self.assertEqual(report["summary"]["total_files"], 2)
        self.assertEqual(report["summary"]["completed"], 2)
        self.assertEqual(report["summary"]["completed_bytes"], len(first) + len(second))
        self.assertEqual(sum(row["file_count"] for row in report["categories"]), 2)
        self.assertEqual(sum(row["task_count"] for row in report["workers"]), 2)
        self.assertIn("persisted runs", report["scope_note"])

    def test_workers_store_native_operating_system_thread_id(self):
        response = self.client.post("/api/upload", data={
            "files": (io.BytesIO(b"native id"), "native.txt")
        }, content_type="multipart/form-data")
        self.assertEqual(response.status_code, 201)
        with patch("fileflow.processing.threading.get_native_id", return_value=424242):
            self.assertEqual(self.client.post("/api/process/start").status_code, 202)
            self.wait_for_batch()
        with self.app.app_context():
            task = db.fetch_one("SELECT thread_id FROM tasks")
        self.assertEqual(task["thread_id"], 424242)

    def test_supabase_adapter_translates_parameters_and_returns_insert_id(self):
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = {"id": 73}
        with self.app.app_context():
            with patch("fileflow.db.get_db", return_value=connection):
                inserted = db.execute(
                    "INSERT INTO files (original_filename, stored_filename, source_path, created_at) VALUES (?,?,?,?)",
                    ("report.txt", "stored.txt", "safe/path", "2026-01-01T00:00:00+00:00"),
                )
        self.assertEqual(inserted, 73)
        query, params = cursor.execute.call_args.args
        self.assertIn("VALUES (%s,%s,%s,%s) RETURNING id", query)
        self.assertEqual(params[0], "report.txt")

    def test_can_run_one_pending_file_and_leave_the_other_queued(self):
        response = self.client.post("/api/upload", data={
            "files": [(io.BytesIO(b"first"), "first.txt"), (io.BytesIO(b"second"), "second.txt")]
        }, content_type="multipart/form-data")
        self.assertEqual(response.status_code, 201)
        tasks = response.get_json()["created"]

        started = self.client.post("/api/process/start", json={"task_ids": [tasks[0]["task_id"]]})
        self.assertEqual(started.status_code, 202)
        self.wait_for_batch()

        with self.app.app_context():
            rows = db.fetch_all("SELECT id,status FROM tasks ORDER BY id")
        self.assertEqual(rows[0]["status"], "completed")
        self.assertEqual(rows[1]["status"], "pending")

        status = self.client.get("/api/status").get_json()["processing"]
        self.assertEqual(status["summary"]["total"], 1)
        self.assertEqual(status["summary"]["completed"], 1)
        self.assertEqual(status["completion_order"][0]["filename"], "first.txt")
        self.assertIn("duration_seconds", status["completion_order"][0])
        self.assertNotIn("started_tick", status["workers"][0])
        self.assertEqual(sum(worker["status"] == "idle" for worker in status["workers"]), 4)

    def test_rejects_non_pending_task_selection(self):
        response = self.client.post("/api/upload", data={
            "files": (io.BytesIO(b"once"), "once.txt")
        }, content_type="multipart/form-data")
        task_id = response.get_json()["created"][0]["task_id"]
        self.assertEqual(self.client.post("/api/process/start", json={"task_ids": [task_id]}).status_code, 202)
        self.wait_for_batch()
        self.assertEqual(self.client.post("/api/process/start", json={"task_ids": [task_id]}).status_code, 409)

    def test_thread_monitor_has_real_queue_controls_without_demo_button(self):
        response = self.client.get("/threads")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'monitorPendingTasks', response.data)
        self.assertIn(b'completionOrder', response.data)
        self.assertIn(b'batchProgressBar', response.data)
        self.assertIn(b'batchEmpty', response.data)
        self.assertNotIn(b'id="monitorQueue"', response.data)
        self.assertNotIn(b'data-action="demo"', response.data)

    def test_concurrent_same_names_never_overwrite_each_other(self):
        response = self.client.post("/api/upload", data={
            "files": [(io.BytesIO(b"alpha"), "same.txt"), (io.BytesIO(b"beta"), "same.txt")]
        }, content_type="multipart/form-data")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(self.client.post("/api/process/start").status_code, 202)
        self.wait_for_batch()

        with self.app.app_context():
            files = db.fetch_all("SELECT organized_path FROM files ORDER BY id")
        destinations = [Path(item["organized_path"]) for item in files]
        self.assertEqual(len(set(destinations)), 2)
        self.assertEqual({path.read_bytes() for path in destinations}, {b"alpha", b"beta"})

    def test_deleted_batch_records_clear_stale_worker_telemetry(self):
        response = self.client.post("/api/upload", data={
            "files": (io.BytesIO(b"temporary"), "temporary.txt")
        }, content_type="multipart/form-data")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(self.client.post("/api/process/start").status_code, 202)
        self.wait_for_batch()

        with self.app.app_context():
            db.execute("DELETE FROM tasks")
            db.execute("DELETE FROM files")
        processing = self.client.get("/api/status").get_json()["processing"]
        self.assertEqual(processing["message"], "Ready")
        self.assertEqual(processing["summary"]["total"], 0)
        self.assertTrue(all(worker["status"] == "idle" for worker in processing["workers"]))

    def test_path_traversal_is_sanitized(self):
        response = self.client.post("/api/upload", data={
            "files": (io.BytesIO(b"safe"), "../../outside.txt")
        }, content_type="multipart/form-data")
        self.assertEqual(response.status_code, 201)
        created = response.get_json()["created"][0]
        self.assertEqual(created["filename"], "outside.txt")
        with self.app.app_context():
            row = db.fetch_one("SELECT source_path FROM files WHERE id=?", (created["file_id"],))
        source = Path(row["source_path"]).resolve()
        self.assertIn(Path(self.app.config["STORAGE_ROOT"]).resolve(), source.parents)

    def test_executable_upload_is_rejected(self):
        response = self.client.post("/api/upload", data={
            "files": (io.BytesIO(b"not executable"), "dangerous.exe")
        }, content_type="multipart/form-data")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.get_json()["ok"])

    def test_safe_vs_unsafe_uses_real_threads_and_lock(self):
        result = synchronization_demo(thread_count=5, increments=40)
        self.assertEqual(result["expected"], 200)
        self.assertLess(result["unsafe_actual"], result["expected"])
        self.assertEqual(result["safe_actual"], result["expected"])
        self.assertEqual(result["safe_lost"], 0)


if __name__ == "__main__":
    unittest.main()
