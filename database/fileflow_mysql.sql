-- FileFlow schema for XAMPP MySQL / MariaDB
-- Import this file in phpMyAdmin only if you do not want the Flask app
-- to create the database and tables automatically.

CREATE DATABASE IF NOT EXISTS fileflow
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE fileflow;

CREATE TABLE IF NOT EXISTS files (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  original_filename VARCHAR(255) NOT NULL,
  stored_filename VARCHAR(255) NOT NULL,
  file_type VARCHAR(150) NULL,
  size BIGINT UNSIGNED NOT NULL DEFAULT 0,
  category VARCHAR(50) NULL,
  sha256 CHAR(64) NULL,
  is_duplicate TINYINT(1) NOT NULL DEFAULT 0,
  duplicate_of BIGINT UNSIGNED NULL,
  worker_id INT NULL,
  thread_id BIGINT NULL,
  status VARCHAR(30) NOT NULL DEFAULT 'pending',
  progress TINYINT UNSIGNED NOT NULL DEFAULT 0,
  source_path TEXT NOT NULL,
  organized_path TEXT NULL,
  created_at VARCHAR(40) NOT NULL,
  started_at VARCHAR(40) NULL,
  completed_at VARCHAR(40) NULL,
  error TEXT NULL,
  CONSTRAINT fk_files_duplicate FOREIGN KEY (duplicate_of)
    REFERENCES files(id) ON DELETE SET NULL,
  INDEX idx_files_hash (sha256),
  INDEX idx_files_status (status),
  INDEX idx_files_category (category)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS tasks (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  file_id BIGINT UNSIGNED NOT NULL,
  worker_id INT NULL,
  thread_id BIGINT NULL,
  status VARCHAR(30) NOT NULL DEFAULT 'pending',
  progress TINYINT UNSIGNED NOT NULL DEFAULT 0,
  queued_at VARCHAR(40) NOT NULL,
  started_at VARCHAR(40) NULL,
  completed_at VARCHAR(40) NULL,
  error TEXT NULL,
  CONSTRAINT fk_tasks_file FOREIGN KEY (file_id)
    REFERENCES files(id) ON DELETE CASCADE,
  INDEX idx_tasks_status (status),
  INDEX idx_tasks_file (file_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS processing_logs (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  level VARCHAR(20) NOT NULL,
  event_type VARCHAR(40) NOT NULL,
  message TEXT NOT NULL,
  worker_id INT NULL,
  thread_id BIGINT NULL,
  file_id BIGINT UNSIGNED NULL,
  created_at VARCHAR(40) NOT NULL,
  INDEX idx_logs_created (created_at),
  INDEX idx_logs_level (level),
  INDEX idx_logs_file (file_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS settings (
  `key` VARCHAR(100) NOT NULL PRIMARY KEY,
  value TEXT NOT NULL,
  updated_at VARCHAR(40) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO settings (`key`, value, updated_at)
VALUES ('worker_count', '5', UTC_TIMESTAMP(3))
ON DUPLICATE KEY UPDATE `key` = `key`;

INSERT INTO settings (`key`, value, updated_at)
VALUES ('demo_delay', 'true', UTC_TIMESTAMP(3))
ON DUPLICATE KEY UPDATE `key` = `key`;
