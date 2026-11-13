-- 文件映射版 eafd2c32 的独立测试实现，5表58列。
-- Word未提供完整DDL，必填／可空、索引及CHECK依字段说明实现，正式DDL需另行核对。
CREATE TABLE graph_sync_batch (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  source_project_id VARCHAR(64) NOT NULL,
  sync_mode VARCHAR(16) NOT NULL CHECK (sync_mode IN ('full','incremental')),
  status VARCHAR(16) NOT NULL CHECK (status IN ('running','validated','succeeded','failed')),
  started_at DATETIME(6) NOT NULL,
  snapshot_at DATETIME(6) NULL,
  finished_at DATETIME(6) NULL,
  expected_counts JSON NULL,
  actual_counts JSON NULL,
  error_message TEXT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE graph_company_entity (
  id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  uuid CHAR(36) NOT NULL UNIQUE,
  company_code VARCHAR(64) NOT NULL UNIQUE,
  standard_name VARCHAR(255) NOT NULL,
  former_names JSON NULL,
  verification_status VARCHAR(64) NOT NULL,
  child_company_codes JSON NULL,
  parent_company_codes JSON NULL,
  source_created_at DATETIME(6) NOT NULL,
  source_updated_at DATETIME(6) NOT NULL,
  sync_batch_id BIGINT UNSIGNED NOT NULL,
  synced_at DATETIME(6) NOT NULL,
  deleted_at DATETIME(6) NULL,
  INDEX (standard_name),
  FOREIGN KEY (sync_batch_id) REFERENCES graph_sync_batch(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE graph_school_entity (
  id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  uuid CHAR(36) NOT NULL UNIQUE,
  school_code VARCHAR(64) NOT NULL UNIQUE,
  standard_name VARCHAR(255) NOT NULL,
  former_names JSON NULL,
  official_code VARCHAR(64) NULL,
  country_region VARCHAR(128) NULL,
  city VARCHAR(128) NULL,
  verification_status VARCHAR(64) NOT NULL,
  source_created_at DATETIME(6) NOT NULL,
  source_updated_at DATETIME(6) NOT NULL,
  sync_batch_id BIGINT UNSIGNED NOT NULL,
  synced_at DATETIME(6) NOT NULL,
  deleted_at DATETIME(6) NULL,
  INDEX (standard_name),
  FOREIGN KEY (sync_batch_id) REFERENCES graph_sync_batch(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE graph_major_entity (
  id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  uuid CHAR(36) NOT NULL UNIQUE,
  major_code VARCHAR(64) NOT NULL UNIQUE,
  standard_name VARCHAR(255) NOT NULL,
  verification_status VARCHAR(64) NOT NULL,
  source_created_at DATETIME(6) NOT NULL,
  source_updated_at DATETIME(6) NOT NULL,
  sync_batch_id BIGINT UNSIGNED NOT NULL,
  synced_at DATETIME(6) NOT NULL,
  deleted_at DATETIME(6) NULL,
  INDEX (standard_name),
  FOREIGN KEY (sync_batch_id) REFERENCES graph_sync_batch(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE graph_edge_mapping (
  id BIGINT NOT NULL PRIMARY KEY CHECK (id > 0),
  source_system VARCHAR(16) NOT NULL CHECK (source_system IN ('expert','resume')),
  source_table VARCHAR(64) NOT NULL,
  source_field_id BIGINT NOT NULL,
  source_field VARCHAR(64) NOT NULL,
  source_person_id BIGINT NOT NULL,
  standard_entity_id BIGINT NOT NULL,
  edge_type VARCHAR(64) NOT NULL,
  created_at DATETIME(6) NULL,
  updated_at DATETIME(6) NULL,
  deleted_at DATETIME(6) NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
