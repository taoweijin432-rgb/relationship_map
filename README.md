# 经纬人物关系查询系统

消费上游归一实体及映射，实现人物关系查询、经历证据展示和夜间版本化更新。人物身份、跨库重复及实体归一由上游维护。主架构及修订记录在本地 `docs/query-system-architecture.md` 持续维护，`docs/` 由本地保存。程序使用的构建契约、测试样本及OpenAPI输入随源码保存于 `resources/`。

## 提测代码基线

提测标签为 `qa-20261113-02`，当前部署与验收记录为 `v0.59.3`。代码版本使用Git提交号及提测标签标识，可以在源码目录读取。

```bash
git rev-parse HEAD
git show --no-patch qa-20261113-02
```

每次提测记录对应的提交号和标签，缺陷修复形成后续提交及提测标签。前端由服务器使用 `frontend/package-lock.json` 构建，后端依赖由 `backend/uv.lock` 固定。部署说明记录对应的前端入口和实际关系数据版本。

## 测试环境

以下状态记录于2026年11月13日。

| 项目 | 已验收配置 |
| --- | --- |
| 测试入口 | http://121.43.176.65:8088/ |
| 应用目录 | `/srv/relationship-map` |
| 图服务 | NebulaGraph 3.8.0，图服务器内网地址 `172.16.0.154`，与测试Milvus共机 |
| 应用侧图入口 | SSH服务转发至 `127.0.0.1:19669` |
| API入口 | `127.0.0.1:8000`，由Nginx的 `/api/` 转发 |
| 实体及映射来源 | `47.113.185.127 / test_derui_expert` |
| 人物及经历来源 | `39.96.40.93 / expert_recommend_real_staging_run_20260713_145630_15247` |
| 已验收关系版本 | `real-921e1ee2e6476b0925bb-202611` |
| 发布数据量 | 6711专家、0简历人物、14355实体、27715事实 |
| 人物展示模式 | `mysql-live` |
| 当前静态目录 | `frontend/dist-layout-v059-label-fix` |
| 前端入口 | `/assets/index-B_uaB6X5.js` |
| 图组件 | `/assets/GraphCanvas-6K1ga1Xw.js` |

实际人物展示字段在线读取MySQL。人物关系由NebulaGraph提供，背景筛选和经历证据使用同一发布的SQLite事实读模型。关系版本、图空间和统计以当前发布清单及API元数据为准。

2026年11月16日测试服图容器已按终端反馈调整为10GiB／2CPU，当前API关系版本为`real-1e464b2951851301adc2-202611`，6711专家、14364实体、27728事实。对应x86_64部署模板为`infra/nebula/compose.test.yaml`；`infra/nebula/compose.yaml`继续作为本机ARM64实验配置。

48a1adb的有界独占会话、多跳导出连接链复用及进程内ID缓存已完成测试服激活和指定样例验收。后续连接预算、异步准入及查询复用改造已在本机分批提交，尚未部署服务器。缓存默认8MiB、最多1024条、每条不超过128KiB、TTL300秒，仅保存图ID结果；设置`RELATIONSHIP_RELATION_CACHE_BYTES=0`可关闭存储，配置范围0至64MiB。人物展示及删除检查继续在线查询MySQL，图版本核对保持执行。新页首次仍可能读取图，缓存不改变背景筛选和分页顺序。

## 查询调度配置

本地新版本点选人物使用`POST /api/v1/persons/{id}/details`，一次返回经历、参考人物及指定条件下的关系证据／连接链。装配内复用人物与事实读取，返回前批量重读在线人物；人物在查询中变化时明确返回`PERSON_SOURCE_CHANGED`，请重新查询。人物数据不跨请求缓存。独立`facts`接口继续用于画布悬停及恢复参考人物，独立取证接口供单独取证与工具调用；前端点选人物已移除原先并行调用这两个接口的路径。此改动尚未部署测试服，前后端需按同一Git版本升级。

新异步入口仅支持当前单API进程部署，继续使用Uvicorn的`--workers 1`。内部受限线程和队列参数通过环境变量设置，以下是本机验证的保守起点，测试服容量仍需实测：

```ini
RELATIONSHIP_ADMISSION_WORKERS=4
RELATIONSHIP_ADMISSION_HEAVY=1
RELATIONSHIP_ADMISSION_LIGHT=3
RELATIONSHIP_ADMISSION_HEAVY_QUEUE=2
RELATIONSHIP_ADMISSION_LIGHT_QUEUE=8
RELATIONSHIP_ADMISSION_QUEUE_SECONDS=0.3
RELATIONSHIP_ADMISSION_INFLIGHT=16
RELATIONSHIP_ADMISSION_FOLLOWERS_PER_KEY=4
RELATIONSHIP_ADMISSION_FOLLOWERS=8
RELATIONSHIP_QUERY_LOG_LEVEL=INFO
```

4个内部线程中保留1个健康／元信息通道。默认重计算最多1项、普通轻操作最多2项，健康通道最多1项；调大重计算数也不会突破总体限制。普通在途上限包括响应发送阶段，健康请求另有最多3个在途及2个等待的上限。队列满或等待超过300ms返回`503 GRAPH_BUSY`和`Retry-After: 1`，客户端应避免并行自动重试。

