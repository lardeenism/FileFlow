"""Supabase PostgreSQL database adapter."""

import re
from datetime import datetime, timezone

from flask import current_app, g

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:
    psycopg = None
    dict_row = None


class DatabaseError(RuntimeError):
    """A safe application-level wrapper around database driver errors."""


POSTGRES_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS files (
        id BIGSERIAL PRIMARY KEY,
        original_filename VARCHAR(255) NOT NULL,
        stored_filename VARCHAR(255) NOT NULL,
        file_type VARCHAR(150),
        size BIGINT NOT NULL DEFAULT 0 CHECK (size >= 0),
        category VARCHAR(50),
        sha256 CHAR(64),
        is_duplicate SMALLINT NOT NULL DEFAULT 0 CHECK (is_duplicate IN (0,1)),
        duplicate_of BIGINT REFERENCES files(id) ON DELETE SET NULL,
        worker_id INTEGER,
        thread_id BIGINT,
        status VARCHAR(30) NOT NULL DEFAULT 'pending',
        progress SMALLINT NOT NULL DEFAULT 0 CHECK (progress BETWEEN 0 AND 100),
        source_path TEXT NOT NULL,
        organized_path TEXT,
        created_at VARCHAR(40) NOT NULL,
        started_at VARCHAR(40),
        completed_at VARCHAR(40),
        error TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS tasks (
        id BIGSERIAL PRIMARY KEY,
        file_id BIGINT NOT NULL REFERENCES files(id) ON DELETE CASCADE,
        worker_id INTEGER,
        thread_id BIGINT,
        status VARCHAR(30) NOT NULL DEFAULT 'pending',
        progress SMALLINT NOT NULL DEFAULT 0 CHECK (progress BETWEEN 0 AND 100),
        queued_at VARCHAR(40) NOT NULL,
        started_at VARCHAR(40),
        completed_at VARCHAR(40),
        error TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS processing_logs (
        id BIGSERIAL PRIMARY KEY,
        level VARCHAR(20) NOT NULL,
        event_type VARCHAR(40) NOT NULL,
        message TEXT NOT NULL,
        worker_id INTEGER,
        thread_id BIGINT,
        file_id BIGINT,
        created_at VARCHAR(40) NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS settings (
        "key" VARCHAR(100) PRIMARY KEY,
        value TEXT NOT NULL,
        updated_at VARCHAR(40) NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_files_hash ON files(sha256)",
    "CREATE INDEX IF NOT EXISTS idx_files_status ON files(status)",
    "CREATE INDEX IF NOT EXISTS idx_files_category ON files(category)",
    "CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)",
    "CREATE INDEX IF NOT EXISTS idx_tasks_file ON tasks(file_id)",
    "CREATE INDEX IF NOT EXISTS idx_logs_created ON processing_logs(created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_logs_level ON processing_logs(level)",
    "CREATE INDEX IF NOT EXISTS idx_logs_file ON processing_logs(file_id)",
    "ALTER TABLE files ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE tasks ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE processing_logs ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE settings ENABLE ROW LEVEL SECURITY",
)


def utcnow():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _postgres_query(query):
    """Translate the small shared SQL subset to Psycopg's parameter style."""
    return query.replace("?", "%s").replace(" COLLATE NOCASE", "").replace("`", '"')


def _supabase_connection():
    if psycopg is None:
        raise DatabaseError("Psycopg is not installed. Run: python -m pip install -r requirements.txt")
    database_url = current_app.config.get("SUPABASE_DB_URL", "").strip()
    if not database_url:
        raise DatabaseError(
            "SUPABASE_DB_URL is not configured. Copy a connection string from the Supabase Connect panel."
        )
    if "sslmode=" not in database_url.lower():
        separator = "&" if "?" in database_url else "?"
        database_url = f"{database_url}{separator}sslmode=require"
    return psycopg.connect(
        database_url, autocommit=True, connect_timeout=5,
        prepare_threshold=None, row_factory=dict_row
    )


def get_db():
    if "db" not in g:
        try:
            g.db = _supabase_connection()
        except DatabaseError:
            raise
        except Exception as error:
            raise DatabaseError("The database connection could not be opened.") from error
    return g.db


def close_db(_error=None):
    connection = g.pop("db", None)
    if connection is not None:
        connection.close()


def init_db():
    try:
        connection = get_db()
        with connection.cursor() as cursor:
            for statement in POSTGRES_SCHEMA:
                cursor.execute(statement)
        if fetch_one('SELECT value FROM settings WHERE "key"=?', ("worker_count",)) is None:
            set_setting("worker_count", "5")
        if fetch_one('SELECT value FROM settings WHERE "key"=?', ("demo_delay",)) is None:
            set_setting("demo_delay", "true")
    except DatabaseError:
        raise
    except Exception as error:
        raise DatabaseError("Could not initialize the FileFlow database schema.") from error


def init_app(app):
    app.teardown_appcontext(close_db)


def fetch_all(query, params=()):
    try:
        connection = get_db()
        with connection.cursor() as cursor:
            cursor.execute(_postgres_query(query), params)
            return list(cursor.fetchall())
    except DatabaseError:
        raise
    except Exception as error:
        raise DatabaseError("A database read failed.") from error


def fetch_one(query, params=()):
    rows = fetch_all(query, params)
    return rows[0] if rows else None


def execute(query, params=()):
    try:
        connection = get_db()
        translated = _postgres_query(query)
        returns_id = re.match(
            r"\s*INSERT\s+INTO\s+(files|tasks|processing_logs)\b",
            query,
            flags=re.IGNORECASE,
        )
        if returns_id and " RETURNING " not in translated.upper():
            translated = translated.rstrip().rstrip(";") + " RETURNING id"
        with connection.cursor() as cursor:
            cursor.execute(translated, params)
            row = cursor.fetchone() if returns_id else None
            return row["id"] if row else None
    except DatabaseError:
        raise
    except Exception as error:
        raise DatabaseError("A database write failed.") from error


def set_setting(key, value):
    execute(
        """INSERT INTO settings ("key", value, updated_at) VALUES (?, ?, ?)
           ON CONFLICT("key") DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
        (key, value, utcnow()),
    )


def add_log(level, event_type, message, worker_id=None, thread_id=None, file_id=None):
    return execute(
        """INSERT INTO processing_logs
           (level, event_type, message, worker_id, thread_id, file_id, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (level, event_type, message, worker_id, thread_id, file_id, utcnow()),
    )
