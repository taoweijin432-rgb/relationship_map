> 历史归档，已由 graph-ddl.md v2.0 替代；不是当前字段定义。

# 人物关系图谱 DDL 与投影契约

版本：v1.3 ｜日期：2026-11-06 ｜模型标识：`uuid-relations-v4` ｜架构：v0.20

这是本项目确定的目标图结构，用于下一轮新模型适配与独立验证。用户进一步确认人物关系需要在入图阶段计算保存，因此在 v1 事实层上增加人物关系层。MySQL 的已确认结构提供数据依据；TAG 名、图属性、月份表示及控制标签是本项目设计，不宣称来自上游 Word。本文替代旧字段清单中“每条边统一 11 个属性”的候选方案，但不修改上游表设计。运行程序仍为 v0.16，尚未按本模型接入 API。

可执行定义由 [无人物姓名的基础节点与事实边](../../infra/nebula/schema/uuid-facts-v2.ngql) 加 [人物关系边](../../infra/nebula/schema/person-relations-v3.ngql) 组成，按此顺序在新空间执行。用户明确人物姓名只回 MySQL 展示，person.name 已从目标图删除；规则见 [人物隐私边界](../graph-privacy.md)。本机空间参数参考 [space-local-example.ngql](../../infra/nebula/schema/space-local-example.ngql)，另取新空间名。定义面向 NebulaGraph 3.8.0，参考官方 [CREATE TAG](https://docs.nebula-graph.io/3.8.0/3.ngql-guide/10.tag-statements/1.create-tag/) 和 [CREATE EDGE](https://docs.nebula-graph.io/3.8.0/3.ngql-guide/11.edge-type-statements/1.create-edge/)；字段规则同时需预检，不能把 DDL 当已完成应用迁移。

## 1 本轮决定

| 对象 | 本版定义 | 目的 |
| --- | --- | --- |
| 业务节点 | `person`、`company`、`school`、`major` 四个独立 TAG | 图本身明确类别；不用通用 entity.kind 重复区分类别 |
| 经历事实边 | `worked_at`、`studied_at`、`studied_major` | 记录同一条原经历对应的标准实体 |
| 预计算人物边 | `same_company`、`company_overlap`、`same_school`、`same_major` | 入图阶段从事实层计算并持久化，查询优先读取 |
| 图键 | 人物 VID、实体 VID、边类型、Rank | 唯一定位节点、经历边及 SQL 证据 |
| 属性 | 公司／学校／专业显示名；人物来源；边月份与工作状态 | 人物姓名不入图，展示时从 SQL 批量回查 |
| 投影状态 | 一个 `projection_meta` 控制节点 | 绑定图结构、完整来源快照及查询基准月 |
| 生命周期 | 每空间一份不可变有效快照 | 删除行不入新图，已发布图不原位更新；停服切换成对 SQL／图 |
| 索引 | 本版不建属性索引 | 图查询从已知 VID 开始；名称搜索和复杂背景筛选仍走 SQL |

本版增加有经历依据的直接人物关系边，不把共同经历解释为实际认识。本版不增加职位、项目、组织层级边。同专业可生成 same_major，但不等同同校、同职位或实际认识。公司上下级不扩大同公司范围。

## 2 空间与图键

空间 VID 类型保持 `FIXED_STRING(128)`。样例分区数 1、副本数 1 只用于本机；生产分区、副本和部署规格待规模与环境验证。空间名称每份快照唯一，不复用旧空间名。CREATE SPACE 后需等待元数据可见，再 USE 并执行 TAG／EDGE DDL，不能假设连续发出就立即可用。[空间定义与异步可见性](https://docs.nebula-graph.io/3.8.0/3.ngql-guide/9.space-statements/1.create-space/)

| 图键 | 规则 | MySQL 依据／校验 |
| --- | --- | --- |
| 人物 VID | `p:expert:<id>` 或 `p:resume:<id>` | `experts.id` 或 `resume.id`；来源前缀确定原表；正十进制、无前导零 |
| 公司 VID | `e:<UUID>`，携带 company TAG | `graph_company_entity.id` |
| 学校 VID | `e:<UUID>`，携带 school TAG | `graph_school_entity.id` |
| 专业 VID | `e:<UUID>`，携带 major TAG | `graph_major_entity.id` |
| 控制 VID | `meta:projection` | 项目常量，与来源 VID 命名空间隔离 |
| 经历事实 Rank | `graph_edge_mapping.id`，有符号 64 位正数 | 范围 1 至 2^63−1；不是原经历 ID、UUID 或数组序号 |
| 人物关系 Rank | 同人物对、类型内按证据键排序后编号 | 当前快照局部序号，不回查源表 id，也不承诺跨版本不变 |
| 完整边键 | 起点 VID＋终点 VID＋边类型＋Rank | 不同任职以不同 Rank 并存；端点改变时旧完整键也必须消失 |

UUID 先校验合法性再统一小写；关联键在同一构建内采用同一规范，不按名称生成或合并。三张标准表出现跨类型相同 UUID 必须阻断发布，不允许一个 `e:<UUID>` 同时拥有公司和学校等不同业务 TAG。若未来来源无法保证这一点，需升模型版本再调整实体 VID，不能静默拼接新前缀。

每个业务节点恰有一个本模型业务 TAG；人物来源不等于获客渠道 `experts.source_type`。未交付人物统一结果前，专家和简历同数字 ID 或同姓名仍是两个节点，不自行根据 `experts.resume_id` 合并。

## 3 节点字段

用户已补充需要业务编号、工作和教育信息，范围与推荐位置见 [业务附属信息](../person-business-information.md)。以下仍是已验证 v4 的物理字段，尚未把该扩展写入 DDL；不能将当前字段表视为禁止后续业务属性。

人物节点只保留来源属性，不保存姓名。公司、学校、专业的标准显示名仍保留。节点 VID 已能定位原主键，不再保存 person.id／entity.id；图中不放人物编号、地区、学历、手机、邮箱、费率或长文本履历，附属个人信息按需从 SQL 返回。

| TAG | 属性 | 类型／空值 | 来源 | 写入规则与用途 |
| --- | --- | --- | --- | --- |
| person | source_system | STRING NOT NULL | 由读取专家／简历主表派生 | 固定 expert／resume；须与 VID 前缀及边来源一致；供图内候选来源过滤 |
| company | name | STRING NOT NULL | `graph_company_entity.standard_name` | 公司显示名；允许同名与改名，身份仍为 UUID |
| school | name | STRING NOT NULL | `graph_school_entity.standard_name` | 学校显示名；同名不合并 |
| major | name | STRING NOT NULL | `graph_major_entity.standard_name` | 专业显示名；不作为岗位或学历 |

实体 name 不设默认值，缺失或空白在预检阻断；NOT NULL 本身不能拒绝空字符串。人物姓名即使在来源缺失也不是图节点缺失的判据，其展示由 SQL／API 独立处理。有效人物可以没有可投影经历而成为孤立节点，不能因此断言其没有实际关系。原实体改名后新快照更新实体显示名，UUID 不变。

## 4 边字段与来源

### 4.1 任职边 worked_at

方向：`person -> company`。每条边对应一条经确认归一的原工作经历，Rank 对应一个已确认边槽位。

| 属性 | 类型／空值 | MySQL 来源 | 转换与用途 |
| --- | --- | --- | --- |
| start_month | INT32 NULL | `experts_work_experience.start_date`／`resume_work_experience.start_date` | DATETIME 转 YYYYMM；用于图内时间交集；空值保持未知 |
| end_month | INT32 NULL | 同一工作行 `end_date` | DATETIME 转 YYYYMM；NULL 本身不代表当前任职 |
| is_current | BOOL NOT NULL | 同一工作行 `is_employed` | 1→true、2→false；其他值预检失败；不设默认值掩盖缺失 |

起点来自 `graph_edge_mapping.source_system/source_person_id`，须回连原工作行 expert_id／resume_id 及有效主表一致。终点来自 `standard_entity_id`，须与有效 `graph_name_mapping.company_id` 及 `graph_company_entity.id` 一致。`source_table/source_field/edge_type` 必须是对应工作表／company_name／worked_at；时间和职位不可从其他工作行借用。职位原文 `position_title` 仍从 SQL 同一行展示。

### 4.2 学校边 studied_at

方向：`person -> school`。

| 属性 | 类型／空值 | MySQL 来源 | 转换与用途 |
| --- | --- | --- | --- |
| start_month | INT32 NULL | `experts_education_experience.start_date`／`resume_education_experience.start_date` | DATETIME 转 YYYYMM；未知保留 NULL |
| end_month | INT32 NULL | 同一教育行 `end_date` | DATETIME 转 YYYYMM；未知保留 NULL |

起点须与原教育行 expert_id／resume_id 一致。目标须与有效映射 school_id 及标准学校 UUID 一致；槽位必须是对应教育表／school_name／studied_at。缺日期仍支持同校，但不据此推断同期、在读或毕业。共同学校查询不应依赖日期非空。

### 4.3 专业边 studied_major

方向：`person -> major`。

| 属性 | 类型／空值 | MySQL 来源 | 转换与用途 |
| --- | --- | --- | --- |
| start_month | INT32 NULL | `experts_education_experience.start_date`／`resume_education_experience.start_date` | 同条教育行转换月份 |
| end_month | INT32 NULL | 同一教育行 `end_date` | 同条教育行转换月份 |

目标须与有效映射 major_id 及标准专业 UUID 一致；槽位为对应教育表／major／studied_major。专业和学校边可通过各自 Rank 回 SQL 得到相同教育行 ID，不在图里凭 Rank 顺序或名称配对。无专业映射不影响已确认的学校边，反之亦然；未确认的多目标拆分不能复制为多条假履历。

### 4.4 月份与同期规则

本版将旧候选 start_date／end_date 明确改名 start_month／end_month，避免把整数月份当完整日期。NULL 用数据库 NULL，不用 0、空字符串或 999912 表示未知。输入日期首先必须是合法日期；同一行两端已知时开始不得晚于结束，不能靠截到月份后掩盖日级倒置。允许的实际历史日期范围在接入配置中声明；不把旧原型 1900—2100 范围当上游事实。

当前任职 is_current=true 时 end_date 必须为空，查询临时用显式 reference_month 作为结束月份；不把基准月写回 end_month。非当前而 end_month=NULL 保持未知。开始未知或有效结束未知均不能判定同期，但仍能判断共同公司。图内相交条件为双方 start_month 非空、有效结束非空、各自开始不晚于有效结束，且 `a.start_month <= b.end`、`b.start_month <= a.end`，月份区间包含端点。当前开始晚于基准月时有效区间为空，不能产生同期证据；应同时报告数据／基准问题。

月数用年和月份计算序号后相减加一，不能用 YYYYMM 直接相减；跨年 202312 至 202401 是 2 个月。所选时间窗口与每一对经历求交；不累加多条重叠经历制造阈值。两段连接链分别满足范围即可，不要求三人同一时期。

### 4.5 预计算人物关系边

same_company、same_school、same_major 各存 entity_vid STRING NOT NULL、left_fact_rank INT64 NOT NULL、right_fact_rank INT64 NOT NULL；company_overlap 额外存 overlap_start_month／overlap_end_month INT32 NOT NULL。四类边均为 person→person，按 VID 大小只存一个物理方向，查询双向读取。

每条边保存一对具体经历依据，重复任职与多实体分别保留，人物列表再去重。不同类型和证据共同存在不代表关系评分。人物关系 Rank 是局部序号，真正回查 SQL 使用 left_fact_rank／right_fact_rank；“左／右”固定指存储 src／dst，不随查询方向改变。

完整字段表、入图计算、重算与预算规则见 [人物关系预计算](../person-relation-materialization.md)。事实与关系都完整通过才能 ready，不能只写完经历就称新图已构建。

## 5 回查证据：为何不再复制来源属性

事实查询由图返回完整事实键和 Rank；人物关系／路径查询返回每段人物关系键、共同实体、双方 left_fact_rank／right_fact_rank 和可用交集。SQL 按事实 Rank 查询 `graph_edge_mapping.id`，再取得原经历、人物和实体显示详情。SQL 核对事实键及日期属性与冻结来源一致，用于完整性检查，不重新搜索候选或计算关系。

例如：`p:expert:101 -> e:11111111-1111-4111-8111-111111111111 @7001`，类型 worked_at，图返回 rank=7001。SQL 回查 `graph_edge_mapping.id=7001`，取得 source_system、source_table、source_field_id、source_field、source_person_id、standard_entity_id，再定位原工作行。界面需要的 `slot:7001` 可以由 API 返回时生成，不在图边重复存储。

该设计要求同批次 SQL 中的 graph_edge_mapping 保留全部已投影槽位，id 唯一且不复用于另一经历；SQL 与图必须成对冻结。Rank 仅在完整边键内受图数据库约束，图不会保证它全空间唯一。全局 Rank 唯一、来源槽位稳定、多目标及删除发布规则仍需预检和上游契约；不因 DDL 已定就称这些问题已解决。映射 UUID→Rank 的发布追溯文件继续保留，边表没有的归一映射 UUID 不凭空补列。

| 旧候选字段 | 本版决定 | 理由 |
| --- | --- | --- |
| person.id／entity.id | 删除 | VID 已包含来源主键／UUID |
| entity.kind／边 kind | 删除 | TAG／边类型区分类别 |
| fact_id | 删除 | Rank 回查映射，接口可生成 slot:<Rank> |
| active | 删除 | 新图只发布有效事实；失效事实不进入快照 |
| 边 source_system | 删除 | 起点 person.source_system 用于来源筛选；来源详情回 SQL |
| source_record_id | 删除 | 表名＋原行 ID 可由 SQL 回查派生 |
| 边 source_table／source_field_id／source_field | 删除 | 由同批次 SQL 的 Rank 定位；重复保存不能替代冻结与校验 |
| 教育边 is_current | 删除 | 原表没有对应状态；false 容易被误解为已毕业 |
| role_id、职位／项目边 | 不纳入 | 最新实体范围不支持，不能用旧虚构词典补齐 |

## 6 有效性与删除边界

进入快照须同时满足：原人物与经历未删除、归属一致；graph_edge_mapping.deleted_at 为空；标准实体 is_deleted=0；名称映射 is_deleted=0、已匹配且在明确发布范围；目标类型正确；发布审核值按上游确认规则放行。不得把未知审核枚举自行解释为通过，也不得因 is_deleted=0 就绕过匹配和发布状态。

is_deleted 不存为图属性：新快照直接不包含对应有效事实边，也不包含依赖该事实的预计算人物边。删除一条名称映射不自动删除人物、实体或其他独立经历。处理中缺行不能当删除通知。修改目标或人物归属后必须重算受影响人物关系，验证新图没有旧完整边键；其他有效证据仍可保留人物关系。保留旧空间用于回退，不能只保留 Rank 就声称旧边已清理。本版仍没有在线增量 Worker 或生产删除协议。

## 7 控制节点 projection_meta

控制 TAG 属于本项目发布设计，不是来源表；只允许固定 VID `meta:projection` 一条。业务查询排除它。

| 属性 | 类型／空值 | 来源与用途 |
| --- | --- | --- |
| schema_version | STRING NOT NULL | 当前固定 uuid-relations-v4，区分含姓名旧模型与无姓名新模型 |
| projection_id | STRING NOT NULL | 本次不可变投影唯一标识；不是 source sync_batch_id 的别名 |
| snapshot_sha256 | FIXED_STRING(64) NOT NULL | 完整冻结 SQL 内容和覆盖范围的逻辑摘要；应用校验 64 位小写十六进制 |
| reference_month | INT32 NOT NULL | 发布清单显式基准月份；当前任职解释与 SQL／API 一致 |
| state | STRING NOT NULL | staging／ready；全部预检、回读和对账后才发布 ready |

在 ready 前可以构建和写入新空间；事实层与人物关系层均完整回读、对账后才可 ready，清单记录各类边数量与计算完成范围。ready 并发布清单后不修改此空间。失败不得输出可激活清单。SQL、图、基准月、模型标识与清单必须匹配，请求前后漂移保持错误，不静默回退到 SQL 重算。控制节点不是生产分布式事务，也不能替代外部完整清单、只读账号与停服切换。

## 8 索引、遍历与展示

姓名、别名、公司／学校条件定位继续由 SQL 提供人物／实体 VID；图从这些确定的 VID 做有界遍历，不默认全图 MATCH 扫描。已知 VID 的 FETCH／GO 与按属性搜索是不同入口，官方说明见 [VID 查询入口](https://docs.nebula-graph.io/3.8.0/1.introduction/3.vid/)。本版不建 name、月份、来源属性索引；不把“没有属性索引”等同没有图的邻接访问。日后确需 LOOKUP 再按查询计划增建索引并验证，不为展示名先建全套索引。

事实层人物 A→公司→人物 B 是 2 条物理经历边；预计算后 A→B 是 1 条人物关系边。最多一位中间人物的查询沿 2 条人物边完成，每段仍返回两个原事实 Rank；不能把人物边 Rank 与事实 Rank 混用。G6 展示后端已计算关系和依据，不自行推断。

共同公司、同公司同期、同校优先读取对应人物边，不进行未限定类型的任意最短路；同专业读取 same_major，依据是 studied_major。同一人物对多证据、多类型要去重人物，范围筛选在图内限制实际证据。预计算使超级实体产生平方级人物对，构建前必须估算并验证容量，不静默截取后发布。候选人数、返回行数、RPC、时间和证据预算继续需要。旧有候选分块标签不是本版基础 DDL；是否引入新读索引要在代表性分布下单独验证。

## 9 数据库约束与应用约束

DDL 负责属性类型和 NOT NULL；以下不能靠这份 DDL 自动保证：VID 格式／长度检查、端点已存在且 TAG 正确、来源枚举、非空白名称、合法月份、区间顺序、当前状态一致性、Rank 正值和全局唯一、同条经历约束、跨表 UUID 冲突、删除／发布范围。下一轮适配必须在写图前预检，再对图回读核对，失败不发布。仅建出 TAG 和 EDGE 不等于完成图谱构建。

同一完整边键再次 INSERT 可能覆盖属性，不能用“INSERT 成功”证明没有重复或版本冲突；导入器应在写入前检查完整边键唯一。不要省略 Rank 使用默认 0；不要把自动生成序号当作稳定经历键。无 TTL，不按时间自动删除历史经历。

## 10 验证与下一步

事实层历史验证入口为 `backend/.venv/bin/python scripts/verify_graph_ddl.py --output <新报告.json>`；当前人物关系层入口为 `backend/.venv/bin/python scripts/verify_person_relation_ddl.py --output <新报告.json>`。后者在两个新空间实际演示写事实、图计算、写人物边、读取及失效后重算。只用本机凭据，不输出密码；仅写本次新空间并清理，不启动容器、不重置认证、不访问 Supabase 或 MySQL，输出不可覆盖。

历史事实层验证见 [DDL 验证记录](../graph-ddl-validation.md)，人物关系层及同专业历史验证见 [v3 验证](../person-relations-v3-validation.md)。当前无姓名模型增加人物属性白名单、所有人物回读及旧姓名写入拒绝检查，见 [隐私验证](../graph-privacy-validation.md)。均为独立小样例，不包含 SQL 姓名回查、API 迁移、生产发布或容量。

下一轮需新增 UUID 新模型适配、完整来源预检、Rank 证据回查及查询代码，再单独建模拟 MySQL／图和 API 清单，验证两入口、分页、路径、证据、导出和版本切换。现有 source-slots-v2 清单／空间不可直接套本 DDL，旧演示服务继续保持；DDL 验证通过不代表这些迁移已经完成。
