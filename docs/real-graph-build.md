# 真实跨库关系图构建记录

2026-11-11，对应主架构v0.41，基准月202611。

## 交付

独立图空间为 `relationship_lab_sync_2d1b24919065`，版本为 `real-2a106af85a3330dba3c2-202611`。本机NebulaGraph 3.8.0已完成事实写入、四类人物关系物化、完整回读与独立SQL证据核对。图空间和GUEST只读账号保留供后续使用。

实体及映射来自 `47.113.185.127:3306/test_derui_expert`。人物及原经历来自用户更正后的 `39.96.40.93:3306/expert_recommend_real_staging_run_20260713_145630_15247`。每个来源独立建立只读一致性快照，记录服务器UUID、时间、TLS证书摘要和数据文件摘要。人物与经历读取范围为当前权威映射引用的全部原行。

| 对象 | 数量 |
| --- | --- |
| 专家人物 | 6525 |
| 公司／学校／专业节点 | 10287／1821／693 |
| 总节点 | 19326 |
| 任职／就读／专业事实 | 12272／7606／5361，总计25239 |
| 同公司／同公司同期证据 | 23780／4502 |
| 同校／同专业证据 | 91487／212014 |
| 人物关系证据 | 331783，对应257775个去重人物对 |

当前映射全部为expert。简历关系构建需要上游交付对应映射。人物姓名存于配套SQL，图人物属性为source_system和serial_number。

## 数据处理与责任

graph_edge_mapping继续由同事维护，事实Rank保留上游id。新增版本化numeric-authoritative-v2，支持同一原字段的多个目标各保留自己的Rank。重复的同目标事实继续阻断。最终60个多目标字段保留121条事实，时间、职位、教育信息沿用各自原经历。

| 输入情况 | 本轮处理 |
| --- | --- |
| 70个人物ID缺失，涉及233条映射 | 隔离并保存Rank／人物／原行定位 |
| 3条倒置日期、4条超出既有年月范围的日期 | 隔离，保留原始记录 |
| 304个MySQL零日期 | 在本机规范化为未知NULL，源快照保留原值 |
| 已删除人物的2570条映射 | 按有效性规则退出图事实 |
| 任职状态0 | 源值保留，当前标志仅在1确认，0缺截止日时保持未知截止 |
| 已合并学校22／专业8 | 按非活跃实体处理 |

源库读取使用只读事务。采集时显式选择关闭证书链核验并保留TLS，正式接入证书配置仍需匹配。两个来源属于各自的数据库快照，跨库同一业务发布版本需要上游协议进一步约定。

## 验收

- 图中人物关系由nGQL生成。完整回读19326节点及357022条边，与计划／构建摘要一致。
- 独立SQL事实自连接逐条核对四类人物证据的双方人物、实体、左右事实Rank及同期月份，四类全部通过。
- GUEST账号调用现有图查询仓储，真实小邻域1至4跳的完整候选与SQL事实BFS一致。每条样例链按原SQL任职事实核对各段。
- 四跳样例为 `p:expert:1076 → p:expert:1075 → p:expert:41256 → p:expert:1200 → p:expert:1171`。
- 后端523通过／247跳过，新增9项。Ruff与Mypy通过，旧UUID真实MySQL／图专项6通过／3跳过。

完整构建及独立核对耗时95.867秒。单个真实小邻域1至4跳顺序观察约23.7／25.4／30.0／79.5毫秒，代表范围为本机该样例。热门实体和生产并发容量仍需独立压测。

本轮构建预算为按有效事实计算的完整保守上界357515条人物证据。共享构建器与回读器支持显式预算，既有默认10000保持兼容。

## 文件与复核入口

全部运行材料位于 `data/real-graph/run-v1`，目录700、私有文件600。

- `entity-source.json`、`person-source.json` 为两源原始冻结输入及元数据。
- `build-v1/input-audit.json` 提供隔离记录及零日期转换定位。
- `build-v1/source.sqlite` 为配套只读SQL及查询读模型，`contract.json` 保存实际字段和状态契约。
- `build-v1/prepared.json` 固定输入与产物摘要，`graph-plan.json` 保存图事实计划。
- `build-v1/manifest.json` 为真实构建清单，`query-validation.json` 为GUEST多跳验收，`distribution.json` 为有效图事实分布。
- `build-v1/graph/reader-credentials.json` 保存本次只读账号材料。

重复完整采集时使用新的输出目录，密码通过交互输入。

```bash
backend/.venv/bin/python scripts/capture_real_graph_sources.py \
  --output data/real-graph/<新输入目录> \
  --person-database expert_recommend_real_staging_run_20260713_145630_15247 \
  --insecure-tls

backend/.venv/bin/python scripts/build_real_graph.py \
  --input data/real-graph/<输入目录> \
  --output data/real-graph/<新构建目录> --prepare-only

backend/.venv/bin/python scripts/build_real_graph.py \
  --output data/real-graph/<已准备构建目录> --build-prepared

backend/.venv/bin/python scripts/verify_real_graph_queries.py \
  --output data/real-graph/<已构建目录>
```

采集中断后可用--resume复用已经完整冻结的来源文件。已有构建目录中的图写入仅执行一次，构建失败时按build-resource.json定位本次空间，后续尝试使用新目录。新的查询验收写入独立报告文件。

本轮产物格式为real-graph-build-v1。HTTP真实数据模式及前端真实来源切换继续待接入，持续CDC调度、双源业务就绪边界及完整简历映射覆盖继续待验证。
