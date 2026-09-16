"""FileFlow application factory."""

import os
from pathlib import Path

from flask import Flask
from dotenv import load_dotenv

from . import db
from .processing import ProcessingManager
from .routes import bp


load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)


def create_app(test_config=None):
    try:
        max_upload_mb = int(os.getenv("FILEFLOW_MAX_UPLOAD_MB", "1024"))
    except ValueError:
        max_upload_mb = 1024
    max_upload_mb = min(10 * 1024, max(1, max_upload_mb))
    max_upload_label = f"{max_upload_mb // 1024:g} GB" if max_upload_mb % 1024 == 0 else f"{max_upload_mb} MB"
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        SECRET_KEY="fileflow-development-key",
        SUPABASE_DB_URL=os.getenv("SUPABASE_DB_URL", ""),
        STORAGE_ROOT=str(Path(app.instance_path) / "storage"),
        MAX_UPLOAD_MB=max_upload_mb,
        MAX_UPLOAD_LABEL=max_upload_label,
        MAX_CONTENT_LENGTH=max_upload_mb * 1024 * 1024,
        FILEFLOW_CATEGORIES=("Images", "Documents", "Spreadsheets", "Presentations",
                             "Videos", "Audio", "Archives", "Others", "Duplicates"),
    )
    if test_config:
        app.config.update(test_config)

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    storage = Path(app.config["STORAGE_ROOT"])
    (storage / "incoming").mkdir(parents=True, exist_ok=True)
    for category in (*app.config.get("FILEFLOW_CATEGORIES", ()),):
        (storage / "organized" / category).mkdir(parents=True, exist_ok=True)

    db.init_app(app)
    with app.app_context():
        db.init_db()

    manager = ProcessingManager(app)
    app.extensions["processing_manager"] = manager
    app.register_blueprint(bp)
    return app
