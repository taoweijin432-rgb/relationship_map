# 修正、停服版本切换与回退验证

日期：2026-11-06。架构 v0.16。本轮全部采用明确标记的虚构数据和模拟上游修正，不访问 Supabase，不修改已有 A 库／图，不建设生产增量 Worker。

## 实现范围

新增三条入口：

- scripts/source_corrections.py：按明确修正指令复制完整快照，预检通过后另建 SQL 库和图空间，回读对账后发布新 API 配置。不会激活或覆盖旧资源。
- scripts/source_release.py：校验候选、停服激活、回退及状态查询。固定开发端口 8000／5173 必须都能独占，否则拒绝；不会替用户终止任何进程。
- scripts/rehearse_source_release.py：真实启动／停止本次开发服务，用 HTTP 演练 A→B→错误候选拒绝→回退 A，保留查询、启动日志与状态历史。

激活记录只有一个 active.json，用文件锁防止并行切换，候选完整验证后才用同目录临时文件＋os.replace 原子替换。状态记录当前／上一完整配置引用、文件摘要、数据版本、激活修订号和历史，不保存密码。API 启动时固定激活引用，请求前后检查指针及配置文件摘要；绕过工具改指针或配置会返回 RELEASE_CHANGED 409，不能在旧进程中热切换。

这是本机单实例的停服流程，不是生产分布式发布事务、在线双写或零停机切换。候选预检失败不会改变当前指针；已经激活但服务启动失败时，提供显式 rollback，需操作者执行，不自动宣告新版本健康或静默降级。

```mermaid
flowchart LR
    A[保留完整 A SQL 和图] --> P[读取 A 的只读快照]
    P --> C[应用明确模拟修正到副本]
    C --> V[预检引用 归属 时间和槽位]
    V --> B[另建完整 B SQL 和图]
    B --> Q[回读核对和查询验收]
    Q --> S[停服务 原子切换指针]
    S --> N[启动 B 核对版本]
    N --> R[停服务 校验并回退 A]
```

## 本轮实际修正

指令为 [完整模拟修正样例](examples/source-correction-plan.json)，绑定 A 的完整源摘要。所有指令携带行 ID、原值条件、目标值与原因；不允许修改主键、来源槽位键或任意表。任何原值不符、多次修正同一行、漏同步槽位或目标不存在均阻断。输入对象不被修改；无效输入在创建新库前阻断。

| 修正 | A | B | 验证目的 |
| --- | --- | --- | --- |
| 工作经历失效 | experts_work_experience:1 有效 | 原行与槽位 1001／1002 标记失效 | 新图无两条经历边，SQL 保留原定位 |
| 人物归属纠正 | 工作经历 19 属 p:expert:1 | 同条原经历和槽位 1241／1242 移至 p:expert:5 | Rank 不换，旧起点不残留；不执行身份识别 |
| 学校目标纠正 | 教育经历 1→学校 308 | 原文和槽位 1003→学校 309 | 旧同校证据消失，新目标正确；专业槽位不被冒认为学校 |
| 公司目标纠正 | resume_work_experience:43→公司 307 | 原文和槽位 1243→公司 304 | 旧终点不残留，同条经历的职位仍为产品经理 |
| 实体更名 | 304=模拟标准公司2 | 304=模拟标准公司2（更名演练） | 长期 ID 保留，旧别名仍可定位 |

映射表始终 252 行；新图边 246→244，完整图键比较为移除 6、增加 4。图键包含起点、终点、边类型和 Rank，因此归属／目标纠正会表现为旧键消失、新键出现，不能只看 Rank 相同就认定旧边已处理。本轮“移除”指 B 的完整新空间不再含旧键；A 空间原边完整保留供回退，并未执行在线增量删除。

A／B 顶点均为 84、有效来源人物均为 63，API 工作／教育事实 119→118。来源人物数不等于真实跨库去重人数。

## 冻结资源

| 批次 | SQL | 图空间 | API 配置 |
| --- | --- | --- | --- |
| A 原始 | relationship_lab_handoff_aab83496cf21 | relationship_lab_three_6a9040da29b3 | data/source-api-trial/run-v2 |
| B 修正 | relationship_lab_handoff_fdf396b81570 | relationship_lab_three_ad25c7914f85 | data/source-release-trial/corrected-v1/api |

A 数据版本 source-slots-v2-def3e6ec6076bf4c3819-202611；B 为 source-slots-v2-7a25c1d15e81c91cd61b-202611。完整 SQL／图摘要和差异保留在本轮本地输出，公开报告不含凭据。

数据版本绑定内容和查询基准月，激活修订号记录切换。A 的游标到 B 被拒绝；回退同一完整 A 后，其原游标可再次有效，因为内容与规则恢复，并非永久撤销游标。新进程仍必须重启，旧激活修订的进程会拒绝继续响应。导出也继续检查数据版本，不允许跨版本拿旧人物页导出。

## 实际验收

