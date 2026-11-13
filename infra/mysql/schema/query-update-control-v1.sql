-- 人物关系查询系统独立控制库，MySQL 8.0.16+，设计 v1。
-- 由本项目部署到自己的控制库。连接会话统一 SET time_zone='+00:00'。
-- 建表前由部署流程选定新库；本文件不创建库，不写上游业务表。

CREATE TABLE rq_cdc_checkpoint (
    stream_id VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    source_generation CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    source_identity_sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    capture_state VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL DEFAULT 'bootstrapping',
    baseline_cursor JSON NULL,
    capture_cursor JSON NULL,
    captured_tx_seq BIGINT UNSIGNED NOT NULL DEFAULT 0,
    lease_owner VARCHAR(128) NULL,
    lease_token BIGINT UNSIGNED NOT NULL DEFAULT 0,
    lease_until DATETIME(6) NULL,
    error_code VARCHAR(64) NULL,
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (stream_id),
    CONSTRAINT ck_rq_capture_state CHECK (capture_state IN ('bootstrapping','streaming','paused','failed')),
    CONSTRAINT ck_rq_capture_cursor CHECK (
        capture_state <> 'streaming' OR (baseline_cursor IS NOT NULL AND capture_cursor IS NOT NULL)
    ),
    CONSTRAINT ck_rq_capture_lease CHECK (
        (lease_owner IS NULL AND lease_until IS NULL) OR
        (lease_owner IS NOT NULL AND lease_until IS NOT NULL)
    )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE rq_cdc_event (
    stream_id VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    source_generation CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    tx_seq BIGINT UNSIGNED NOT NULL,
    event_index INT UNSIGNED NOT NULL,
    source_event_id CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    source_tx_key VARCHAR(255) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    commit_cursor JSON NOT NULL,
    source_table VARCHAR(128) NOT NULL,
    operation VARCHAR(8) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    source_pk JSON NULL,
    before_row JSON NULL,
    after_row JSON NULL,
    source_committed_at DATETIME(6) NULL,
    captured_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (stream_id, source_generation, tx_seq, event_index),
    UNIQUE KEY uq_rq_source_event (stream_id, source_generation, source_event_id),
    KEY ix_rq_source_transaction (stream_id, source_generation, source_tx_key),
    CONSTRAINT fk_rq_event_stream FOREIGN KEY (stream_id) REFERENCES rq_cdc_checkpoint(stream_id),
    CONSTRAINT ck_rq_event_seq CHECK (tx_seq > 0),
    CONSTRAINT ck_rq_event_operation CHECK (operation IN ('insert','update','delete','ddl')),
    CONSTRAINT ck_rq_event_images CHECK (
        (operation = 'insert' AND source_pk IS NOT NULL AND after_row IS NOT NULL) OR
        (operation = 'update' AND source_pk IS NOT NULL AND before_row IS NOT NULL AND after_row IS NOT NULL) OR
        (operation = 'delete' AND source_pk IS NOT NULL AND before_row IS NOT NULL) OR
        operation = 'ddl'
    )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE rq_projection_batch (
    batch_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    stream_id VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    source_generation CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    idempotency_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    trigger_kind VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    base_batch_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NULL,
    expected_release_revision BIGINT UNSIGNED NOT NULL,
    expected_release_digest CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NULL,
    from_tx_seq BIGINT UNSIGNED NOT NULL,
    to_tx_seq BIGINT UNSIGNED NOT NULL,
    end_cursor JSON NOT NULL,
    reference_month INT NOT NULL,
    model_version VARCHAR(64) NOT NULL,
    status VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL DEFAULT 'queued',
    attempt_count INT UNSIGNED NOT NULL DEFAULT 0,
    next_attempt_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    lease_owner VARCHAR(128) NULL,
    lease_token BIGINT UNSIGNED NOT NULL DEFAULT 0,
    lease_until DATETIME(6) NULL,
    data_version VARCHAR(128) NULL,
    projection_id VARCHAR(128) NULL,
    source_digest CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NULL,
    graph_digest CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NULL,
    bundle_digest CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NULL,
    verification_report_ref VARCHAR(1024) NULL,
    release_directory VARCHAR(1024) NULL,
    sql_database VARCHAR(64) NULL,
    graph_space VARCHAR(128) NULL,
    error_code VARCHAR(64) NULL,
    error_message VARCHAR(1024) NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    ready_at DATETIME(6) NULL,
    published_at DATETIME(6) NULL,
    PRIMARY KEY (batch_id),
    UNIQUE KEY uq_rq_projection_request (stream_id, idempotency_key),
    KEY ix_rq_projection_queue (stream_id, status, next_attempt_at),
    CONSTRAINT fk_rq_batch_stream FOREIGN KEY (stream_id) REFERENCES rq_cdc_checkpoint(stream_id),
    CONSTRAINT fk_rq_base_batch FOREIGN KEY (base_batch_id) REFERENCES rq_projection_batch(batch_id),
    CONSTRAINT ck_rq_batch_trigger CHECK (trigger_kind IN ('initial','cdc','month_rollover','reconcile')),
    CONSTRAINT ck_rq_batch_range CHECK (to_tx_seq >= from_tx_seq),
    CONSTRAINT ck_rq_batch_month CHECK (reference_month BETWEEN 100001 AND 999912 AND reference_month % 100 BETWEEN 1 AND 12),
    CONSTRAINT ck_rq_batch_status CHECK (status IN ('queued','building','verifying','ready','published','failed','cancelled')),
    CONSTRAINT ck_rq_batch_lease CHECK (
        (lease_owner IS NULL AND lease_until IS NULL) OR
        (lease_owner IS NOT NULL AND lease_until IS NOT NULL)
    ),
    CONSTRAINT ck_rq_ready_artifacts CHECK (
        status NOT IN ('ready','published') OR (
            source_digest IS NOT NULL AND graph_digest IS NOT NULL AND bundle_digest IS NOT NULL AND
            verification_report_ref IS NOT NULL AND
            release_directory IS NOT NULL AND sql_database IS NOT NULL AND graph_space IS NOT NULL AND
            data_version IS NOT NULL AND projection_id IS NOT NULL AND ready_at IS NOT NULL
        )
    ),
    CONSTRAINT ck_rq_published_time CHECK (status <> 'published' OR published_at IS NOT NULL)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