请求体上限1MiB。调度、回源、SQL／图和装配共用入口起算5秒预算，子查询不能重新起算；路径入口仍可使用更小的业务预算并返回明确受限状态。阻塞驱动采用协作取消，HTTP超时不等于线程已停止，名额在工作实际结束后归还。启动完整核验和夜间构建不套用交互预算；退出先排空线程，再关闭SQL和图连接。日志记录请求ID、共享任务ID、阶段计时和拒绝原因，`RELATIONSHIP_QUERY_LOG_LEVEL=WARNING`可降低日志量。

## 已实现的查询与展示

- 支持从人物查关联人物，以及按公司、学校、专业和任职职位等条件筛选人物。
- 支持同公司、同公司同期、同校和同专业关系，同专业查询可选择已有同校关系作为前提。
- 单人物关联查询支持1至4跳，两人连接链入口支持最多一位中间人物。
- 人物候选按姓名或业务编号前缀检索，每批最多50条，候选范围为已发布有效人物。
- 图按人物连接摘要分层，点击人物可聚焦已验证证据链，并可恢复全图。聚焦姓名单行侧置，实体名称及关系文字按需显示。
- 支持证据详情、设为查询中心、展开、分页、保存条件，以及JSON、CSV和PNG导出。
- 画布上限为100节点、200边，列表提供继续分页。

实际公网已核对人物1000的全部共同经历四跳样例，返回20位人物、62节点、64边，图未截断。聚焦恢复、标签开关、PNG下载和390像素窄屏触摸详情通过，页面错误为空。验证范围和容量待验项见主方案。

## 运行配置与服务

人物搜索诊断使用`backend/.venv/bin/python scripts/profile_people_search.py --output <私有报告路径>`，读取现有在线MySQL环境与夜间配置，或显式指定`--source-config`和`--release`。它捕获实际运行SQL，再执行只读EXPLAIN／ANALYZE，输出扫描算子、候选分页和发布成员命中计数；不打印人物字段或搜索原文，不改来源表／索引。报告绑定当次发布版本；本机冻结发布配上当前来源时，不能冒充服务器当前发布。真实计划未取得前，不据此宣称搜索已使用或绕过索引。

本地Nginx候选模板`infra/nginx/relationship-map-nightly.conf`已补充JS／CSS／JSON压缩、带hash资源长期缓存及HTML重验证，API明确`no-store`，保留业务503与维护503的区别。测试服尚未安装这轮配置。部署时保留服务器实际`root`、监听端口及其他站点设置，先暂存并通过`nginx -t`，再reload。

前端继续在服务器构建独立候选目录。切换Nginx前，使用`backend/.venv/bin/python scripts/retain_frontend_assets.py --previous <当前静态目录> --candidate <新构建目录>`保留旧页面依赖的分包；工具不会替换候选HTML或覆盖不同内容的同名资源。默认合并上限256MiB／10000文件，超限明确失败，需要评估历史资源后再交付，不自动删除旧分包或改动当前服务目录。

服务器私有配置位于 `/etc/relationship-map`。

| 配置文件 | 用途 |
| --- | --- |
| `query.env` | `RELATIONSHIP_NUMERIC_RELEASE_STORE` 指向实际发布目录 |
| `mysql-sources.json` | 实体与人物两个逻辑角色的物理连接配置 |
| `mysql.env` | 在线MySQL环境配置及密码环境变量，权限为600 |
| `nightly.json` | 来源配置引用、夜间窗口、发布及保留参数 |

`relationship-graph-tunnel.service` 托管图服务转发，`relationship-query.service` 托管查询API，Nginx提供网页及API代理。应用服务器上的启动和只读检查命令如下。

```bash
systemctl start relationship-graph-tunnel.service
systemctl start relationship-query.service nginx
systemctl status relationship-query.service --no-pager
curl -fsS http://127.0.0.1:8088/api/v1/health
curl -fsS http://127.0.0.1:8088/api/v1/meta
systemctl list-timers relationship-nightly.timer --all --no-pager
```

当前部署使用Python 3.12.14、Node.js 22.23.4、Nginx 1.18.0及Vite 7.3.7。环境相关地址、凭据、图读取账号及冻结数据通过私有配置和发布产物管理。

## 夜间更新

当前实际链路采用双源全量只读采集和版本化发布。先采集实体、映射和所引用的原经历并封存输入。维护响应通过后暂停查询，构建并核验独立图空间，再切换完整版本并恢复服务。采集与输入准备发生在维护标记写入之前。

定时器每天北京时间04:30启动，窗口为04:30至06:00，总预算90分钟。成功发布默认保留最近2份，并额外保护当前和回退引用。2026年11月13日首次实际定时发布成功，全流程约4分46秒。

```bash
cd /srv/relationship-map
backend/.venv/bin/python -m relationship_query.update.nightly status \
  --config /etc/relationship-map/nightly.json
```

持续CDC对接真实发布链路属于后续优化路线。部署配置、维护响应和恢复流程分别见[测试服务器部署说明](docs/test-server-deployment.md)、[在线人物及夜间输入](docs/live-mysql-and-nightly-input.md)和[夜间版本发布说明](docs/nightly-release.md)。

