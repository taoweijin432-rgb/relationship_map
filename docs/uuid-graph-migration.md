# UUID 人物关系图迁移与运行验收

2026-11-06 ｜架构 v0.24 ｜模型 uuid-relations-v5 ｜全部人物和履历为虚构数据

用户授权按已确认的节点／边方案修改当前使用的图。采用独立 SQL 模拟库和新图空间，完整回读及查询验收后切换激活指针；旧库、旧空间和历史清单保持不变。本轮没有访问 Supabase。

## 当前运行对象

| 项目 | 本轮结果 |
| --- | --- |
| 模型 | uuid-facts-v3.ngql + person-relations-v3.ngql = uuid-relations-v5 |
| 新图空间 | relationship_lab_uuid_b19a220c6635 |
| 新 MySQL 模拟库 | relationship_lab_handoff_e7d11a446004 |
| 版本／投影 | uuid-v5-ebfa6f27340364ef46eb-202611 |
| 基准月 | 202611 |
| 本地清单 | data/uuid-graph-trial/run-v1/manifest.json，format_version=3 |
| 激活目录 | data/source-release-trial/rehearsal-v1/store，切换至修订 6 |
| 上一版本 | data/source-api-trial/run-v2，原 SQL／图保留 |
| 访问 | http://127.0.0.1:5173/；http://127.0.0.1:8000/docs |

63 个有效来源人物节点（专家 18、简历 45），不是去重后的 63 个自然人；人物按来源保留身份，不自行识别跨库同人。

| 图内容 | 数量 |
| --- | ---: |
| person | 63 |
| company／school／major | 7／5／3 |
| 业务节点合计 | 78 |
| 控制节点 projection_meta | 1 |
| 三类经历事实边合计 | 178 |
| same_company | 285 |
| company_overlap | 255 |
| same_school | 325 |
| same_major | 1711 |
| 人物证据边合计 | 2576 |
| 全部边合计 | 2754 |

边数量是经历对证据数，不是去重人物对数。同期边是同公司边的子集，不能相加计分。学校和专业两个事实可指向同一条教育记录，178 条事实不等于 178 段不同履历。

## 实际构建与查询

新空间直接执行已确认的 DDL。person 仅写 source_system、serial_number；公司／学校／专业写标准名和业务 code。工作事实写原始职位、月份、在职状态和 experience_key；教育两类事实写学历、统招原文、月份与相同教育行的 experience_key。事实 Rank 保留映射 id。

构建器先写 staging、有效节点和事实，再用 nGQL 从共同实体计算四类人物边。Python 只编排、分配快照局部人物边 Rank 和写入，不在构建器重算人物关系或时间交集。依据有效当前任职的空结束时间在计算时使用基准月，不回写结束属性。

本轮保守估计的经历对上界为 2608，小于 10000 条构建预算。实际关系全部生成，回读全部节点／事实／人物边并核对摘要，再标 ready。预算不足直接拒绝发布，不截断后声称完整。新建 GUEST 账号供 API 读取，密码只在忽略目录的 600 权限文件中，不在文档、日志或接口返回。

新模式的相关人物列表、关系证据、两人对比、展开及当前页关系导出均读取物化人物边。图返回 VID 和双方事实 Rank；SQL 读取人物、原工作／教育行并核对归属、目标和事实属性，然后批量补充姓名与展示字段。最多一位中间人物的路径遍历两条已保存的人物边，每段分别提供事实依据。SQL 不为新模式召回关系候选，Python 不重新判定关系。

实体组合筛选继续使用 SQL，原始职位精确多选与公司／任职时间约束同一工作经历。新增专业筛选／专题、同专业关系和图例；不建设标准职位节点，不按专业代替职位。人物可按姓名、人物键或业务编号定位。页面上的姓名来自 MySQL，不回写图。

同公司查询会展示对应同期证据，但相同经历对的同公司基础边不会重复显示成第二条关系。存储中两种边均保留；没有时间交集的经历对仍保留同公司证据。同专业不推断同校、同期或实际认识。

## SQL 模拟层的准确范围

一次性迁移输入是已冻结的历史虚构 SQL 库、其显式 UUID 对照及本地归一模拟样例：

- data/source-api-trial/run-v2：旧服务冻结来源，只读。
- data/projection-source-trial/run-v4/bridge-ledger.json：恢复原先明确的 UUID 对照，不按名称猜测。
- data/handoff-trial/run-v3/source-snapshot.json：明确标准实体的 UUID、名称与 code。

新库复制八张原人物／经历模拟表，建立三张 UUID 标准表的最小字段子集及 graph_edge_mapping。映射目标使用 UUID，映射 id 仍为 BIGINT；不恢复废弃的独立实体／别名字典或生产 UUID→BIGINT 桥接。历史对照文件只是一次性迁移输入。

**这是 12 张本地冻结模拟表的接入适配，不是最新文档 15 张表的完整生产适配。** 三张标准表本轮仅模拟 id、名称、code、is_deleted；不将其临时物理定义当作正式上游 DDL。名称归一、跨库身份和既有映射接受结果来自已验证虚构来源，不在本系统重新识别。graph_name_mapping、graph_sync_batch、graph_company_relation 的正式状态和发布规则尚未接通；未来必须核对已匹配＋is_deleted=0、完整批次与删除通知，不能将本轮映射复制视作这些契约已验证。

新模拟层暂只提供标准名称检索，没有迁移旧独立别名表。实体更名／别名搜索需等正式字段和样本接入；UI 已将此模式的提示改为标准名称。项目与标准职位的旧边不迁入新图，项目原表只是保留来源快照，不参与关系。原职位文字仍可筛选和展示。