- 真正启动前后端并经 HTTP 查询：A 的 24 个月直接同期和经 p:resume:7 的两段连接存在；切换 B 后这两项消失，p:expert:1 仅剩学校 309 的教育事实，slot:1241 在 p:expert:5 下可追溯。
- B 期间提交 A 游标返回 INVALID_CURSOR 422；试图在开发服务仍监听时切换被拒绝，指针原样保留。
- 使用 A SQL＋B 图的错误候选返回 GRAPH_VERSION_MISMATCH 409，B 激活记录不变。回退前重新验证 A，重新启动后元数据、直接证据与原值一致。
- 不存在的实体、遗漏失效槽位等坏修正被阻断；没有可使用的半初始化 API 批次。
- 启动故障以隔离测试模拟，随后显式回退旧批次恢复健康；未通过停止共享数据库模拟故障。
- 文件锁、原子写失败、旧配置被改动、运行中激活文件漂移及重复激活均有专项；重复激活同一完整配置不额外增加修订号。

| 检查 | 实际结果 |
| --- | --- |
| 完整原生后端回归 | 528 通过、80 配置专项跳过，310.40 秒；MySQL／图环境／原图业务专项启用 |
| 修正与切换专项 | 22 通过、0 跳过，3.03 秒；包括实际 SQL／图、坏输入、端口保护、故障与回退 |
| 原 A 原表接口专项 | 60 通过、0 跳过，9.10 秒 |
| 原演示浏览器 | 18 通过、12 可选专项跳过，44.7 秒 |
| 修正 B 浏览器 | 3 通过、0 跳过，10.1 秒；截图已查看 |
| 静态、契约和构建 | Ruff、mypy 61 源文件、OpenAPI／TypeScript 生成、前端格式／类型／构建通过，构建 3.42 秒 |
| 真实 HTTP 演练 | A→B→错误候选拒绝→回退 A 全部通过，本次前后端已回收 |

80 个跳过项为 28 条旧来源配置专项、46 条原表 API 专项、6 条本轮原生切换专项；后两组分别在 60／22 项中显式执行。各批次存在重叠，不能把通过数相加。既有 G6 包体和 Starlette/httpx 提示保留，没有新生产容量结论。

原始记录：[完整后端](performance/source-release-full-backend.xml)、[切换专项](performance/source-release-tests.xml)、[原 A 接口](performance/source-release-original-api.xml)、[修正 B 浏览器](performance/source-release-browser.xml)、[真实 HTTP 演练](performance/source-release-http.json)、[环境与代码摘要](performance/source-release-validation.json)。[修正 B 页面截图](source-release-preview.png) 展示旧链消失且标明完整无结果。

本地真实 HTTP 报告为 data/source-release-trial/rehearsal-v1/report.json；服务日志为 a.log／b.log／restored-a.log。错误混合候选目录仅用于负例，不作为可用发布批次。验收后激活目录已回退 A（修订 5），B 保留可再次显式激活，原服务恢复 A 供用户查看。

## 使用方式

先停止本项目开发服务，再激活候选；不要停止 MySQL／NebulaGraph 或其他服务。

```bash
# 创建新的修正 SQL／图与 API 配置，输出必须不存在。
backend/.venv/bin/python scripts/source_corrections.py \
  --base data/source-api-trial/run-v2 \
  --plan docs/examples/source-correction-plan.json \
  --output data/source-release-trial/my-new-correction

# 停服后激活已发布批次。
backend/.venv/bin/python scripts/source_release.py activate \
  --store data/source-release-trial/my-store \
  --release data/source-release-trial/my-new-correction/api

# 使用单一激活目录启动。不得混用旧源环境配置。
unset RELATIONSHIP_DATABASE RELATIONSHIP_MYSQL_URL RELATIONSHIP_NEBULA_MANIFEST RELATIONSHIP_GRAPH_ENGINE
unset RELATIONSHIP_SOURCE_API_MANIFEST RELATIONSHIP_SOURCE_API_MYSQL_URL
export RELATIONSHIP_SOURCE_RELEASE_STORE="$PWD/data/source-release-trial/my-store"
bash scripts/dev.sh

# Ctrl+C 停服后，回退到已经保留的上一批次；首次激活没有上一批次。
backend/.venv/bin/python scripts/source_release.py rollback \
  --store data/source-release-trial/my-store
bash scripts/dev.sh
```

查看状态使用 status --store；切回直接清单或默认演示前 unset RELATIONSHIP_SOURCE_RELEASE_STORE。原表／激活目录模式都拒绝 init/reset，启动不会初始化默认 SQLite。

重现完整 HTTP 演练：

```bash
backend/.venv/bin/python scripts/rehearse_source_release.py \
  --a data/source-api-trial/run-v2 \
  --b data/source-release-trial/corrected-v1/api \
  --output data/source-release-trial/my-new-rehearsal
```

## 仍需同事确认与后续实现

可转发 [稳定标识与发布问题清单](stable-identifiers-and-publishing-questions.md)，其中最关键的是跨重跑稳定键、一字段多目标、完成批次、删除纠正和历史保留。上游发布完成不等于本项目图构建完成，也不等于服务切换成功，应分别定义。

本轮不解决持久 UUID→BIGINT 分配、正式人物归一、实体合并／拆分、生产增量旧边清理、CDC、线上发布协调、权限／备份／容量。完整摘要、固定端口锁和 GUEST 逐次建池仍是本机小样本选择，不能用于生产规模结论。