## 本地模拟环境

新检出目录准备Python 3.12、uv及Node.js 22.12以上环境后执行。

```bash
bash scripts/setup.sh
RELATIONSHIP_DATABASE="$PWD/data/mock-v1.sqlite" bash scripts/dev.sh
```

本地前端入口为 http://127.0.0.1:5173/，API入口为 http://127.0.0.1:8000/。模拟数据由初始化命令生成，真实环境通过配套发布和私有来源配置启动。

## 历史原型与验证记录

<details>
<summary>展开各阶段的模拟环境、实验入口和验证记录</summary>

使用模拟人物和经历验证两个查询入口、共同经历规则、人物列表、局部关系图和证据详情。当前是本机原型；可选来源演练使用一次只读采样的真实实体名称，人物、任期和关系仍全部虚构，不连接专家库或简历库。人物身份与实体归一由上游负责。

当前本机运行使用 **v0.25／uuid-relations-v5**。已完成轻量SQL发布检查、批量图取证和图候选游标分页，并验证1100个关联人物完整翻页。相同63人样例首屏中位耗时由306.377降至132.686毫秒，图执行调用数88降至20。当前配置及验证见 [查询性能报告](docs/performance/uuid-query-v025.md)，主方案为 [持续维护的架构方案](docs/query-system-architecture.md)。

代码新增 **v0.26 远程 MySQL 只读接入**，清单v5绑定主机、端口和CA证书，要求TLS身份校验与只读账号。独立MySQL 8.4.13容器的51项专项通过，容器已回收；当前没有实际远程来源。配置、复现和验证范围见[远程MySQL模拟验证](docs/remote-mysql-validation.md)。

独立更新程序 **v0.30.1** 已实现版本化表列映射、新版BIGINT事实适配、完整事务持久化与重放、固定截止点微批及独立发布恢复，入口为 `backend/.venv/bin/python -m relationship_query.update`。当前没有测试库，具体来源采用文件回放，真实MySQL一致性快照／实时CDC适配、上游实表全链路及查询API新模式仍待联调。本轮审计修复六项问题，已完成本机Nebula五轮真实图更新及GUEST权限核对，记录见[更新程序审计](docs/update-program-audit.md)。维护规则和完整命令见[更新程序说明](docs/update-program.md)。

已确认采用首次一致性全量＋CDC采集＋本项目微批发布。上游负责测试环境建表和模拟数据，graph_sync_batch归属同事Supabase→MySQL同步；本项目独立维护消费与投影状态。实施与联调见[更新设计](docs/mysql-change-sync-design.md)及[交接说明](docs/data-handoff.md)。

图中有四类业务节点、三类经历事实及四类入图预计算人物边。人物只存来源和业务编号，姓名从 MySQL 批量回查。相关人物列表、证据、对比、展开、关系导出和有界路径消费图中人物关系，实体背景筛选由 SQL 完成。当前发布源使用独立只读SQL账号、变更序号与36个DML触发器，发布和启动完整对账。管理员DDL按停服重新发布流程管理。[历史迁移记录](docs/uuid-graph-migration.md)

当前使用独立虚构快照：63 个来源人物节点、15 个标准实体、178 条经历事实和 2576 条人物证据边。不是跨库去重后的自然人数，也不是真实数据／生产容量验证。新模拟 SQL 为 12 表字段子集；正式 15 表归一状态、批次、删除和生产同步仍待接入。新模式暂按标准名称检索实体，原职位文字可组合筛选，专业不代替职位。

已安装环境下启动当前激活图（先停旧服务，清除其他模式配置）：

```bash
unset RELATIONSHIP_DATABASE RELATIONSHIP_MYSQL_URL RELATIONSHIP_NEBULA_MANIFEST RELATIONSHIP_GRAPH_ENGINE
unset RELATIONSHIP_SOURCE_API_MANIFEST RELATIONSHIP_SOURCE_API_MYSQL_URL
RELATIONSHIP_SOURCE_RELEASE_STORE="$PWD/data/source-release-trial/rehearsal-v1/store" bash scripts/dev.sh
```

页面 http://127.0.0.1:5173/。Ctrl+C 停止本次服务；不带上述配置的 `bash scripts/dev.sh` 仍是默认 SQLite 演示。完整默认回归 `bash scripts/check.sh` 也应在新图服务停止后执行，避免浏览器复用不同数据模式的 5173 服务。

以下版本记录描述各轮历史边界，不能将旧三表模式或旧含姓名 writer 当作新模型生产接入方式。

2026-11-06 目标图设计更新为 **v0.22／uuid-relations-v5**：[图 DDL](docs/graph-ddl.md) 定义四类业务节点、三类经历边及四类入图预计算人物边（含同专业），执行顺序见 [DDL 目录](infra/nebula/schema/README.md)。[预计算规则](docs/person-relation-materialization.md) 明确双方事实 Rank 和修正重算；[独立演练](docs/graph-business-fields-validation.md) 的 15／11 条证据边符合人工预期并完整回读。现有服务仍 v0.16，尚未适配新 API／构建器；person 保存来源和业务编号，工作／教育附属信息绑定经历；姓名不入图，只回 MySQL 展示，旧模拟图未清理，详见 [隐私边界](docs/graph-privacy.md)；最新MySQL输入及SQL回查字段见 [对应文档v5.0](docs/mysql-to-graph-fields.md)，旧v3.3候选已归档。

