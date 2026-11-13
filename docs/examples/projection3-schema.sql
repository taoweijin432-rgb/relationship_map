-- 实验约束包含建议的槽位唯一键；缺失的合并／发布列未补造。

CREATE TABLE `Relationship_Graph_entity` (
	id BIGINT NOT NULL, 
	entity_type VARCHAR(32) NOT NULL, 
	canonical_name VARCHAR(255) NOT NULL, 
	created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), 
	updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6), 
	deleted_at DATETIME(6), 
	PRIMARY KEY (id), 
	CHECK (id > 0), 
	CHECK (entity_type IN ('organization','role','project','school','major'))
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_bin;

CREATE INDEX ix_dictionary_name_type ON `Relationship_Graph_entity` (canonical_name, entity_type, deleted_at);

CREATE TABLE `Relationship_Graph_edge_mapping` (
	id BIGINT NOT NULL, 
	source_system VARCHAR(16) NOT NULL, 
	source_table VARCHAR(64) NOT NULL, 
	source_field_id BIGINT NOT NULL, 
	source_field VARCHAR(64) NOT NULL, 
	source_person_id BIGINT NOT NULL, 
	entity_id BIGINT NOT NULL, 
	edge_type VARCHAR(64) NOT NULL, 
	created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), 
	updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6), 
	deleted_at DATETIME(6), 
	PRIMARY KEY (id), 
	CHECK (id > 0 AND source_field_id > 0 AND source_person_id > 0), 
	UNIQUE (source_system, source_table, source_field_id, source_field), 
	CONSTRAINT ck_source_slot_role CHECK ((source_system='expert' AND source_table='experts_work_experience' AND source_field='company_name' AND edge_type='worked_at') OR (source_system='expert' AND source_table='experts_work_experience' AND source_field='position_title' AND edge_type='held_role') OR (source_system='expert' AND source_table='experts_project_experience' AND source_field='project_title' AND edge_type='participated_in') OR (source_system='expert' AND source_table='experts_project_experience' AND source_field='company_name' AND edge_type='collaborated with') OR (source_system='expert' AND source_table='experts_education_experience' AND source_field='school_name' AND edge_type='studied_at') OR (source_system='expert' AND source_table='experts_education_experience' AND source_field='major' AND edge_type='studied_major') OR (source_system='resume' AND source_table='resume_work_experience' AND source_field='company_name' AND edge_type='worked_at') OR (source_system='resume' AND source_table='resume_work_experience' AND source_field='position_title' AND edge_type='held_role') OR (source_system='resume' AND source_table='resume_project_experience' AND source_field='project_title' AND edge_type='participated_in') OR (source_system='resume' AND source_table='resume_project_experience' AND source_field='company_name' AND edge_type='collaborated with') OR (source_system='resume' AND source_table='resume_education_experience' AND source_field='school_name' AND edge_type='studied_at') OR (source_system='resume' AND source_table='resume_education_experience' AND source_field='major' AND edge_type='studied_major')), 
	FOREIGN KEY(entity_id) REFERENCES `Relationship_Graph_entity` (id)
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_bin;

CREATE INDEX ix_edge_target ON `Relationship_Graph_edge_mapping` (entity_id);

CREATE TABLE `Relationship_Graph_entity_alias` (
	id BIGINT NOT NULL, 
	entity_id BIGINT NOT NULL, 
	alias_name VARCHAR(255) NOT NULL, 
	created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), 
	updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6), 
	deleted_at DATETIME(6), 
	PRIMARY KEY (id), 
	CHECK (id > 0), 
	UNIQUE (entity_id, alias_name), 
	FOREIGN KEY(entity_id) REFERENCES `Relationship_Graph_entity` (id)
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_bin;

CREATE INDEX ix_alias_lookup ON `Relationship_Graph_entity_alias` (alias_name, deleted_at);
