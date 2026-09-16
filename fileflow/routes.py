"""Flask presentation and JSON API routes for FileFlow."""

from datetime import datetime
from pathlib import Path

from flask import Blueprint, current_app, jsonify, render_template, request, send_file

from . import db
from .file_service import FileValidationError, confined_path, metadata_for, save_upload, unique_name
from .processing import synchronization_demo


bp = Blueprint("main", __name__)
PAGE_TITLES = {
    "dashboard": "Dashboard", "files": "File Library", "queue": "Processing Queue",
    "threads": "Thread Monitor", "history": "Processing History",
    "logs": "System Logs", "settings": "Settings",
    "reports": "Reports & Analytics", "about": "About & Concurrency",
}


def manager():
    return current_app.extensions["processing_manager"]


@bp.route("/")
def landing():
    return render_template("landing.html")


@bp.route("/dashboard")
def dashboard():
    return render_template("page.html", page="dashboard", page_title=PAGE_TITLES["dashboard"])


@bp.route("/<page>")
def page(page):
    if page not in PAGE_TITLES or page == "dashboard":
        return render_template("404.html"), 404
    return render_template("page.html", page=page, page_title=PAGE_TITLES[page])


@bp.get("/api/status")
def api_status():
    counts = db.fetch_one(
        """SELECT COUNT(*) AS total,
        SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) AS processed,
        SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END) AS pending,
        SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed,
        SUM(CASE WHEN is_duplicate=1 THEN 1 ELSE 0 END) AS duplicates FROM files"""
    )
    snap = manager().snapshot()
    batch_tasks = []
    if snap["batch_task_ids"]:
        placeholders = ",".join("?" for _ in snap["batch_task_ids"])
        batch_tasks = db.fetch_all(
            f"SELECT status, progress FROM tasks WHERE id IN ({placeholders})",
            tuple(snap["batch_task_ids"]),
        )
    if snap["batch_task_ids"] and not batch_tasks and not snap["active"]:
        manager().reset_completed_state()
        snap = manager().snapshot()
    batch_total = len(batch_tasks)
    snap["summary"] = {
        "total": batch_total,
        "completed": sum(task["status"] == "completed" for task in batch_tasks),
        "running": sum(task["status"] == "processing" for task in batch_tasks),
        "pending": sum(task["status"] == "pending" for task in batch_tasks),
        "failed": sum(task["status"] == "failed" for task in batch_tasks),
        "progress": round(sum(int(task["progress"] or 0) for task in batch_tasks) / batch_total)
        if batch_total else 0,
    }
    counts = {key: int(value or 0) for key, value in counts.items()}
    counts["active_workers"] = sum(w["status"] == "running" for w in snap["workers"])
    logs = db.fetch_all("SELECT * FROM processing_logs ORDER BY id DESC LIMIT 12")
    tasks = db.fetch_all(
        """SELECT t.*, f.original_filename FROM tasks t JOIN files f ON f.id=t.file_id
        ORDER BY t.id DESC LIMIT 12"""
    )
    return jsonify(stats=counts, processing=snap, logs=logs, tasks=tasks)


@bp.get("/api/files")
def api_files():
    rows = db.fetch_all(
        """SELECT id, original_filename, file_type, size, category,
        substr(sha256,1,16) AS short_hash, is_duplicate, duplicate_of, worker_id,
        thread_id, status, progress, created_at, completed_at, error
        FROM files ORDER BY
        CASE WHEN is_duplicate=1 THEN 9
             WHEN category='Images' THEN 1 WHEN category='Documents' THEN 2
             WHEN category='Spreadsheets' THEN 3 WHEN category='Presentations' THEN 4
             WHEN category='Videos' THEN 5 WHEN category='Audio' THEN 6
             WHEN category='Archives' THEN 7 ELSE 8 END,
        original_filename COLLATE NOCASE"""
    )
    return jsonify(files=rows)


@bp.get("/api/tasks")
def api_tasks():
    rows = db.fetch_all(
        """SELECT t.*, f.original_filename, f.category, f.size FROM tasks t
        JOIN files f ON f.id=t.file_id ORDER BY t.id DESC"""
    )
    return jsonify(tasks=rows)