2026-11-06 设计基线更新为 v0.16.4：按最新精简版(3)使用 *_entity UUID 标准表、graph_name_mapping 和三类边；目标类型已写为 CHAR(36)，简历原表沿用专家 DDL 的规则也已获用户确认。用户已确认并补回名称映射 is_deleted，现为 12 列，按已匹配且 is_deleted=0 消费；其余旧列说明／约束仍待统一；尚未迁移程序或数据库。字段对照见 [图字段与MySQL对应 v5.0](docs/mysql-to-graph-fields.md)。全部履历仍虚构，没有正式数据与生产容量结论。

2026-11-06 已完成 [修正与版本切换演练](docs/source-release-validation.md)。给数据库同事的 [稳定标识与发布规则确认清单](docs/stable-identifiers-and-publishing-questions.md) 已区分上游契约与项目侧职责；尚未建设生产增量 Worker。发布工具和手动回退命令见报告。

2026-11-05 的 [六表建表与模拟接入](docs/handoff-schema-validation.md)、[三表及原履历独立图验证](docs/projection-three-table-validation.md) 已记录 DDL、实际结果、缺项与索引问题。启动六表样例工作台：加载 `data/handoff-trial/native.env` 后运行 `bash scripts/dev.sh`；三表实验使用 lab-manifest.json，不能当作 API 配置。

随后完成 [新原表模式端到端集成](docs/source-api-validation.md)。已发布的本机配置可直接启动；先停止旧服务、清除旧模式配置：

```bash
unset RELATIONSHIP_SOURCE_RELEASE_STORE
unset RELATIONSHIP_DATABASE RELATIONSHIP_MYSQL_URL RELATIONSHIP_NEBULA_MANIFEST RELATIONSHIP_GRAPH_ENGINE
source data/source-api-trial/run-v2/api.env
bash scripts/dev.sh
# Ctrl+C 停止后，切回默认演示。
unset RELATIONSHIP_SOURCE_API_MANIFEST RELATIONSHIP_SOURCE_API_MYSQL_URL
```

新模式直接只读访问已有 11 张模拟原表／词典表及新图，不额外建事实表，不修改这些冻结实验资源。重现配置发布使用 `backend/.venv/bin/python scripts/source_api.py --input data/projection-source-trial/run-v4 --output data/source-api-trial/my-new-run --reference-month 202611`，要求新目录；不支持原位 reset。正式增量、持久桥接与容量仍待验证。

项目整体进度、现有能力、技术验证与剩余工作汇总见 [项目现状报告](docs/project-status.md)（维护至 2026-11-05）。

2026-11-04 新增 [Supabase 候选归一数据源评估](docs/supabase-source-assessment.md)：已只读核对标准实体与映射；原经历另取、职位归一待定，尚未导入正式人物数据或接通 PostgreSQL 查询后端。

随后完成 [v0.12 严格只读样例全流程演练](docs/source-trial-validation.md)：从冻结的本地样例生成 60 名虚构人物与 122 条经历，验证 SQLite／MySQL／图辅助；后续运行不再访问 Supabase。当前源字段不作为正式交付结构。

```bash
# 已发布的本轮 SQLite 演练（与原演示分开）。
source data/source-trial/run-v2/.env
bash scripts/dev.sh
# Ctrl+C 停服后切回原演示。
unset RELATIONSHIP_DATABASE RELATIONSHIP_MYSQL_URL RELATIONSHIP_NEBULA_MANIFEST
```

重新生成只需本地文件和新目录：

```bash
backend/.venv/bin/python scripts/source_trial.py \
  --input docs/examples/source-trial-sample.json \
  --output data/source-trial/my-new-run
```

## 环境与首次安装

需要 Python 3.12、uv、Node.js 22.12+ 和 npm。后端依赖固定安装在 `backend/.venv`，前端依赖位于 `frontend/node_modules`，不使用全局 Python 包。

```bash
bash scripts/setup.sh
```

安装使用 `backend/uv.lock` 与 `frontend/package-lock.json`。若已有其他位置的 Python 3.12，可用 `PYTHON_VERSION=/absolute/path/to/python3.12 bash scripts/setup.sh` 指定解释器。

## 本地启动与停止

在项目根目录执行：

```bash
bash scripts/dev.sh
```

- 页面：<http://127.0.0.1:5173>
- API 文档：<http://127.0.0.1:8000/docs>
- 健康检查：<http://127.0.0.1:8000/api/v1/health>

首次启动会初始化缺失的模拟数据库；已有数据库会保留。端口被其他服务占用时明确报错，不会自动切换端口或终止其他服务。终端按 Ctrl+C 停止本次启动的前后端进程。开发模式下 Python 与 Vue 源码修改会重新加载。

## 数据与重置

默认数据库在 `data/mock-v1.sqlite`，模拟基准月份固定为 202611。数据集含 60 名人物，其中 1 人失效，界面显示 59 名有效人物；来源数量含双来源人物，因此专家与简历来源人数不能直接相加作为总人数。

