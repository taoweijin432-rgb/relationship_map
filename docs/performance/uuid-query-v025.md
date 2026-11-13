# UUID 关系查询性能改造与验证

2026-11-09 ｜架构 v0.25 ｜图模型 uuid-relations-v5 ｜本机虚构数据

本轮完成轻量发布版本检查、批量图取证、图候选游标分页，沿用现有关系规则、SQL 回查和人物隐私字段。运行配置采用新的本机 SQL 实验库及只读账号，图复用已完整验证的不可变空间。规模样例使用另一套独立 SQL／图资源。

## 相同数据的前后观察

63 个有效来源人物、15 个标准实体、178 条事实、2576 条人物证据边。改造前后使用相同冻结内容及图，三场景的首轮完整 JSON 响应对照通过，游标按新版查询规则重新生成。每场景顺序执行 7 次，记录中位数。

| 场景 | 改造前中位数 ms | 改造后中位数 ms | SQL 语句数前→后 | 图执行调用数前→后 |
| --- | ---: | ---: | ---: | ---: |
| 参考人物全部关系首屏20人 | 306.377 | 132.686 | 44→11 | 88→20 |
| 同专业首屏20人 | 129.975 | 61.329 | 44→11 | 26→9 |
| 两人完整对比 | 70.511 | 43.012 | 44→11 | 9→9 |

计时使用 FastAPI TestClient 顺序 ASGI 请求，启动及启动时完整对账单独执行。SQL 计数来自 SQLAlchemy before_cursor_execute，图计数来自 GraphClient.execute。SDK 建连、认证和内部探测产生的流量计入耗时，调用数采用上述应用层定义。测试环境为本机 MySQL 9.7.1、NebulaGraph 3.8.0，Python 使用 backend/.venv，结果用于本轮方法比较。

原始数据保存在 data/uuid-query-performance/before-v024、after-v025。benchmark_uuid_query.py 支持冻结响应对照与新目录输出。首次样本、缓存状态及系统负载均保留自然运行状态，生产并发容量需要代表性负载测试。

## 轻量版本检查

新清单 format_version=4、sql_guard=mutation-sequence-v1，图 schema_version 保持 uuid-relations-v5。发布工具建立本机项目辅助表 relationship_release_guard，记录源摘要、数据版本、基准月、状态及变更序号。12 张来源表各有 AFTER INSERT／UPDATE／DELETE 触发器，共36个，源写入与序号变化在同一事务提交或回滚。

发布和启动完整读取源、检查数据规则并核对摘要。正常请求前后，以及图取证借用 SQL 会话时，读取固定一行发布标记并核对激活指针。已提交 DML 会导致后续请求返回 SOURCE_VERSION_MISMATCH 409，未提交和已回滚写入遵守 MySQL 事务可见性。

新查询账号仅有本实验库 SELECT 权限，启动通过 SHOW GRANTS 检查实际授权。专项验证即使主动使用 writable=True 打开连接，UPDATE、TRUNCATE 和 DROP TRIGGER 仍受数据库权限阻止。控制表和触发器由发布工具维护。管理员 DDL 属于受控发布操作，执行后需要停服、完整对账和重新发布，DML 标记的检测范围是 INSERT、UPDATE、DELETE。

format_version=3 继续执行原完整快照校验，可作为旧发布配置回退入口。新发布使用独立 SQL 库，既有已发布库保持原格式。正式上游接入需要重新确认批次和变更契约，再确定生产发布标记机制。

## 批量取证

将人物对按8对一组、按关系类型合并成 UNION ALL 查询。每个分支保留独立 ORDER BY、LIMIT 和溢出探测，返回后逐对核对端点及配额。同一对的多条证据、反向读取、共同时间窗及同公司／同期子集去重继续沿用原规则。

事实按原 Rank 批量回读并与 SQL 属性核对，SQL 负责姓名和经历展示。图中人名白名单规则与四类预计算关系定义保持原约定。

每个 RPC 继续以剩余预算配置独立 SDK 池，批量查询减少连接与认证次数。跨 RPC 长连接复用需要单独验证 SDK 超时和并发边界。

## 候选游标分页

