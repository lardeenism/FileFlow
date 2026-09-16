"""Real concurrent file-processing engine used by the web application."""

import queue
import random
import threading
import time
import traceback
from pathlib import Path

from . import db
from .file_service import metadata_for, move_to_organized, sha256_file


class ProcessingManager:
    """Owns batch queues, worker threads, and synchronized shared state."""

    def __init__(self, app):
        self.app = app
        self.state_lock = threading.RLock()
        self.organization_lock = threading.Lock()
        self.task_queue = None
        self.worker_threads = []
        self.coordinator_thread = None
        self.workers = {}
        self.batch_active = False
        self.batch_mode = None
        self.batch_message = "Ready"
        self.completed_in_batch = 0
        self.failed_in_batch = 0
        self.batch_task_ids = []
        self.completion_order = []

    def _log(self, level, event_type, message, worker_id=None, thread_id=None, file_id=None):
        with self.app.app_context():
            db.add_log(level, event_type, message, worker_id, thread_id, file_id)

    def snapshot(self):
        with self.state_lock:
            configured = len(self.workers) if self.workers else self._configured_worker_count()
            workers = []
            for worker_id in range(1, configured + 1):
                worker = dict(
                    self.workers.get(
                        worker_id,
                        {
                            "worker_id": worker_id,
                            "thread_id": None,
                            "current_file": None,
                            "status": "idle",
                            "progress": 0,
                            "start_time": None,
                            "completion_time": None,
                            "duration_seconds": 0,
                            "started_tick": None,
                            "processed": 0,
                        },
                    )
                )
                worker.pop("started_tick", None)
                workers.append(worker)
            return {
                "active": self.batch_active,
                "mode": self.batch_mode,
                "message": self.batch_message,
                "queue_size": self.task_queue.qsize() if self.task_queue else 0,
                "completed_in_batch": self.completed_in_batch,
                "failed_in_batch": self.failed_in_batch,
                "batch_task_ids": list(self.batch_task_ids),
                "completion_order": [dict(item) for item in self.completion_order],
                "workers": workers,
            }

    def _configured_worker_count(self):
        with self.app.app_context():
            row = db.fetch_one("SELECT value FROM settings WHERE `key` = 'worker_count'")
        try:
            return min(12, max(1, int(row["value"] if row else 5)))
        except (TypeError, ValueError):
            return 5

    def reset_completed_state(self):
        """Clear stale telemetry only when no processing batch is active."""
        with self.state_lock:
            if self.batch_active:
                return False
            self.task_queue = None
            self.worker_threads = []
            self.coordinator_thread = None
            self.workers = {}
            self.batch_mode = None
            self.batch_message = "Ready"
            self.completed_in_batch = 0
            self.failed_in_batch = 0
            self.batch_task_ids = []
            self.completion_order = []
            return True

    def start_batch(self, task_ids, worker_count=None, demo=False):
        """Start an asynchronous batch; the coordinator uses Queue.join and Thread.join."""
        with self.state_lock:
            if self.batch_active:
                return False, "A processing batch is already running."
            task_ids = list(dict.fromkeys(int(task_id) for task_id in task_ids))
            if not task_ids:
                return False, "There are no pending tasks to process."
            count = min(12, max(1, int(worker_count or self._configured_worker_count())))
            self.task_queue = queue.Queue()
            for task_id in task_ids:
                self.task_queue.put(task_id)
            for _ in range(count):
                self.task_queue.put(None)

            self.batch_active = True
            self.batch_mode = "demo" if demo else "standard"
            self.batch_message = f"Processing {len(task_ids)} queued files"
            self.completed_in_batch = 0
            self.failed_in_batch = 0
            self.batch_task_ids = list(task_ids)
            self.completion_order = []
            self.workers = {
                number: {
                    "worker_id": number,
                    "thread_id": None,
                    "current_file": None,
                    "status": "starting",
                    "progress": 0,
                    "start_time": None,
                    "completion_time": None,
                    "duration_seconds": 0,
                    "started_tick": None,
                    "processed": 0,
                }
                for number in range(1, count + 1)
            }

            self.worker_threads = [
                threading.Thread(
                    target=self._worker_loop,
                    args=(number, demo),
                    name=f"FileFlow-Worker-{number:02d}",
                    daemon=True,
                )
                for number in range(1, count + 1)
            ]
            for thread in self.worker_threads:
                thread.start()
            self.coordinator_thread = threading.Thread(
                target=self._wait_for_batch,
                name="FileFlow-Batch-Coordinator",
                daemon=True,
            )
            self.coordinator_thread.start()

        self._log("info", "queue", f"Queued {len(task_ids)} files for {count} real worker threads.")
        return True, f"Started {count} workers for {len(task_ids)} files."

    def _wait_for_batch(self):
        """Controller waits for all queue work, then joins every worker thread."""
        self._log("info", "join", "Coordinator called Queue.join(); waiting for all tasks.")
        self.task_queue.join()
        for thread in self.worker_threads:
            thread.join()
        try:
            self._log("success", "join", "ALL FILES PROCESSED! Queue.join() and worker join() completed.")
        finally:
            # Publish the inactive state only after the final join event is observable.
            with self.state_lock:
                self.batch_active = False
                self.batch_message = "ALL FILES PROCESSED!"

    def _set_worker(self, worker_id, **values):
        with self.state_lock:
            self.workers[worker_id].update(values)

    def _update_progress(self, worker_id, task_id, file_id, progress):
        progress = min(100, max(0, int(progress)))
        self._set_worker(worker_id, progress=progress)
        with self.app.app_context():
            db.execute("UPDATE tasks SET progress = ? WHERE id = ?", (progress, task_id))
            db.execute("UPDATE files SET progress = ? WHERE id = ?", (progress, file_id))

    def _worker_loop(self, worker_id, demo):
        # This maps to the operating-system thread; get_ident() is only a
        # Python runtime identifier and may be recycled.
        thread_id = threading.get_native_id()
        self._set_worker(worker_id, thread_id=thread_id, status="idle")
        self._log("info", "thread", f"Worker {worker_id:02d} started.", worker_id, thread_id)

        while True:
            task_id = self.task_queue.get()
            try:
                if task_id is None:
                    with self.state_lock:
                        unused = self.workers[worker_id]["status"] in {"idle", "starting"}
                    if unused:
                        self._set_worker(worker_id, status="idle", progress=0)
                    return
                self._process_task(task_id, worker_id, thread_id, demo)
            except Exception as error:  # keep a worker alive if one file is bad
                self._mark_failed(task_id, worker_id, thread_id, error)
            finally:
                self.task_queue.task_done()

    def _process_task(self, task_id, worker_id, thread_id, demo):
        with self.app.app_context():
            task = db.fetch_one(
                """SELECT t.*, f.original_filename, f.source_path, f.id AS actual_file_id
                   FROM tasks t JOIN files f ON f.id = t.file_id WHERE t.id = ?""",
                (task_id,),
            )
            if not task:
                raise RuntimeError(f"Task {task_id} no longer exists.")
            file_id = task["actual_file_id"]
            source = Path(task["source_path"])
            if not source.is_file():
                raise FileNotFoundError("The staged source file is missing.")

            started = db.utcnow()
            started_tick = time.perf_counter()
            self._set_worker(
                worker_id,
                current_file=task["original_filename"],
                status="running",
                progress=5,
                start_time=started,
                completion_time=None,
                duration_seconds=0,
                started_tick=started_tick,
            )
            db.execute(
                "UPDATE tasks SET status='processing', progress=5, worker_id=?, thread_id=?, started_at=? WHERE id=?",
                (worker_id, thread_id, started, task_id),
            )
            db.execute(
                "UPDATE files SET status='processing', progress=5, worker_id=?, thread_id=?, started_at=? WHERE id=?",
                (worker_id, thread_id, started, file_id),
            )
            db.add_log(
                "info", "processing", f"Started {task['original_filename']}",
                worker_id, thread_id, file_id,
            )

            delay = random.uniform(1, 3) / 3 if demo else 0
            if delay:
                time.sleep(delay)
            details = metadata_for(source, task["original_filename"])
            self._update_progress(worker_id, task_id, file_id, 15)
            file_hash = sha256_file(
                source, lambda value: self._update_progress(worker_id, task_id, file_id, value)
            )
            if delay:
                time.sleep(delay)
            self._update_progress(worker_id, task_id, file_id, 72)

            db.add_log("info", "lock", f"Worker {worker_id:02d} waiting for metadata Lock.", worker_id, thread_id, file_id)
            with self.organization_lock:
                duplicate = db.fetch_one(
                    """SELECT id, original_filename FROM files
                       WHERE sha256 = ? AND id != ? AND status IN ('processing','completed')
                       AND is_duplicate = 0 ORDER BY id LIMIT 1""",
                    (file_hash, file_id),
                )
                category = "Duplicates" if duplicate else details["category"]
                db.execute(
                    """UPDATE files SET file_type=?, size=?, category=?, sha256=?,
                       is_duplicate=?, duplicate_of=? WHERE id=?""",
                    (
                        details["file_type"], details["size"], details["category"], file_hash,
                        1 if duplicate else 0, duplicate["id"] if duplicate else None,
                        file_id,
                    ),
                )
            db.add_log("success", "lock", f"Worker {worker_id:02d} released metadata Lock.", worker_id, thread_id, file_id)

            # Slow filesystem I/O intentionally happens outside the synchronization Lock.
            destination = move_to_organized(
                source, self.app.config["STORAGE_ROOT"], category, task["original_filename"]
            )
            completed = db.utcnow()
            duration_seconds = round(time.perf_counter() - started_tick, 3)
            db.execute(
                """UPDATE files SET organized_path=?, status='completed', progress=100,
                   completed_at=?, error=NULL WHERE id=?""",
                (str(destination), completed, file_id),
            )
            db.execute(
                "UPDATE tasks SET status='completed', progress=100, completed_at=?, error=NULL WHERE id=?",
                (completed, task_id),
            )

            if delay:
                time.sleep(delay)
            with self.state_lock:
                self.completed_in_batch += 1
                processed = self.workers[worker_id]["processed"] + 1
                self.completion_order.append({
                    "rank": len(self.completion_order) + 1,
                    "task_id": task_id,
                    "file_id": file_id,
                    "filename": task["original_filename"],
                    "worker_id": worker_id,
                    "thread_id": thread_id,
                    "status": "completed",
                    "completed_at": completed,
                    "duration_seconds": duration_seconds,
                })
            self._set_worker(
                worker_id, status="completed", progress=100,
                completion_time=completed, duration_seconds=duration_seconds, processed=processed,
            )
            label = "Duplicate detected" if duplicate else f"Organized into {details['category']}"
            db.add_log(
                "success", "completed", f"{label}: {task['original_filename']} in {duration_seconds:.3f}s",
                worker_id, thread_id, file_id,
            )

    def _mark_failed(self, task_id, worker_id, thread_id, error):
        message = str(error)[:500] or error.__class__.__name__
        completed = db.utcnow()
        with self.state_lock:
            started_tick = self.workers[worker_id].get("started_tick")
        duration_seconds = round(time.perf_counter() - started_tick, 3) if started_tick else 0
        self._set_worker(worker_id, status="failed", completion_time=completed, duration_seconds=duration_seconds)
        with self.app.app_context():
            task = db.fetch_one(
                """SELECT t.file_id, f.original_filename FROM tasks t
                   JOIN files f ON f.id=t.file_id WHERE t.id = ?""",
                (task_id,),
            )
            if task:
                db.execute(
                    "UPDATE tasks SET status='failed', error=?, completed_at=? WHERE id=?",
                    (message, completed, task_id),
                )
                db.execute(
                    "UPDATE files SET status='failed', error=?, completed_at=? WHERE id=?",
                    (message, completed, task["file_id"]),
                )
                db.add_log("error", "failed", message, worker_id, thread_id, task["file_id"])
        with self.state_lock:
            self.failed_in_batch += 1
            self.completion_order.append({
                "rank": len(self.completion_order) + 1,
                "task_id": task_id,
                "file_id": task["file_id"] if task else None,
                "filename": task["original_filename"] if task else f"Task #{task_id}",
                "worker_id": worker_id,
                "thread_id": thread_id,
                "status": "failed",
                "completed_at": completed,
                "duration_seconds": duration_seconds,
            })
        self.app.logger.error("FileFlow worker error: %s\n%s", message, traceback.format_exc())