重置、更换文件或数据版本前先停止开发服务，完成后重新启动。原型在启动时读取数据版本，暂不支持服务运行中的数据发布。

```bash
# 保留已有数据；缺失时才初始化
backend/.venv/bin/python -m relationship_query.cli init

# 显式恢复虚构样例；会清空此文件中的 demo_* 演示表
backend/.venv/bin/python -m relationship_query.cli reset
```

通过 `RELATIONSHIP_DATABASE=/absolute/path/demo.sqlite` 指定另一演示数据库文件。`--size` 可生成较大的固定种子样例，应同时指定独立文件；不同版本数据不会被 init 静默覆盖。不应将此环境变量指向任何真实业务数据库。

样例包括同名人物、双来源人物、重复任职、失效经历、非同期、时间缺失和跨公司职位变化。默认人物“林知远 p:000001”，与“周明澈 p:000002”具有 2021.01—2022.12 的 24 个月任职交集。“顾若溪 p:000007”曾在星澜科技任产品经理，在远川智能任技术总监，不能命中“星澜科技＋技术总监”。

## v0.9 本机 MySQL 模拟验证

可使用本机 MySQL 的独立实验库运行原工作台，默认 SQLite 入口保留。实测版本为 9.7.1；没有连接正式专家库／简历库、图数据库或 Linux 服务器。过程与限制见 [MySQL 验证记录](docs/performance/mysql-results.md)。

停止开发服务后，从独立模拟快照创建新实验库与新输出目录：

```bash
# 默认尝试本机 root 无密码连接；有认证时通过 RELATIONSHIP_MYSQL_ADMIN_URL 配置，勿提交凭据。
# 输入可以是单独生成的 60 人快照或 R01 保留的规模快照；不得用真实业务数据。
backend/.venv/bin/python scripts/mysql_lab.py \
  --input data/benchmarks/r01-final/scale-10000.sqlite \
  --output data/mysql-lab/my-new-run

# 加载新生成的本机配置，仍用相同命令启动；Ctrl+C 停止本次进程。
source data/mysql-lab/my-new-run/.env
bash scripts/dev.sh

# 停服后切回默认 SQLite。MySQL 模式下 init/reset 会拒绝执行。
unset RELATIONSHIP_MYSQL_URL
```

本次已保留 60 人联调配置 `data/mysql-lab/workbench/.env`；可加载它启动熟悉的演示工作台。配置文件权限为 600，位于忽略的 data 目录，不打印连接字符串。导入入口只新建随机 `relationship_lab_` 前缀库，拒绝已有表和输出目录；失败后使用新目录重试，不自动清空旧库。MySQL 实验库保留供复核，不自动删除现有服务或数据库。

API 会话为只读事务，但这不等于独立数据库账号的权限隔离；本轮沿用授权的本机账号。当前仅允许 loopback、PyMySQL、指定库名前缀和 utf8mb4 配置。MySQL 的字段长度是实验读模型约束，预检不接受超长值，不代表未来上游规范。专用账号、生产配置与其他 MySQL 版本后续单独验证。

专项检查与复现：

```bash
# 只创建并回收本次随机测试库，正常回归默认跳过需要 MySQL 的用例。
RELATIONSHIP_MYSQL_TEST=1 backend/.venv/bin/pytest backend/tests/test_mysql.py -q

# 先加载对应 10 万人实验配置；输入／数据库版本须匹配。
source data/mysql-lab/scale-100000/.env
backend/.venv/bin/python scripts/benchmark_mysql.py \
  --input data/benchmarks/r01-final/scale-100000.sqlite \
  --output data/mysql-lab/my-observation --size 100000 --analyze
unset RELATIONSHIP_MYSQL_URL
```

观察经过真实 MySQL TCP 与 API 序列化，但使用 ASGI 顺序请求，尚无 HTTP 并发负载结论。`--analyze` 会实际执行模拟查询并记录计划。SQLite／MySQL 结果均对照，错误和预算耗尽分别记录；不能将本机结果推算为百万级生产容量。

## v0.10 本地 NebulaGraph 环境

已建立固定 3.8.0 ARM64 镜像与 SDK 3.8.3 的独立实验环境，原生连接地址为 `127.0.0.1:19669`。环境管理命令：

```bash
bash scripts/nebula.sh up      # 首次注册／后续恢复，等待真实服务就绪
bash scripts/nebula.sh status
bash scripts/nebula.sh stop    # 保留容器和卷
bash scripts/nebula.sh down    # 移除本项目容器和网络，保留卷
```

凭据自动保存在 `data/nebula-lab/credentials.json`，权限 600，SDK 工具自动读取，不在命令行打印密码。此文件须随本机实验环境保留；工具不会在认证失败时自动重置已初始化的密码。使用原生 SDK 端口，不包含浏览器管理界面。

已有持久化验收样例可只读核对，也可新建虚构样例空间：

```bash
backend/.venv/bin/python scripts/nebula_lab.py verify --input data/nebula-lab/smoke.json
backend/.venv/bin/python scripts/nebula_lab.py smoke --output data/nebula-lab/another-smoke.json
RELATIONSHIP_NEBULA_TEST=1 backend/.venv/bin/pytest backend/tests/test_nebula_lab.py -q
```

