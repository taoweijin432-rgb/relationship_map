# R01 模拟规模与查询诊断报告

实验标签：r01-v0.8；生成于 2026-11-03T07:47:12.994019+00:00。

仅固定种子虚构数据、单进程顺序请求；ASGI TestClient 包含路由及序列化，不含网络、网关或并发。不能推算百万级生产容量。

每个场景在独立进程中首次观测一次，再记录预热重复；首次观测不是清空操作系统缓存的冷启动。P95 为最近秩法，小样本只供观察。

阶段耗时为嵌套的 inclusive wall time，不能相加。cursor_execute_ms 不包含后续全部 fetch；VM 步数是近似值，不是扫描行数。路径保留自己的执行预算，不被诊断器覆盖。

环境：`{'python': '3.12.14', 'executable': '/Users/yuka/Developer/character_relationship_map/backend/.venv/bin/python', 'platform': 'macOS-26.5.1-arm64-arm-64bit', 'machine': 'arm64', 'logical_cpus': 10, 'sqlite': '3.53.1', 'backend_source_sha256': 'c791a5b6190e76fa57eb0aa551017d6a4b1d1fcba67c2947d8805e9b5af5691e'}`

| 人物规模 | 场景 | 策略 | 首次 ms | 预热 P50 / P95 ms | 响应 KiB | 路径数 | 受限原因 / 错误 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 10000 | meta | baseline | 13.306 | 5.672 / 6.026 | 0.2 | 0 | 无 |
| 10000 | meta | current | 12.696 | 5.607 / 5.996 | 0.2 | 0 | 无 |
| 10000 | name_prefix | baseline | 7.972 | 1.344 / 1.744 | 3.1 | 0 | 无 |
| 10000 | name_prefix | current | 8.158 | 1.422 / 1.711 | 3.1 | 0 | 无 |
| 10000 | name_miss | baseline | 8.352 | 1.604 / 1.771 | 0.1 | 0 | 无 |
| 10000 | name_miss | current | 8.477 | 1.722 / 1.989 | 0.1 | 0 | 无 |
| 10000 | entity_alias | baseline | 8.735 | 1.367 / 1.533 | 0.2 | 0 | 无 |
| 10000 | entity_alias | current | 7.959 | 1.358 / 1.615 | 0.2 | 0 | 无 |
| 10000 | entity_ordinary | baseline | 13.769 | 5.456 / 5.574 | 29.6 | 0 | 无 |
| 10000 | entity_ordinary | current | 13.385 | 5.492 / 5.611 | 29.6 | 0 | 无 |
| 10000 | entity_hot_company | baseline | 11.141 | 3.634 / 3.763 | 32.2 | 0 | 无 |
| 10000 | entity_hot_company | current | 11.446 | 3.641 / 4.312 | 32.2 | 0 | 无 |
| 10000 | entity_hot_school | baseline | 10.986 | 3.066 / 3.374 | 22.5 | 0 | 无 |
| 10000 | entity_hot_school | current | 10.838 | 3.049 / 3.277 | 22.5 | 0 | 无 |
| 10000 | company_role | baseline | 11.281 | 3.857 / 4.249 | 2.5 | 0 | 无 |
| 10000 | company_role | current | 11.489 | 3.761 / 4.158 | 2.5 | 0 | 无 |
| 10000 | multi_intersection | baseline | 11.03 | 3.468 / 4.0 | 2.0 | 0 | 无 |
| 10000 | multi_intersection | current | 11.275 | 3.691 / 3.909 | 2.0 | 0 | 无 |
| 10000 | empty_intersection | baseline | 9.818 | 3.093 / 3.404 | 0.6 | 0 | 无 |
| 10000 | empty_intersection | current | 10.126 | 3.167 / 3.381 | 0.6 | 0 | 无 |
| 10000 | deep_cursor | baseline | 11.432 | 3.677 / 3.986 | 32.3 | 0 | 无 |
| 10000 | deep_cursor | current | 11.346 | 3.659 / 3.879 | 32.3 | 0 | 无 |
| 10000 | person_ordinary | baseline | 16.36 | 6.503 / 7.753 | 2.0 | 0 | 无 |
| 10000 | person_ordinary | current | 14.855 | 6.508 / 7.304 | 2.0 | 0 | 无 |
| 10000 | person_hot | baseline | 13.325 | 4.66 / 4.914 | 17.2 | 0 | 无 |
| 10000 | person_hot | current | 13.357 | 4.576 / 4.815 | 17.2 | 0 | 无 |
| 10000 | person_long | baseline | 20.949 | 12.692 / 13.11 | 22.4 | 0 | 无 |
| 10000 | person_long | current | 21.324 | 12.698 / 13.037 | 22.4 | 0 | 无 |
| 10000 | person_scoped | baseline | 13.73 | 4.722 / 5.006 | 15.3 | 0 | 无 |
| 10000 | person_scoped | current | 13.548 | 4.782 / 5.064 | 15.3 | 0 | 无 |
| 10000 | facts_long | baseline | 9.273 | 2.266 / 2.906 | 53.5 | 0 | 无 |
| 10000 | facts_long | current | 9.504 | 2.22 / 2.983 | 53.5 | 0 | 无 |
| 10000 | compare_long | baseline | 109.253 | 175.556 / 193.13 | 17823.2 | 0 | 无 |
| 10000 | compare_long | current | 107.497 | 171.512 / 182.598 | 17823.2 | 0 | 无 |
| 10000 | path_ordinary | baseline | 11.743 | 2.799 / 3.539 | 4.5 | 1 | 无 |
| 10000 | path_ordinary | current | 11.972 | 3.197 / 3.385 | 4.5 | 1 | 无 |
| 10000 | path_hot | baseline | 16.657 | 7.251 / 7.789 | 27.1 | 0 | evidence_limit, sql_limit |
| 10000 | path_hot | current | 16.978 | 8.23 / 8.791 | 309.1 | 10 | candidate_limit, evidence_limit, path_limit |
| 10000 | path_long | baseline | 16.752 | 8.109 / 8.858 | 27.0 | 0 | evidence_limit, sql_limit |
| 10000 | path_long | current | 24.513 | 15.881 / 16.867 | 550.0 | 10 | candidate_limit, evidence_limit, path_limit |
| 10000 | path_empty | baseline | 8.941 | 1.682 / 2.166 | 1.0 | 0 | 无 |
| 10000 | path_empty | current | 9.076 | 1.782 / 2.175 | 1.0 | 0 | 无 |
| 100000 | meta | baseline | 68.871 | 56.066 / 62.278 | 0.2 | 0 | 无 |
| 100000 | meta | current | 62.37 | 55.341 / 55.928 | 0.2 | 0 | 无 |
| 100000 | name_prefix | baseline | 7.909 | 1.4 / 1.736 | 3.1 | 0 | 无 |
| 100000 | name_prefix | current | 8.378 | 1.43 / 1.642 | 3.1 | 0 | 无 |
| 100000 | name_miss | baseline | 14.754 | 7.939 / 8.145 | 0.1 | 0 | 无 |
| 100000 | name_miss | current | 15.271 | 8.249 / 8.486 | 0.1 | 0 | 无 |
| 100000 | entity_alias | baseline | 8.381 | 1.32 / 1.541 | 0.2 | 0 | 无 |
| 100000 | entity_alias | current | 8.103 | 1.338 / 1.515 | 0.2 | 0 | 无 |
| 100000 | entity_ordinary | baseline | 14.506 | 5.766 / 6.393 | 29.6 | 0 | 无 |
| 100000 | entity_ordinary | current | 13.849 | 5.784 / 6.106 | 29.6 | 0 | 无 |
| 100000 | entity_hot_company | baseline | 13.326 | 7.331 / 10.548 | 32.2 | 0 | 无 |
| 100000 | entity_hot_company | current | 11.292 | 3.65 / 3.986 | 32.2 | 0 | 无 |
| 100000 | entity_hot_school | baseline | 10.931 | 3.032 / 3.392 | 22.5 | 0 | 无 |
| 100000 | entity_hot_school | current | 10.655 | 2.971 / 3.257 | 22.5 | 0 | 无 |
| 100000 | company_role | baseline | 35.624 | 27.564 / 28.863 | 8.5 | 0 | 无 |
| 100000 | company_role | current | 34.866 | 27.941 / 28.465 | 8.5 | 0 | 无 |
| 100000 | multi_intersection | baseline | 32.393 | 24.597 / 27.192 | 3.3 | 0 | 无 |
| 100000 | multi_intersection | current | 32.044 | 24.171 / 25.314 | 3.3 | 0 | 无 |
| 100000 | empty_intersection | baseline | 29.646 | 22.459 / 22.654 | 0.6 | 0 | 无 |
| 100000 | empty_intersection | current | 29.576 | 22.637 / 23.632 | 0.6 | 0 | 无 |
| 100000 | deep_cursor | baseline | 12.168 | 4.022 / 4.354 | 32.0 | 0 | 无 |
| 100000 | deep_cursor | current | 13.453 | 3.953 / 4.169 | 32.0 | 0 | 无 |
| 100000 | person_ordinary | baseline | 59.136 | 50.302 / 51.114 | 2.0 | 0 | 无 |
| 100000 | person_ordinary | current | 58.564 | 50.821 / 51.954 | 2.0 | 0 | 无 |
| 100000 | person_hot | baseline | 13.409 | 4.832 / 5.288 | 17.2 | 0 | 无 |
| 100000 | person_hot | current | 13.415 | 4.727 / 5.006 | 17.2 | 0 | 无 |
| 100000 | person_long | baseline | 21.842 | 13.188 / 13.43 | 22.4 | 0 | 无 |
| 100000 | person_long | current | 21.875 | 13.222 / 14.033 | 22.4 | 0 | 无 |
| 100000 | person_scoped | baseline | 13.279 | 4.779 / 5.077 | 15.3 | 0 | 无 |
| 100000 | person_scoped | current | 13.268 | 4.836 / 4.938 | 15.3 | 0 | 无 |
| 100000 | facts_long | baseline | 9.396 | 2.321 / 2.875 | 53.5 | 0 | 无 |
| 100000 | facts_long | current | 8.907 | 2.326 / 2.85 | 53.5 | 0 | 无 |
| 100000 | compare_long | baseline | 111.264 | 174.749 / 190.981 | 17823.2 | 0 | 无 |
| 100000 | compare_long | current | 110.233 | 173.505 / 182.556 | 17823.2 | 0 | 无 |
| 100000 | path_ordinary | baseline | 13.599 | 2.905 / 4.194 | 4.5 | 1 | 无 |
| 100000 | path_ordinary | current | 11.438 | 2.91 / 3.527 | 4.5 | 1 | 无 |
| 100000 | path_hot | baseline | 15.73 | 7.543 / 7.968 | 27.1 | 0 | evidence_limit, sql_limit |
| 100000 | path_hot | current | 17.176 | 8.635 / 8.903 | 309.1 | 10 | candidate_limit, evidence_limit, path_limit |
| 100000 | path_long | baseline | 16.371 | 8.255 / 8.451 | 27.0 | 0 | evidence_limit, sql_limit |
| 100000 | path_long | current | 26.25 | 16.256 / 17.318 | 550.1 | 10 | candidate_limit, evidence_limit, path_limit |
| 100000 | path_empty | baseline | 13.309 | 3.343 / 5.43 | 1.0 | 0 | 无 |
| 100000 | path_empty | current | 9.024 | 1.699 / 2.092 | 1.0 | 0 | 无 |