图以稳定人物 ID 去重排序，每次读取128名候选及1名探测项。SQL 对候选批次执行背景筛选，按类别组合规则补足当前页和下一条探测结果。筛选较稀疏时继续读下一批，当前页达到需求或图候选读取完成时返回。

分页游标仍绑定条件、参考人物和数据版本，并加入 materialized-cursor-v2 查询规则。旧规则游标返回明确错误，保存条件重新查询第一页后可继续使用。单对资格检查直接在图验证该人物对，SQL 提供候选背景筛选。

单页保持5秒业务阶段预算及现有图返回行／调用数边界，预算不足返回明确错误。图候选可跨越原1000人界限，单条证据上限和画布上限分别保留。LIMIT 和 SDK 超时的服务端执行效果仍需在正式环境观察。

## 1100候选规模样例

独立星形样例有1101个人物、1100家公司、2200条工作事实、1100条同公司及1100条同期人物证据边，共4400条边。中心人物分别在1100家公司有经历，每家公司关联中心人物和一名候选，所有关系完整构建并回读核对。该分布用于验证高关联度中心的查询分页。

接口验收连续22页、每页50人，1100名候选与人工生成的完整预期列表一致。每17名候选设置一个入选职位，65名匹配人物分两页返回，并完整核对。另有离线1139候选测试，覆盖失效人物及前1100名均不匹配背景条件的情况。

| 1100候选场景 | 中位数 ms | SQL 语句数 | 图执行调用数 |
| --- | ---: | ---: | ---: |
| 全部关系首屏20人 | 305.215 | 11 | 18 |
| 稀疏职位筛选首屏50人 | 812.979 | 17 | 41 |
| 中心与一名候选完整对比 | 113.109 | 11 | 7 |

原始记录位于 data/uuid-query-performance/scale-observation-v1。热门公司、学校和专业造成的平方级人物边构建需要独立分布与容量测试。本轮完整构建预算仍为10000条人物证据边，源启动预检继续采用单表10000行边界。

## 回归与操作

backend/tests/test_uuid_query_performance.py 新增稀疏分页、旧游标、批次取证配额、请求期间整库读取禁止、SQL只读权限、36个DML标记及回滚、提交变更拒绝和1100候选接口测试。与原新图专项组合运行34项通过，最终只读复核32项通过、2项变更库用例按环境配置跳过。变更演练专用 mutation-v1 末尾提交了明确虚构纠正，保留其版本冲突状态供检查。

最终完整检查通过Ruff、mypy、后端411项、前端格式／类型／构建和默认浏览器18项。默认运行跳过231项显式环境后端用例及15项其他模式浏览器用例，新图专项另行执行。优化后在线工作台的3项浏览器验收通过，结果保存于data/uuid-query-performance/browser-v025.json。docs/performance/uuid-query-v025.json保留测试和计时汇总。

当前工作台已在发布修订7激活轻量校验配置，并通过真实HTTP核对同专业首屏20人与下一页标记，运行记录保存于data/uuid-query-performance/runtime-v025.json。

启动当前激活配置仍使用项目根目录命令，先清除其他来源配置并确认开发端口可用。

```bash
RELATIONSHIP_SOURCE_RELEASE_STORE="$PWD/data/source-release-trial/rehearsal-v1/store" bash scripts/dev.sh
```

本轮查询配置目录为 data/uuid-query-performance/guarded-v1，SQL 库为 relationship_lab_handoff_146435a232a0，图复用 relationship_lab_uuid_b19a220c6635。规模库和变更演练库各自独立。切换／回退继续使用 source_release.py，操作前先停止前后端。回退发布配置后仍运行当前代码，查询游标按当前规则生成。

重建独立实验和计时入口如下，输出目录须另取新值。

```bash
backend/.venv/bin/python scripts/uuid_query_lab.py --source-bundle data/uuid-graph-trial/run-v1 --output data/uuid-query-performance/my-guarded-run
backend/.venv/bin/python scripts/uuid_query_lab.py --size 1100 --output data/uuid-query-performance/my-scale-run
backend/.venv/bin/python scripts/benchmark_uuid_query.py --input data/uuid-query-performance/my-guarded-run --output data/uuid-query-performance/my-observation --baseline data/uuid-query-performance/before-v024
```