@bp.get("/api/history")
def api_history():
    rows = db.fetch_all(
        """SELECT t.*, f.original_filename, f.category, f.size, f.is_duplicate,
        substr(f.sha256,1,16) AS short_hash FROM tasks t JOIN files f ON f.id=t.file_id
        WHERE t.status IN ('completed','failed') ORDER BY t.completed_at DESC"""
    )
    return jsonify(history=rows)


@bp.get("/api/reports")
def api_reports():
    """Return historical aggregates supported by persisted task and file data."""
    summary = db.fetch_one(
        """SELECT COUNT(*) AS total_files,
        SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) AS completed,
        SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed,
        SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END) AS pending,
        SUM(CASE WHEN status='processing' THEN 1 ELSE 0 END) AS processing,
        SUM(CASE WHEN status='completed' THEN size ELSE 0 END) AS completed_bytes,
        SUM(CASE WHEN is_duplicate=1 THEN 1 ELSE 0 END) AS duplicates
        FROM files"""
    )
    categories = db.fetch_all(
        """SELECT category, COUNT(*) AS file_count, SUM(size) AS total_bytes
        FROM files WHERE status='completed'
        GROUP BY category ORDER BY total_bytes DESC, category"""
    )
    workers = db.fetch_all(
        """SELECT t.worker_id, COUNT(*) AS task_count, SUM(f.size) AS total_bytes
        FROM tasks t JOIN files f ON f.id=t.file_id
        WHERE t.status='completed' AND t.worker_id IS NOT NULL
        GROUP BY t.worker_id ORDER BY t.worker_id"""
    )
    timings = db.fetch_all(
        """SELECT started_at, completed_at FROM tasks
        WHERE status='completed' AND started_at IS NOT NULL AND completed_at IS NOT NULL"""
    )
    durations = []
    for row in timings:
        try:
            elapsed = (
                datetime.fromisoformat(row["completed_at"])
                - datetime.fromisoformat(row["started_at"])
            ).total_seconds()
            if elapsed >= 0:
                durations.append(elapsed)
        except (TypeError, ValueError):
            continue

    summary = {key: int(value or 0) for key, value in summary.items()}
    finished = summary["completed"] + summary["failed"]
    summary["success_rate"] = round(summary["completed"] * 100 / finished, 1) if finished else 0
    summary["duplicate_ratio"] = (
        round(summary["duplicates"] * 100 / summary["total_files"], 1)
        if summary["total_files"] else 0
    )
    summary["average_duration_seconds"] = (
        round(sum(durations) / len(durations), 3) if durations else 0
    )

    return jsonify(
        generated_at=db.utcnow(),
        summary=summary,
        categories=[{
            "category": row["category"] or "Others",
            "file_count": int(row["file_count"] or 0),
            "total_bytes": int(row["total_bytes"] or 0),
        } for row in categories],
        workers=[{
            "worker_id": int(row["worker_id"]),
            "task_count": int(row["task_count"] or 0),
            "total_bytes": int(row["total_bytes"] or 0),
        } for row in workers],
        scope_note="Worker totals combine all persisted runs; worker numbers are reused between batches.",
    )


@bp.get("/api/logs")
def api_logs():
    level = request.args.get("level", "all")
    if level in {"info", "success", "warning", "error"}:
        rows = db.fetch_all(
            "SELECT * FROM processing_logs WHERE level=? ORDER BY id DESC LIMIT 500", (level,)
        )
    else:
        rows = db.fetch_all("SELECT * FROM processing_logs ORDER BY id DESC LIMIT 500")
    return jsonify(logs=rows)


