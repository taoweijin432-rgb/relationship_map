# v0.11 模拟图投影与路径查询验收

历史记录：v0.13 已将配置图后的默认路径引擎改为图内计算，SQL 仅装配来源详情，见 [新验收](graph-native-validation.md)。本页数字与候选算法保留作对照，不代表当前默认图引擎。复现本页旧行为须显式设置 `RELATIONSHIP_GRAPH_ENGINE=candidates`。

日期：2026-11-03。已实现从同一虚构快照生成不可变图投影，通过 NebulaGraph 召回有界候选，再由 SQL 与现有 Domain 规则核对每段经历证据。默认仍采用 SQL：本轮 9 个场景的图辅助预热 P50 均高于纯 MySQL，没有验证到加速收益。

## 已实现范围

- 仅最多一位中间人物的连接链可选图候选；人物／实体搜索、分页、直接关联、事实、完整两人对比和最终关系证据仍用 SQL。
- `scripts/graph_projection.py` 从独立 SQLite 快照只读导入，每次创建新空间、新输出目录。先共用校验、检查标识长度，再写 building 标记；逐批回读人物、经历和邻接，对账成功并验证独立只读账号后发布 ready manifest。失败批次不发布，不覆盖旧空间。
- 人物和实体 VID 带类型前缀，严格检查 128 字节 UTF-8 长度。每人的经历按事实 ID 排序分配 rank，保留重复任职和来源定位；rank 仅在该不可变快照内可复现，跨版本引用使用事实 ID。
- 附属实体邻接及每块 128 人的有序成员索引用于稳定召回，不生成全库人物对。读取块时验证数量、成员摘要和顺序，按人物 ID 归并去重，随后由 SQL 重新核对来源、有效性、共同实体、时间窗口等资格。
- 继续执行原有候选、路径、事实、证据及时间预算；另限制 64 个参考实体、20000 图返回行和 256 次图请求。受限返回明确原因 `graph_limit`，不声称全局没有关系。这些是客户端读取预算，不是服务端磁盘扫描行数或 HTTP 硬时限。
- 前端路径页标注图辅助模式，响应返回 `query_backend`、`projection_id`、图调用次数及返回行数。关系和时间证据仍由后端生成。