报告文件不覆盖；每次 smoke 使用新实验空间，专项测试回收自己创建的空间。停止／移除命令不删卷，不使用 `down -v` 或系统清理来重置。环境建设记录见 [图环境说明](docs/nebula-environment.md)，后续模拟业务接入见下节。

## v0.13 图内路径计算（显式启用）

图负责连接链中的直接关系、至多一位中间人物的路径、同期窗口和证据事实引用；SQL 按 ID 提供人物／经历／来源详情并核对属性一致性。普通列表、专题和完整对比仍 SQL。无图配置保持纯 SQL；配置图后默认使用新引擎。历史辅助模式记录见 [v0.11](docs/graph-query-validation.md)，本版边界与耗时见 [v0.13](docs/graph-native-validation.md)。

```bash
# 使用已经发布的 60 人图投影启动熟悉的工作台。
unset RELATIONSHIP_MYSQL_URL
source data/graph-projection/workbench-v1/.env
export RELATIONSHIP_GRAPH_ENGINE=paths
bash scripts/dev.sh

# Ctrl+C 停服后，切回原始 SQLite 演示。
unset RELATIONSHIP_NEBULA_MANIFEST RELATIONSHIP_DATABASE RELATIONSHIP_GRAPH_ENGINE
```

路径结果显示“图内路径计算 · SQL 来源证据”。也可加载匹配的 MySQL 实验配置，再设置 RELATIONSHIP_NEBULA_MANIFEST；启动会校验版本、基准月和完整内容摘要，不匹配时拒绝启动。正常查询故障不自动切回 SQL；需要恢复 SQL 时停 API、取消图配置后重启。仅为历史比较时才设置 `RELATIONSHIP_GRAPH_ENGINE=candidates` 使用旧辅助引擎。

查看冻结来源样例的 MySQL＋图工作台：`source data/graph-native/source-trial.env` 后运行 `bash scripts/dev.sh`。所有人物与经历仍为虚构；启动无需访问 Supabase。

创建新模拟投影与复现对照：

```bash
backend/.venv/bin/python scripts/graph_projection.py \
  --input data/benchmarks/r01-final/scale-10000.sqlite \
  --output data/graph-projection/my-new-run

source data/mysql-lab/scale-10000/.env
backend/.venv/bin/python scripts/benchmark_graph.py \
  --input data/benchmarks/r01-final/scale-10000.sqlite \
  --manifest data/graph-projection/scale-10000-v1/manifest.json \
  --output data/graph-projection/my-new-observation
unset RELATIONSHIP_MYSQL_URL
```

构建新图空间、对账后才发布 ready manifest，不覆盖旧目录／批次，也不改源 SQLite。每份投影的只读账号在 reader-credentials.json（600 权限）；不要把该文件放进版本控制或报告。rank 只在该快照内可复现，源事实 ID 为跨批次引用。所有已发布 SQL／图快照保持不可变，纠正需要新快照、新图空间，停 API 后成对切换。

专项业务图测试使用 RELATIONSHIP_GRAPH_TEST=1，正常回归默认跳过；测试只清理自己创建的空间／账号。预算耗尽、批次不符和服务故障有独立状态；没有任意深度遍历、生产同步或百万级容量结论。

## 查询行为

- 两个入口分别保留条件，修改条件自动查询并重置分页与局部图；也可点击查询按钮。
- 公司、学校、职位可多选，类别内 OR、类别间 AND；公司、职位、任职时间绑定同一条工作经历。例如选择两家公司和“总监”，表示在其中任意一家公司担任总监，不会拼接不同经历。
- 每页 20 人，按稳定人物 ID 排序；接口最多 50 人。游标绑定条件与数据版本。
- “曾任职同一公司”包括同期和非同期；“同公司同期”要求双方时间可计算且相交；“同校”不推断同期。
- 职位用于背景筛选，不推断上下级、合作或实际认识。
- 点击列表人物查看证据，点击图中公司／学校可转为实体筛选；人物可设为新中心。
- 展开选中人物一次最多 20 位直接关联，图累计最多 100 节点、200 边。重复点击不会无限遍历全图；需要完整结果时设为中心后在列表翻页。列表完整性不受图展示上限影响。
- 图中每条线对应人物到实体的一条经历；证据面板保留来源记录定位。相同人物多次任职仍可区分。

### 两人对比与时间轴

点击左侧“对比”进入独立工作台，或从人物详情点击“与参考人物对比”。选择两位不同人物后自动查询，也可点击“对比人物”；交换按钮调换双方。

页面并排展示双方履历，使用统一月份尺度。深色区间仅来自同公司同期证据；时间不完整的经历单列，当前任职标记截至数据集基准月。选择共同经历可高亮双方对应记录，并查看来源经历键。同校不推断同期，共同经历不证明实际认识；月份不会跨多条证据直接累加。

接口示例：

```text
POST /api/v1/persons/compare
{"reference_id":"p:000001","candidate_id":"p:000002"}

POST /api/v1/persons/search
{"organization_ids":["org:0","org:1"],"role_ids":["role:0"],"school_ids":[],"page_size":20}
```

