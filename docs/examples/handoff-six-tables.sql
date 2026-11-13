-- 本地虚构数据实验；批次 status 未定义枚举，未自行添加约束。

CREATE TABLE graph_sync_batch (
	id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, 
	source_project_id VARCHAR(64) NOT NULL, 
	sync_mode VARCHAR(16) NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	started_at DATETIME(6) NOT NULL, 
	snapshot_at DATETIME(6), 
	finished_at DATETIME(6), 
	expected_counts JSON, 
	actual_counts JSON, 
	error_message TEXT, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_batch_mode CHECK (sync_mode IN ('full','incremental'))
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_bin;

CREATE TABLE graph_company (
	id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL, 
	company_code VARCHAR(64) NOT NULL, 
	entity_key VARCHAR(128) NOT NULL, 
	standard_name VARCHAR(255) NOT NULL, 
	former_names JSON, 
	verification_status VARCHAR(64) NOT NULL, 
	child_company_codes JSON, 
	parent_company_codes JSON, 
	source_created_at DATETIME(6) NOT NULL, 
	source_updated_at DATETIME(6) NOT NULL, 
	sync_batch_id BIGINT UNSIGNED NOT NULL, 
	synced_at DATETIME(6) NOT NULL, 
	is_deleted TINYINT UNSIGNED NOT NULL DEFAULT '0', 
	deleted_at DATETIME(6), 
	PRIMARY KEY (id), 
	UNIQUE (company_code), 
	UNIQUE (entity_key), 
	CHECK (former_names IS NULL OR JSON_TYPE(former_names) = 'ARRAY'), 
	CHECK (child_company_codes IS NULL OR JSON_TYPE(child_company_codes) = 'ARRAY' OR (JSON_TYPE(child_company_codes) = 'INTEGER' AND JSON_UNQUOTE(child_company_codes) = '0')), 
	CHECK (parent_company_codes IS NULL OR JSON_TYPE(parent_company_codes) = 'ARRAY' OR (JSON_TYPE(parent_company_codes) = 'INTEGER' AND JSON_UNQUOTE(parent_company_codes) = '0')), 
	CHECK (is_deleted IN (0,1)), 
	FOREIGN KEY(sync_batch_id) REFERENCES graph_sync_batch (id)
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_bin;

CREATE INDEX ix_company_name ON graph_company (standard_name);

CREATE INDEX ix_graph_company_sync_batch_id ON graph_company (sync_batch_id);

CREATE TABLE graph_major (
	id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL, 
	major_code VARCHAR(64) NOT NULL, 
	entity_key VARCHAR(128) NOT NULL, 
	standard_name VARCHAR(255) NOT NULL, 
	verification_status VARCHAR(64) NOT NULL, 
	source_created_at DATETIME(6) NOT NULL, 
	source_updated_at DATETIME(6) NOT NULL, 
	sync_batch_id BIGINT UNSIGNED NOT NULL, 
	synced_at DATETIME(6) NOT NULL, 
	is_deleted TINYINT UNSIGNED NOT NULL DEFAULT '0', 
	deleted_at DATETIME(6), 
	PRIMARY KEY (id), 
	UNIQUE (major_code), 
	UNIQUE (entity_key), 
	CHECK (is_deleted IN (0,1)), 
	FOREIGN KEY(sync_batch_id) REFERENCES graph_sync_batch (id)
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_bin;

CREATE INDEX ix_graph_major_sync_batch_id ON graph_major (sync_batch_id);

CREATE INDEX ix_major_name ON graph_major (standard_name);

CREATE TABLE graph_school (
	id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL, 
	school_code VARCHAR(64) NOT NULL, 
	entity_key VARCHAR(128) NOT NULL, 
	standard_name VARCHAR(255) NOT NULL, 
	former_names JSON, 
	official_code VARCHAR(64), 
	country_region VARCHAR(128), 
	city VARCHAR(128), 
	verification_status VARCHAR(64) NOT NULL, 
	source_created_at DATETIME(6) NOT NULL, 
	source_updated_at DATETIME(6) NOT NULL, 
	sync_batch_id BIGINT UNSIGNED NOT NULL, 
	synced_at DATETIME(6) NOT NULL, 
	is_deleted TINYINT UNSIGNED NOT NULL DEFAULT '0', 
	deleted_at DATETIME(6), 
	PRIMARY KEY (id), 
	UNIQUE (school_code), 
	UNIQUE (entity_key), 
	CHECK (former_names IS NULL OR JSON_TYPE(former_names) = 'ARRAY'), 
	CHECK (is_deleted IN (0,1)), 
	FOREIGN KEY(sync_batch_id) REFERENCES graph_sync_batch (id)
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_bin;

CREATE INDEX ix_graph_school_sync_batch_id ON graph_school (sync_batch_id);

CREATE INDEX ix_school_name ON graph_school (standard_name);

CREATE TABLE graph_company_relation (
	id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL, 
	parent_company_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL, 
	child_company_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL, 
	relation_type VARCHAR(32) NOT NULL, 
	verification_status VARCHAR(64) NOT NULL, 
	source_created_at DATETIME(6) NOT NULL, 
	source_updated_at DATETIME(6) NOT NULL, 
	sync_batch_id BIGINT UNSIGNED NOT NULL, 
	synced_at DATETIME(6) NOT NULL, 
	is_deleted TINYINT UNSIGNED NOT NULL DEFAULT '0', 
	deleted_at DATETIME(6), 
	PRIMARY KEY (id), 
	CHECK (is_deleted IN (0,1)), 
	UNIQUE (parent_company_id, child_company_id, relation_type), 
	CONSTRAINT ck_relation_self CHECK (parent_company_id <> child_company_id), 
	CONSTRAINT ck_relation_type CHECK (relation_type IN ('子公司','分公司')), 
	FOREIGN KEY(parent_company_id) REFERENCES graph_company (id), 
	FOREIGN KEY(child_company_id) REFERENCES graph_company (id), 
	FOREIGN KEY(sync_batch_id) REFERENCES graph_sync_batch (id)
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_bin;

CREATE INDEX ix_graph_company_relation_sync_batch_id ON graph_company_relation (sync_batch_id);

CREATE INDEX ix_relation_child ON graph_company_relation (child_company_id, verification_status, is_deleted);

CREATE TABLE graph_expert_name_mapping (
	id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL, 
	entity_type VARCHAR(16) NOT NULL, 
	source_namespace VARCHAR(128) NOT NULL, 
	source_record_id VARCHAR(128) NOT NULL, 
	item_no INTEGER UNSIGNED NOT NULL, 
	raw_name TEXT NOT NULL, 
	company_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin, 
	school_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin, 
	major_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin, 
	processing_status VARCHAR(64) NOT NULL, 
	source_updated_at DATETIME(6) NOT NULL, 
	sync_batch_id BIGINT UNSIGNED NOT NULL, 
	synced_at DATETIME(6) NOT NULL, 
	is_deleted TINYINT UNSIGNED NOT NULL DEFAULT '0', 
	PRIMARY KEY (id), 
	CHECK (is_deleted IN (0,1)), 
	CONSTRAINT ck_mapping_item CHECK (item_no > 0), 
	CONSTRAINT ck_mapping_kind CHECK (entity_type IN ('company','school','major')), 
	CONSTRAINT ck_mapping_status CHECK (processing_status IN ('待处理','已匹配','待确认','无有效名称','处理失败','部分匹配')), 
	CONSTRAINT ck_mapping_target CHECK ((entity_type='company' AND school_id IS NULL AND major_id IS NULL AND (processing_status<>'已匹配' OR company_id IS NOT NULL)) OR (entity_type='school' AND company_id IS NULL AND major_id IS NULL AND (processing_status<>'已匹配' OR school_id IS NOT NULL)) OR (entity_type='major' AND company_id IS NULL AND school_id IS NULL AND (processing_status<>'已匹配' OR major_id IS NOT NULL))), 
	FOREIGN KEY(company_id) REFERENCES graph_company (id), 
	FOREIGN KEY(school_id) REFERENCES graph_school (id), 
	FOREIGN KEY(major_id) REFERENCES graph_major (id), 
	FOREIGN KEY(sync_batch_id) REFERENCES graph_sync_batch (id)
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_bin;

CREATE INDEX ix_graph_expert_name_mapping_sync_batch_id ON graph_expert_name_mapping (sync_batch_id);

CREATE INDEX ix_mapping_company ON graph_expert_name_mapping (company_id, processing_status, is_deleted);

CREATE INDEX ix_mapping_major ON graph_expert_name_mapping (major_id, processing_status, is_deleted);

CREATE INDEX ix_mapping_school ON graph_expert_name_mapping (school_id, processing_status, is_deleted);

CREATE INDEX ix_mapping_source ON graph_expert_name_mapping (source_namespace, source_record_id, entity_type, is_deleted);