## 数据与完整性

- 10000 人：`{'people': 10000, 'facts': 53521, 'seed': 42, 'profile': 'scale-v1', 'logical_sha256': '3d03d0770228b6626d3f5e27f81fe53dcb82714dd64ce817d5d2ceb87506c2d1', 'generation_ms': 884.82, 'database_bytes': 13561856}`
- 分布：`{'active_people': 9896, 'active_facts_on_active_people': 52168, 'unknown_employment_dates': 7502, 'per_person_active_facts': {'p50': 4, 'p95': 9, 'p99': 30, 'max': 121}, 'active_entity_people': {'employment': {'p50': 30, 'p95': 39, 'p99': 45, 'max': 6415}, 'education': {'p50': 49, 'p95': 60, 'p99': 63, 'max': 4960}}, 'sqlite_pragmas': {'page_size': 4096, 'cache_size': -2000, 'journal_mode': 'delete'}, 'indexes': [{'name': 'ix_demo_entity_name', 'sql': 'CREATE INDEX ix_demo_entity_name ON demo_entity (name)'}, {'name': 'ix_demo_entity_type', 'sql': 'CREATE INDEX ix_demo_entity_type ON demo_entity (type)'}, {'name': 'ix_demo_fact_company_role', 'sql': 'CREATE INDEX ix_demo_fact_company_role ON demo_fact (entity_id, role_id, active)'}, {'name': 'ix_demo_fact_entity', 'sql': 'CREATE INDEX ix_demo_fact_entity ON demo_fact (entity_id, active, person_id)'}, {'name': 'ix_demo_fact_person', 'sql': 'CREATE INDEX ix_demo_fact_person ON demo_fact (person_id, active, entity_id)'}, {'name': 'ix_demo_person_name', 'sql': 'CREATE INDEX ix_demo_person_name ON demo_person (name)'}, {'name': 'sqlite_autoindex_demo_entity_1', 'sql': None}, {'name': 'sqlite_autoindex_demo_entity_alias_1', 'sql': None}, {'name': 'sqlite_autoindex_demo_fact_1', 'sql': None}, {'name': 'sqlite_autoindex_demo_person_1', 'sql': None}, {'name': 'sqlite_autoindex_demo_person_source_1', 'sql': None}]}`
- 数据库查询前后摘要相同：True
- 100000 人：`{'people': 100000, 'facts': 531013, 'seed': 42, 'profile': 'scale-v1', 'logical_sha256': '153cb22fbb5af68655bc11ae2f531418c51757df47dd7a75889a1875676534cf', 'generation_ms': 9842.4, 'database_bytes': 133697536}`
- 分布：`{'active_people': 98969, 'active_facts_on_active_people': 516951, 'unknown_employment_dates': 73833, 'per_person_active_facts': {'p50': 4, 'p95': 9, 'p99': 30, 'max': 122}, 'active_entity_people': {'employment': {'p50': 299, 'p95': 330, 'p99': 338, 'max': 63363}, 'education': {'p50': 496, 'p95': 537, 'p99': 549, 'max': 49400}}, 'sqlite_pragmas': {'page_size': 4096, 'cache_size': -2000, 'journal_mode': 'delete'}, 'indexes': [{'name': 'ix_demo_entity_name', 'sql': 'CREATE INDEX ix_demo_entity_name ON demo_entity (name)'}, {'name': 'ix_demo_entity_type', 'sql': 'CREATE INDEX ix_demo_entity_type ON demo_entity (type)'}, {'name': 'ix_demo_fact_company_role', 'sql': 'CREATE INDEX ix_demo_fact_company_role ON demo_fact (entity_id, role_id, active)'}, {'name': 'ix_demo_fact_entity', 'sql': 'CREATE INDEX ix_demo_fact_entity ON demo_fact (entity_id, active, person_id)'}, {'name': 'ix_demo_fact_person', 'sql': 'CREATE INDEX ix_demo_fact_person ON demo_fact (person_id, active, entity_id)'}, {'name': 'ix_demo_person_name', 'sql': 'CREATE INDEX ix_demo_person_name ON demo_person (name)'}, {'name': 'sqlite_autoindex_demo_entity_1', 'sql': None}, {'name': 'sqlite_autoindex_demo_entity_alias_1', 'sql': None}, {'name': 'sqlite_autoindex_demo_fact_1', 'sql': None}, {'name': 'sqlite_autoindex_demo_person_1', 'sql': None}, {'name': 'sqlite_autoindex_demo_person_source_1', 'sql': None}]}`
- 数据库查询前后摘要相同：True

默认演示库保持不变：True

每次请求的阶段、SQL 模板、参数、EXPLAIN QUERY PLAN、样本和结果数量均保存在 report.json；错误与外部观察预算会明确记录，不算作正常空结果。