@bp.post("/api/upload")
def api_upload():
    uploads = request.files.getlist("files")
    if not uploads or all(not upload.filename for upload in uploads):
        return jsonify(ok=False, message="Choose at least one file."), 400
    created, rejected = [], []
    for upload in uploads[:100]:
        destination = None
        try:
            original, stored, destination = save_upload(upload, current_app.config["STORAGE_ROOT"])
            details, now = metadata_for(destination, original), db.utcnow()
            file_id = db.execute(
                """INSERT INTO files (original_filename,stored_filename,file_type,size,category,
                status,progress,source_path,created_at) VALUES (?,?,?,?,?,'pending',0,?,?)""",
                (original, stored, details["file_type"], details["size"], details["category"], str(destination), now),
            )
            task_id = db.execute(
                "INSERT INTO tasks(file_id,status,progress,queued_at) VALUES(?,'pending',0,?)",
                (file_id, now),
            )
            db.add_log("info", "upload", f"Queued upload: {original}", file_id=file_id)
            created.append({"file_id": file_id, "task_id": task_id, "filename": original})
        except (FileValidationError, OSError, db.DatabaseError) as error:
            if destination and destination.exists():
                destination.unlink(missing_ok=True)
            rejected.append({"filename": upload.filename or "unnamed", "error": str(error)})
    message = f"Queued {len(created)} file(s)." + (f" Rejected {len(rejected)}." if rejected else "")
    return jsonify(ok=bool(created), message=message, created=created, rejected=rejected), 201 if created else 400


@bp.post("/api/process/start")
def api_process_start():
    payload = request.get_json(silent=True) or {}
    requested_ids = payload.get("task_ids")
    if requested_ids is not None:
        if not isinstance(requested_ids, list) or not requested_ids:
            return jsonify(ok=False, message="Choose at least one queued file to run."), 400
        try:
            requested_ids = list(dict.fromkeys(int(task_id) for task_id in requested_ids))
        except (TypeError, ValueError):
            return jsonify(ok=False, message="Invalid queued task selection."), 400
        placeholders = ",".join("?" for _ in requested_ids)
        pending = db.fetch_all(
            f"SELECT id FROM tasks WHERE status='pending' AND id IN ({placeholders}) ORDER BY id",
            tuple(requested_ids),
        )
        if len(pending) != len(requested_ids):
            return jsonify(ok=False, message="One or more selected files are no longer pending."), 409
    else:
        pending = db.fetch_all("SELECT id FROM tasks WHERE status='pending' ORDER BY id")
    ok, message = manager().start_batch([row["id"] for row in pending])
    return jsonify(ok=ok, message=message), 202 if ok else 409


DEMO_SAMPLES = (
    ("architecture-notes.txt", b"FileFlow architecture\nQueue -> Workers -> Lock -> Supabase PostgreSQL\n"),
    ("student-records.csv", b"id,name,grade\n1,Ada,98\n2,Linus,95\n"),
    ("project-report.pdf", b"%PDF-1.4\nFileFlow demonstration document\n%%EOF"),
    ("dashboard.png", b"\x89PNG\r\n\x1a\nFILEFLOW-DEMO-IMAGE"),
    ("presentation.pptx", b"PK\x03\x04FileFlow presentation sample"),
    ("system-audio.mp3", b"ID3\x04\x00\x00FileFlow audio sample"),
    ("backup.zip", b"PK\x03\x04FileFlow archive sample"),
    ("demo-video.mp4", b"\x00\x00\x00\x18ftypmp42FileFlow video"),
    ("architecture-copy.txt", b"FileFlow architecture\nQueue -> Workers -> Lock -> Supabase PostgreSQL\n"),
)


@bp.post("/api/demo/start")
def api_demo_start():
    if manager().snapshot()["active"]:
        return jsonify(ok=False, message="Wait for the current batch to finish."), 409
    incoming = confined_path(current_app.config["STORAGE_ROOT"], "incoming")
    task_ids = []
    try:
        for original, content in DEMO_SAMPLES:
            stored = unique_name(original)
            destination = confined_path(incoming, stored)
            destination.write_bytes(content)
            details, now = metadata_for(destination, original), db.utcnow()
            file_id = db.execute(
                """INSERT INTO files (original_filename,stored_filename,file_type,size,category,
                status,progress,source_path,created_at) VALUES (?,?,?,?,?,'pending',0,?,?)""",
                (original, stored, details["file_type"], details["size"], details["category"], str(destination), now),
            )
            task_ids.append(db.execute(
                "INSERT INTO tasks(file_id,status,progress,queued_at) VALUES(?,'pending',0,?)", (file_id, now)
            ))
        db.add_log("info", "demo", f"Concurrent demo created {len(task_ids)} sample files.")
    except (OSError, db.DatabaseError) as error:
        db.add_log("error", "demo", f"Could not prepare demo: {error}")
        return jsonify(ok=False, message="Could not prepare demo files."), 500
    ok, message = manager().start_batch(task_ids, worker_count=5, demo=True)
    return jsonify(ok=ok, message=message), 202 if ok else 409