旧单值筛选字段继续兼容，并与相应多选列表合并为同类 OR；列表排序与重复项不影响查询。真正改变集合后旧游标不可复用；从 v0.4 升级也应重新查询。每类最多 50 项，所有选择均需有效且类型正确。

本轮无需重置数据库。对比页面截图为 `docs/comparison-preview.png`；数据、表结构和只读预检格式保持原有约定。

## v0.6 实体专题、细化查询、保存与导出

- 点击左侧“专题”选择公司或学校，查看标准名称与已知别名，并继续按来源、职位等背景条件筛选。图中实体详情和人物经历也能进入专题；人物、实体组合、专题分别保留筛选状态。专题显示当前页人数，不提供全库总数或在职人数。
- 人物入口可以选共同公司；“同公司同期”还可以选月份窗口和最短共同任职月数。月数只计算一条经历对在窗口内的交集，不跨重复／多次任职累加。切换同校自动清除公司与同期限制。列表摘要、图及右侧共同证据使用同一关系范围；两人对比仍查看双方完整履历与共同证据。
- 查询成功后，在“常用条件”输入名称并保存，最多 20 组、名称 1–40 字。记录仅存在当前浏览器当前站点，刷新可恢复，从第一页重新查询；不保存结果、旧游标或图位置。数据版本变化会提示，无效标识和存储故障显示失败；损坏记录不会被自动覆盖，可显式清空。清理浏览器数据会删除记录。
- “导出当前页 JSON／CSV”只导出当前页，附模拟标识、数据版本、基准月、查询条件、人物和来源证据。全部有效履历另外标明，不代表每条均命中筛选。CSV 包含元数据行、UTF-8 BOM 和公式文本保护。服务端核对页面版本和人物；409 时先刷新查询再导出。API 最多 50 人、经历及证据合计超过 5000 条时报错，不导出全库。
- “导出图 PNG”先适应画布，导出有界局部图，并附模拟标识、版本及范围说明。图片可含手动展开，与列表导出范围不同；长条件的完整内容见 JSON／CSV。筛选变化会取消旧导出。

新增接口为 `GET /api/v1/entities/{id}`、`POST /api/v1/relations/evidence/search`、`POST /api/v1/exports/persons`。关系筛选示例：

```text
POST /api/v1/persons/p:000001/relations/search
{"relation_type":"same_company_overlap","relation_organization_ids":["org:0"],"relation_start_month":202101,"relation_end_month":202112,"min_overlap_months":12}
```

上述查询中周明澈的证据交集为 12 个月，原始履历日期保留。`start_month/end_month` 仍指候选工作经历的背景时间，`relation_start_month/relation_end_month` 才是共同同期窗口，两者互不替代。共同时间窗仅适用于同公司同期，非法组合返回 422。

截图：`docs/entity-topic-preview.png`、`docs/graph-export-preview.png`。升级 v0.6 无需重置或迁移数据库，旧分页游标需重新查询。

## v0.7 连接链探索

点击左侧“路径”，或在两人对比中点击“探索连接链”。选择两位不同人物，查看直接共同经历及最多经一位中间人物的连接链。点击链条、段落按钮或图中实体／连线切换证据，可选择本段其他经历，并点击“对比本段履历”核对双方完整履历。同名人物始终依人物 ID 区分。

页面默认每段要求同公司同期，可切换同公司、同校或全部共同经历（允许混合）。API 省略 scope 或提供空 scope 时按全部共同经历处理，实际规则在响应中回显。共同公司和同期窗口约束每一段，中间人物来源仅影响中间人物。每段分别判断时间，不要求三人同时共事，不推断实际认识或可引荐；同校不推断同期，职位不作为连接节点。

```text
POST /api/v1/relations/paths
{"reference_id":"p:000001","candidate_id":"p:000008","scope":{"relation_type":"same_company_overlap"}}
```

默认虚构数据中，林知远 p:000001 与程星野 p:000008 可通过顾若溪 p:000007 连接：第一段星澜科技，第二段远川智能，来源分别可定位到顾若溪的两条不同任职经历。p:000001 与同名的 p:000012 在同公司同期规则下无结果，切换“全部共同经历”可观察混合公司／学校路径。截图见 `docs/paths-preview.png`。

默认核查 200 位中间候选、返回 10 条间接链、读取 2000 条经历、每段展示 20 条证据，事实处理预算 1500 毫秒，并有 SQLite 执行与 Python 核对次数保护。“搜索范围”可调整候选与展示条数，API 有更高但有限的上限。候选从 A 的邻接按 ID 获取，预算导致的局部结果不是全局推荐；交换端点后局部范围可能不同。

发现连接但不完整时保留已核实结果并标明原因；未找到且预算耗尽时明确显示“搜索范围受限”，不能据此断言没有关系。证据展示上限和中间候选核查是否完成分别标记。完整空结果只说明所选规则下一位中间人物范围内未发现链。服务失败显示错误和重试，取消后不显示虚假的空结果。