def synchronization_demo(thread_count=5, increments=100):
    """Run deterministic unsafe and safe shared-counter experiments with real threads."""
    unsafe = {"value": 0}
    barrier_read = threading.Barrier(thread_count)
    barrier_write = threading.Barrier(thread_count)

    def unsafe_increment():
        for _ in range(increments):
            snapshot = unsafe["value"]
            barrier_read.wait()
            unsafe["value"] = snapshot + 1
            barrier_write.wait()

    unsafe_threads = [threading.Thread(target=unsafe_increment) for _ in range(thread_count)]
    for thread in unsafe_threads:
        thread.start()
    for thread in unsafe_threads:
        thread.join()

    safe = {"value": 0}
    lock = threading.Lock()

    def safe_increment():
        for _ in range(increments):
            with lock:
                safe["value"] += 1

    safe_threads = [threading.Thread(target=safe_increment) for _ in range(thread_count)]
    for thread in safe_threads:
        thread.start()
    for thread in safe_threads:
        thread.join()

    expected = thread_count * increments
    return {
        "expected": expected,
        "unsafe_actual": unsafe["value"],
        "unsafe_lost": expected - unsafe["value"],
        "safe_actual": safe["value"],
        "safe_lost": expected - safe["value"],
        "thread_count": thread_count,
        "increments_per_thread": increments,
    }