## 验证证据

主要入口：backend/tests/test_uuid_graph.py、frontend/tests/uuid-graph.spec.ts。

- 12 项离线预检：姓名白名单、教育同源分组、原 Rank、重复／冲突 ID、错误归属／类型、日级逆序、当前任职矛盾、业务编号缺失和失效过滤；不修改输入。
- 25 项显式本机专项（含上述 12 项预检）：从原始 JSON 行及明确映射编写独立朴素基准，不调用生产适配、关系或日期计算函数；核对全部 2576 条人物证据边、局部 Rank、五类关系选择的全部分页、正反向证据、202112—202201 两个月的窗口、非同期／未知、三类路径、同条经历、对比、导出、图截断和列表完整性，并验证图故障明确 503、不回退 SQL，以及业务编号定位。
- 专项通过 monkeypatch 禁止 SQL 关系候选和 Python build_evidence，证实新模式不依赖旧关系计算。图的完整回读摘要与本地记录一致，再和独立原表基准比对。
- 最终 `bash scripts/check.sh` 通过：Ruff、mypy、后端 408 项通过／225 项显式环境用例跳过，前端格式、类型与构建通过，默认演示浏览器 18 项通过／15 项其他模式跳过。新模式另外 3 项浏览器测试通过：同专业及业务编号、公司＋原职位与专业专题保存恢复、履历对比及图路径逐段证据。实际截图已检查，来源记录和图都正常显示。TestClient 弃用和既有 G6 产物体积提示仍存在，不影响本轮检查通过。
- 第一次浏览器职位用例在选项生成前直接按回车，没有提交职位；改为等待并明确选择生成选项，断言已选职位后验证请求结果，三项重跑通过。没有修改查询预期。

本地原始记录：data/uuid-graph-trial/run-v1/report.json、migration-inputs.json、source-snapshot.json、graph-nodes.json、graph-edges.json、native-final-tests.xml、regression-final.log、browser-release.json、browser-release/ 和 runtime-meta.json。其中 source-snapshot 含虚构姓名，graph-nodes／graph-edges 的人物载荷无姓名。最终汇总见 docs/data-sources/uuid-graph-migration-v024.json。

构建实际耗时 22.464 秒；最终 25 项原生专项一次运行 4.19 秒，新图浏览器 3 项 10.1 秒。它们是本机小样本顺序演练，包含不同阶段等待，不是单查询延迟、生产并发或百万级容量证明。恢复服务后已通过真实 HTTP 核对元数据为 uuid-relations-v5／nebula-materialized；旧版本也已只读重新完整验证，仍可回退。

## 启动、停止和回退

在项目根目录，保持本机 MySQL 和 Nebula 容器运行，清除其他模式的配置后启动：

```bash
unset RELATIONSHIP_DATABASE RELATIONSHIP_MYSQL_URL RELATIONSHIP_NEBULA_MANIFEST RELATIONSHIP_GRAPH_ENGINE
unset RELATIONSHIP_SOURCE_API_MANIFEST RELATIONSHIP_SOURCE_API_MYSQL_URL
RELATIONSHIP_SOURCE_RELEASE_STORE="$PWD/data/source-release-trial/rehearsal-v1/store" bash scripts/dev.sh
```

Ctrl+C 停止这条命令创建的前后端进程。旧服务若占用端口会明确失败，不终止其他服务。未配置以上变量时，原有 `bash scripts/dev.sh` 仍启动默认 SQLite 演示，不会自动加载新图。

必须先停服，再回退激活指针，再用同一启动命令重启：

```bash
backend/.venv/bin/python scripts/source_release.py rollback --store data/source-release-trial/rehearsal-v1/store
```

回退后若要重新启用本轮图，停服执行：

```bash
backend/.venv/bin/python scripts/source_release.py activate --store data/source-release-trial/rehearsal-v1/store --release data/uuid-graph-trial/run-v1
```

切换前重新核对新旧完整 SQL／图；运行期间 pin 固定激活修订，指针漂移返回 409。故障不静默回退其他查询引擎。重建演练需新目录：

```bash
backend/.venv/bin/python scripts/migrate_uuid_graph.py \
  --source-bundle data/source-api-trial/run-v2 \
  --bridge data/projection-source-trial/run-v4/bridge-ledger.json \
  --normalized data/handoff-trial/run-v3/source-snapshot.json \
  --output data/uuid-graph-trial/my-new-run
```

该命令只适合迁移历史虚构来源；不接受 Supabase、生产库或未知最新数据。失败不会发布可激活的半成品；已创建的隔离实验资源保留供检查，不自动删库或旧空间。

## 仍未验证

正式 15 表契约、完整数据与批次、名字权限和字段脱敏、生产登录／授权、增量修正与旧边清理、生产监控／备份／恢复、热门实体平方级关系容量均未完成。新模式每请求完整校验单表不超过 10000 行的冻结 SQL，是本地验收保护，不能照搬生产。

相关人物列表当前最多读取 1000 个图关联人物作 SQL 背景筛选，证据每人物对／类型最多探测 1001 条；超限返回明确错误，不伪装完整结果。路径仍保留 RPC／返回行／事实／时间和展示预算，LIMIT 和 SDK 超时不等于图服务端扫描限制或即时取消。生产需要代表性分布重评索引、分页、构建分片和读写隔离。

旧图保留的是历史虚构姓名结构，只用于历史回退；本轮没有清理全部旧图、凭据、备份或日志，不宣称历史数据都满足新隐私规则。新生产来源不得使用旧 writer。