时间预算是事实处理保护，不是 HTTP 硬时限；前端取消旧请求，服务端同步执行仍受预算约束。v0.7 不增加任意深度、后台搜索、全库路径预计算，也暂不保存或导出路径查询；v0.6 的常用条件和当前页导出继续可用。无需迁移或重置数据库，旧列表查询规则保持兼容。

## 验证与接口类型

### 只读逻辑数据预检

```bash
backend/.venv/bin/python -m relationship_query.cli validate-dataset \
  --input docs/examples/logical-dataset.json
```

仅读取文件，向标准输出返回 JSON 报告，不打开数据库、不导入、不创建目标目录，也不修改输入。示例包含 14 名人物、10 个实体、29 条经历；预期 0 错误、4 条提示，退出码 0。出现错误时退出码 1；用法错误为 2。counts 包含失效记录，区别于页面的有效记录数。

报告通过不代表真实数据可上线；尚无正式结构，样例只是逻辑示意。重复 ID、悬空引用、日期矛盾等阻断导入；未知任期、疑似重复经历及同类型别名歧义作为待核对提示，不自动补日期、去重或合并人物。初始化和预检复用相同校验。

### 正确性与回归

人工样例的期望结果在 `backend/tests/fixtures/query-cases.json`，固定种子 500 人差分使用独立日历月份算法。快照演练使用隔离临时数据库，先结束旧 API 生命周期再加载新版本，不改变默认演示数据库。

```bash
# 全部检查，浏览器测试可自动启动并回收开发服务
bash scripts/check.sh

# 只跑后端
cd backend
.venv/bin/pytest -q
.venv/bin/ruff check src tests
.venv/bin/mypy src

# 只检查预检、独立基准和快照修正
.venv/bin/pytest tests/test_validation.py tests/test_query_baseline.py tests/test_snapshot_rehearsal.py -q
```

浏览器测试默认使用已安装的 Google Chrome；覆盖两个入口、组合筛选、翻页、证据、展开、设为中心、失败重试和过期响应。浏览器需要能够访问本机端口；受限运行环境可能需要授予本机监听与测试浏览器启动权限。

```bash
# Pydantic / OpenAPI 是前后端契约来源，修改契约后重新生成
bash scripts/generate-api.sh

# 前端类型检查与生产构建
cd frontend
npm run typecheck
npm run build
npm run test:e2e
```

`docs/openapi.json` 和 `frontend/src/api/schema.d.ts` 是生成文件，不手动修改。前端只转换展示格式，不重新实现关系规则。

```bash
# 独立临时数据库上的小样本耗时观察，不改变默认演示数据库
backend/.venv/bin/python scripts/benchmark.py
```

## 代码与后续接入

### R01 规模观察与诊断

已完成固定种子 1 万／10 万人、21 场景的接口观察与浏览器验证，结果及限制见 [R01 报告](docs/performance/r01-results.md)。现有模拟库不需要重置，新规模库只写到新目录：

```bash
backend/.venv/bin/python scripts/benchmark_scale.py \
  --output data/benchmarks/my-run --sizes 10000 100000 \
  --repeats 7 --seed 42 --strategy both --keep-databases

# 先停止普通开发服务；脚本只接受规模报告登记的独立虚构库。
backend/.venv/bin/python scripts/benchmark_browser.py \
  --database data/benchmarks/my-run/scale-100000.sqlite \
  --output data/benchmarks/my-run/browser-100000.json
```

报告目录和浏览器输出必须是新路径。省略 `--keep-databases` 时临时规模库用完删除；保留库仅用于后续观察，不作为默认演示库或真实数据接入。可用 `--cases entity_ordinary path_hot` 只跑选定场景，`--strategy baseline/current/both` 选择冻结参照或当前策略。

报告包含首次／预热耗时、近似 VM 工作量、SQL 计划、嵌套阶段、响应大小和受限原因；不能把 VM 计数当扫描行数，也不能把这些本机顺序请求当成生产并发容量。热门路径采用有界展开量探测选择 SQL，规则与预算不变。长履历完整证据响应仍约 18 MB，后续需评估分页与摘要。

常规 `bash scripts/check.sh` 会跳过规模浏览器观察，不默认生成大库。原 `scripts/benchmark.py` 的 2000 人服务层命令继续可用。

后续可扩展功能与前置条件见 [扩展候选路线图](docs/extension-roadmap.md)。清单用于选择，不代表已实现或全部纳入首版。

后端的 `api`、`services`、`domain`、`infrastructure` 分别负责协议、查询编排、业务规则和存储。`QueryRepository` 是业务服务消费的最小数据访问边界，当前实现为 SQLite；未来数据库实现必须在 SQL 内完成过滤和分页，不能读取全库后用 Python 筛选。

前端的 `useWorkbench` 管理请求生命周期和工作台状态，`GraphCanvas` 封装 G6，`PersonList` 与 `EvidencePanel` 负责展示。图引擎按需加载，实例不进入深度响应式状态。

正式数据到位后，按 `docs/query-system-architecture.md` 的流程复核新表、分布、负载和运行环境，再决定 MySQL 读模型、NebulaGraph、缓存及同步链路的实际实现。原型的演示表、固定月份、无登录模式和 SQLite 耗时不属于生产设计结论。

</details>
