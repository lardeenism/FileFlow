-- FileFlow schema for Supabase PostgreSQL.
-- The application creates these objects automatically. This script can also be
-- pasted into the Supabase SQL Editor before the first application run.

CREATE TABLE IF NOT EXISTS files (
  id BIGSERIAL PRIMARY KEY,
  original_filename VARCHAR(255) NOT NULL,
  stored_filename VARCHAR(255) NOT NULL,
  file_type VARCHAR(150),
  size BIGINT NOT NULL DEFAULT 0 CHECK (size >= 0),
  category VARCHAR(50),
  sha256 CHAR(64),
  is_duplicate SMALLINT NOT NULL DEFAULT 0 CHECK (is_duplicate IN (0, 1)),
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
);

CREATE TABLE IF NOT EXISTS tasks (
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
);

CREATE TABLE IF NOT EXISTS processing_logs (
  id BIGSERIAL PRIMARY KEY,
  level VARCHAR(20) NOT NULL,
  event_type VARCHAR(40) NOT NULL,
  message TEXT NOT NULL,
  worker_id INTEGER,
  thread_id BIGINT,
  file_id BIGINT,
  created_at VARCHAR(40) NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
  "key" VARCHAR(100) PRIMARY KEY,
  value TEXT NOT NULL,
  updated_at VARCHAR(40) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_files_hash ON files(sha256);
CREATE INDEX IF NOT EXISTS idx_files_status ON files(status);
CREATE INDEX IF NOT EXISTS idx_files_category ON files(category);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_file ON tasks(file_id);
CREATE INDEX IF NOT EXISTS idx_logs_created ON processing_logs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_logs_level ON processing_logs(level);
CREATE INDEX IF NOT EXISTS idx_logs_file ON processing_logs(file_id);

-- FileFlow connects from its trusted Flask backend with the database role.
-- No anonymous Data API policies are created.
ALTER TABLE files ENABLE ROW LEVEL SECURITY;
ALTER TABLE tasks ENABLE ROW LEVEL SECURITY;
ALTER TABLE processing_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE settings ENABLE ROW LEVEL SECURITY;

INSERT INTO settings ("key", value, updated_at)
VALUES ('worker_count', '5', to_char(clock_timestamp(), 'YYYY-MM-DD"T"HH24:MI:SS.MS"+00:00"'))
ON CONFLICT ("key") DO NOTHING;

INSERT INTO settings ("key", value, updated_at)
VALUES ('demo_delay', 'true', to_char(clock_timestamp(), 'YYYY-MM-DD"T"HH24:MI:SS.MS"+00:00"'))
ON CONFLICT ("key") DO NOTHING;