这里的分块设计用于避免依赖原生 LIMIT 的不确定截断顺序：每块至多 128 人，原生 GO 的 `LIMIT [129]` 检测越界，读取后核对完整块并排序。它不是对任意热门实体无限展开。语法与 LIMIT 限制参见 [NebulaGraph 3.8 官方说明](https://docs.nebula-graph.io/3.8.0/3.ngql-guide/8.clauses-and-options/limit/)。

## 版本、权限与故障

启动时检查 SQL 版本、基准月份和全量逻辑内容 SHA-256，匹配 manifest 才启用图。每次路径请求前后检查图 ready 标记和批次。全量摘要会增加启动开销，运行期间必须保持已发布 SQL／图快照不可变；不支持同版本原位更新。修正后新建快照和图空间，停 API 后成对换配置。

每投影使用独立 GUEST 账号，只读凭据放在 manifest 同目录的 reader-credentials.json，权限 600；报告和 manifest 不含密码。权限边界已用真实写入被拒绝的测试验证，角色定义见 [官方账号与权限文档](https://docs.nebula-graph.io/3.8.0/7.data-security/1.authentication/2.management-user/)。

每次图 RPC 使用剩余预算设置 SDK 超时并回收连接池；进程内最多 4 个并行 RPC。本轮没有生产连接池或 HTTP 并发容量结论。依赖故障返回 503，批次不匹配返回 409，不静默回退 SQL。SDK 超时不能保证立即取消服务端工作。

初始化回归发现新建 Tag 已在 Graph 可见、Storage 尚未就绪时可能返回 `-1005 / Storage Error: Tag not found.`。导入辅助工具只对明确的异步就绪状态限时等待，补充了对应单元测试并通过完整原生回归；普通业务查询不使用这套重试，解析、权限、网络失败不作为通用重试条件。

## 实际投影

环境沿用 [本机图环境](nebula-environment.md)：macOS 26.5.1 ARM64、Python 3.12.14 虚拟环境、SDK 3.8.3、NebulaGraph 3.8.0 三容器、MySQL 9.7.1。本轮没有新增依赖，保留现有 MySQL／Canal。

| 项目 | 工作台快照 | 规模快照 |
| --- | --- | --- |
| 人物 | 60 | 10000 |
| 经历事实边 | 122 | 53521 |
| 标准实体 | 16 | 1125 |
| 有效人物—实体成员关系 | 118 | 46545 |
| 有序成员块 | 11 | 1192 |
| 辅助边（附属实体＋成员） | 236 | 93090 |
| 导入、回读及发布总耗时 | 26.40 秒 | 37.98 秒 |

总耗时包含 Schema／角色传播等待，不等于稳定导入吞吐。1 万人图有 12318 个顶点（含元数据）、146611 条边；辅助索引增加存储与维护成本。公共原始记录为 [1 万人投影](performance/graph-projection-10000.json) 和 [工作台投影](performance/graph-workbench.json)，凭据保留在本机 data 目录。

## 同快照 MySQL／图辅助对照

对同一 1 万人、53521 条经历、固定种子 42 快照，在独立子进程中逐场景顺序执行 ASGI 接口，实际连接本机 MySQL TCP 和 Nebula RPC。每场景每策略首次观测 1 次、预热 7 次，9 × 2 × 8 共 144 次。不是 HTTP 并发压测；首次观测不等于清空系统缓存，7 次预热的 P95 仅供定位。启动检查耗时另列在原始记录，不计入请求延迟。

| 路径场景 | MySQL 预热 P50 / P95 ms | 图辅助预热 P50 / P95 ms |
| --- | --- | --- |
| 普通路径 | 8.813 / 9.399 | 23.578 / 28.793 |
| 热门公司 | 29.562 / 40.457 | 92.344 / 111.925 |
| 长履历 | 33.886 / 44.859 | 97.447 / 122.799 |
| 无结果 | 5.301 / 10.967 | 8.068 / 8.496 |
| 中间人物专家来源 | 24.710 / 36.863 | 512.727 / 528.410 |
| 同期窗口／最少月份 | 30.997 / 52.204 | 129.208 / 147.158 |
| 同校 | 8.475 / 9.228 | 16.601 / 28.619 |
| 未知任职日期 | 25.926 / 37.430 | 678.371 / 769.192 |
| 候选上限 1 | 12.594 / 13.149 | 30.419 / 31.117 |

144 次均无接口错误、外部超时或已核对的语义差异；4 个完整搜索场景的语义摘要相等，5 个受限场景比较共同返回路径和证据，未声称验证全集。结果后端标记正确，源 SQLite、默认演示库和 MySQL 逻辑内容摘要均不变。[最终原始对照](performance/graph-query-10000.json) 的后端源码 SHA-256 为 `10de2b5498d24d14a9bb71597943efc7044d946cd0cbf50dcc12088da0bbb402`，已核对与最终源码一致；前几轮本机观察保留在 data/graph-projection 下。

当前图实现逐 RPC 创建 SDK 池并归并成员，时间／来源资格仍需 SQL 过滤。稀少命中时会读取更多块；例如未知时间场景的首次请求有 107 次图调用、6471 行返回。额外 RPC 与复核是当前开销来源，具体优化收益仍需后续对照验证，不能据此推断图数据库在所有负载下更慢或更快。

## 正确性与界面验收

执行 `RELATIONSHIP_MYSQL_TEST=1 RELATIONSHIP_NEBULA_TEST=1 RELATIONSHIP_GRAPH_TEST=1 bash scripts/check.sh`：424 项后端通过（250.48 秒），Ruff、mypy、OpenAPI 类型生成、前端格式／类型／构建通过，默认浏览器 18 项通过（45.5 秒），规模观察与图专项按开关跳过。加载工作台图配置并设置 `RELATIONSHIP_GRAPH_BROWSER=1` 后，19 项浏览器通过（48.5 秒），仅规模观察跳过；真实 HTTP 响应与图辅助标记、经历证据一致。

新增 37 项图业务测试，包括离线边界和 20 项原生访问测试：

- 人工场景验证候选、每段关系及证据与独立月份算法一致，覆盖来源、同校、同公司、未知日期和窗口条件；500 人独立数据穷尽候选，核对 24 组参考人物／范围／来源组合。
- 四类新快照修正：经历失效、公司／学校归一纠正、上游人物映射变更。新图与 SQL 证据更新，旧投影被拒绝，旧游标失效；不在本系统重做人物识别。
- 真实 GUEST 写入拒绝、building 标记拒绝、成员边丢失报错、发布失败不产生 ready manifest、已有输出不覆盖。
- 模拟 SDK 认证、连接、服务端错误及超时，确认分类和连接回收；没有将模拟故障说成真实停机演练。
- 图预算不足保留已核实前缀并标注限制，不静默当作空结果。

真实测试随机空间／账号已回收，首次失败遗留的未发布空间也已清理；保留 60 人和 1 万人 ready 投影及原环境持久化样例。浏览器创建的前后端服务已退出，图容器有意保留运行。既有 G6 包体提示和 Starlette/httpx 弃用提示仍存在。

## 本机使用与复现

在项目根目录，已发布工作台快照可直接启用：

```bash
bash scripts/nebula.sh up
unset RELATIONSHIP_MYSQL_URL
source data/graph-projection/workbench-v1/.env
bash scripts/dev.sh
```

打开 http://127.0.0.1:5173，进入连接链查询。Ctrl+C 停止后 `unset RELATIONSHIP_NEBULA_MANIFEST RELATIONSHIP_DATABASE` 可恢复默认 SQL 演示。若使用 MySQL，先加载匹配的 MySQL .env，再显式设置对应 manifest；不同快照即使版本名相同，也会被内容检查拒绝。

新投影和对照命令（输出必须为新目录）：

```bash
backend/.venv/bin/python scripts/graph_projection.py \
  --input data/benchmarks/r01-final/scale-10000.sqlite \
  --output data/graph-projection/new-projection

source data/mysql-lab/scale-10000/.env
backend/.venv/bin/python scripts/benchmark_graph.py \
  --input data/benchmarks/r01-final/scale-10000.sqlite \
  --manifest data/graph-projection/scale-10000-v1/manifest.json \
  --output data/graph-projection/new-comparison
unset RELATIONSHIP_MYSQL_URL
```

## 后续决策条件

真实数据到位后，先核对字段映射、事实及身份来源、日期质量、快照版本，再统计热门实体和履历分布。若继续优化图模式，应优先减少 RPC／连接成本、评估资格过滤位置，再用相同规则和预算比较；暂不将更深路径或全量人物对预计算纳入默认范围。

目标 Linux、公司指定数据库版本、生产权限、并发负载、恢复、增量同步、10 万人图投影及百万级容量本轮均未验证。切换成对不可变快照是原型约定，不能替代生产 CDC 或发布一致性方案；生产索引、MySQL／图分工和部署规格继续待验证。