@bp.post("/api/synchronization-demo")
def api_synchronization_demo():
    result = synchronization_demo()
    db.add_log("warning", "race", f"Race demo: unsafe={result['unsafe_actual']}, safe={result['safe_actual']}, expected={result['expected']}.")
    return jsonify(ok=True, result=result)


@bp.route("/api/settings", methods=("GET", "POST"))
def api_settings():
    if request.method == "POST":
        payload = request.get_json(silent=True) or {}
        try:
            count = int(payload.get("worker_count", 5))
        except (TypeError, ValueError):
            return jsonify(ok=False, message="Worker count must be a number."), 400
        if not 1 <= count <= 12:
            return jsonify(ok=False, message="Worker count must be between 1 and 12."), 400
        if manager().snapshot()["active"]:
            return jsonify(ok=False, message="Settings cannot change during processing."), 409
        db.set_setting("worker_count", str(count))

        db.add_log("success", "settings", f"Worker count changed to {count}.")
        with manager().state_lock:
            manager().workers = {}
        return jsonify(ok=True, message="Settings saved.", worker_count=count)
    rows = db.fetch_all("SELECT `key` AS `key`, value FROM settings")
    return jsonify(settings={row["key"]: row["value"] for row in rows})


@bp.get("/api/files/<int:file_id>/download")
def download_file(file_id):
    row = db.fetch_one("SELECT organized_path,original_filename FROM files WHERE id=?", (file_id,))
    if not row or not row["organized_path"]:
        return jsonify(ok=False, message="Processed file not found."), 404
    path, root = Path(row["organized_path"]).resolve(), Path(current_app.config["STORAGE_ROOT"]).resolve()
    if root not in path.parents or not path.is_file():
        return jsonify(ok=False, message="Unsafe or missing file path."), 404
    return send_file(path, as_attachment=True, download_name=row["original_filename"])


@bp.delete("/api/files/<int:file_id>")
def delete_file(file_id):
    row = db.fetch_one("SELECT source_path,organized_path,status,original_filename FROM files WHERE id=?", (file_id,))
    if not row:
        return jsonify(ok=False, message="File not found."), 404
    if manager().snapshot()["active"] and row["status"] in {"pending", "processing"}:
        return jsonify(ok=False, message="A file in an active batch cannot be deleted."), 409
    root = Path(current_app.config["STORAGE_ROOT"]).resolve()
    for value in (row["source_path"], row["organized_path"]):
        if value:
            candidate = Path(value).resolve()
            if root in candidate.parents and candidate.is_file():
                candidate.unlink()
    db.execute("UPDATE files SET duplicate_of=NULL WHERE duplicate_of=?", (file_id,))
    db.execute("DELETE FROM tasks WHERE file_id=?", (file_id,))
    db.execute("DELETE FROM files WHERE id=?", (file_id,))
    db.add_log("warning", "delete", f"Deleted file record: {row['original_filename']}")
    return jsonify(ok=True, message="File deleted.")


@bp.app_errorhandler(413)
def too_large(_error):
    limit = current_app.config.get("MAX_UPLOAD_LABEL", "configured")
    return jsonify(ok=False, message=f"Upload exceeds the {limit} request limit."), 413



@bp.app_errorhandler(db.DatabaseError)
def database_unavailable(error):
    current_app.logger.error("Database request failed: %s", error)
    return jsonify(
        ok=False,
        message="Supabase PostgreSQL is unavailable. Check SUPABASE_DB_URL and network access.",
    ), 503

@bp.get("/favicon.ico")
def favicon():
    return current_app.send_static_file("favicon.ico")
