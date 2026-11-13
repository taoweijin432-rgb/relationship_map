# 人物关系图谱字段与 MySQL 对应说明

文档版本 v5.0 ｜2026-11-06 ｜字段整理轮次 v0.23 ｜图模型 uuid-relations-v5

2026-11-10目标来源更新并完成本机验证。文件映射版五张MySQL表58列由同事维护，graph_edge_mapping为权威事实映射，id直接用于图Rank。名称JSON和UUID解析用于上游生成映射表，本项目直接消费表关联。v0.35的numeric-authoritative-v1已去除名称表依赖，并完成13表228列、262人及真实MySQL协议到原生图验证，详情见[原生记录](mysql-latest-native-validation.md)。数字HTTP／前端和正式来源仍待接入，本文v5.0及Word保留历史UUID字段映射，旧15表251列按历史范围解释。

实施状态补充：v0.24 已按这些图字段迁移本机虚构快照并切换 API／页面，详见 [迁移报告](uuid-graph-migration.md)。本文与 Word 的字段规范保留 v5.0，不把本轮最小 SQL 模拟子集当作正式15表接入。

本文面向数据库交付人员与项目开发人员，回答两件事：构建图数据库分别需要哪些 MySQL 字段；图查询得到人物和证据引用后，页面还需要回查哪些字段。正文按每种图节点和边组织，明确直接复制、转换、图内预计算和项目元数据；附录反向列出 15 张 MySQL 表的 251 列去向。

人物姓名不写入图，只在 API 批量回查配套 MySQL 后展示。业务编号允许入图，工作与教育属性绑定具体经历。四类人物关系在新图发布前计算保存。本文更新字段对应文档，不修改上游 Word、DDL、数据库、图空间或服务，不访问 Supabase；不把旧应用或小样例结果描述成真实数据接入。

## 1 依据与阅读方式

| 依据 | 当前采用内容 |
| --- | --- |
| 当前物理图定义 | infra/nebula/schema/uuid-facts-v3.ngql 与 person-relations-v3.ngql；5 个 TAG、7 类 EDGE，共 42 个属性，不含图键。 |
| 最新 MySQL 归一及投影设计 | 精简版(3)当前本地文件；7 表 81 列，含 graph_name_mapping.is_deleted；来源 SHA-256 为 e96f2a54db67d5a541f8116841f3a1de37b4dbc336ce4981d4f4454970e3c030。 |
| 原人物和经历 | 已提供专家 DDL 的 4 表 85 列；用户确认简历结构 expert 对应改为 resume，合计 8 表 170 列。 |
| 决定与范围 | 人物身份、跨库关联及实体归一由上游负责。旧独立 BIGINT 实体词典、旧 entity TAG 和旧边属性候选不再使用。 |

当前 MySQL Word 不是完整正式 CREATE TABLE SQL，graph_edge_mapping 的可空性原文未列；下文图中必需项是构建要求，不伪称源表已具备同等约束。简历表名按确认规则为 resume、resume_work_experience、resume_project_experience、resume_education_experience。

| 数据用途 | 处理方式 |
| --- | --- |
| 写入图属性 | 复制或转换到本版明确列出的图字段，不透传人物整行。 |
| 构建关联与过滤 | 用于人物归属、目标确认、删除及发布判断，不一定成为图属性。 |
| 仅 SQL 回查展示 | 按请求与权限读取，姓名等不入图；本文件不代表所有可选详情都已批准开放。 |
| 本版不使用 | 不投影、不默认查询，仍在原 MySQL 留存；字段存在不等于已支持相关功能。 |

## 2 构建关联链与来源定位

| 步骤 | MySQL 表与字段 | 校验规则 |
| --- | --- | --- |
| 定位原经历 | graph_name_mapping.source_namespace＋source_field_id → 对应原经历表.id | 命名空间须明确到来源、表及字段含义；字符串经历键先验证无损回连，不当人物 ID。 |
| 确认原人物 | 原经历 expert_id／resume_id → experts.id／resume.id | 有效原人物存在；不得根据姓名或 experts.resume_id 自行合并跨库人物。 |
| 确认标准实体 | entity_type 选择 company_id／school_id／major_id → 对应 *_entity.id | 正确类别仅有确认目标；映射已匹配且 is_deleted=0，实体有效并在发布范围。 |
| 确认事实槽位 | graph_edge_mapping.source_system、source_table、source_field_id、source_field、source_person_id、standard_entity_id、edge_type | 必须与原经历、人物、名称映射及目标一致；id 为事实 Rank。 |
| 生成图关系 | 已验证事实边 → same_company／company_overlap／same_school／same_major | 图内计算；各边保留共同实体和双方事实 Rank，不要求上游新增人物关系表。 |

名称映射没有 raw_name、item_no、source_record_id，不恢复旧列。边表 source_field_id 为原经历数值键，名称映射同名列为 VARCHAR(128)，不能凭字段同名直接混用。删除标志为 1 的映射不得生成有效事实，即使 processing_status=已匹配。

每份图必须配套完整冻结 SQL、基准月和发布清单；sync_batch_id 是最近同步批次，不天然等于全表一致快照。核验状态放行值、完整批次、来源命名空间、多目标与删除通知仍需双方契约，本文不虚构枚举或自动处理多目标。

## 3 人物节点 person

| 图字段与类型 | 用途 | MySQL 来源表 | MySQL 来源字段 | 转换与空值规则 |
| --- | --- | --- | --- | --- |
| VID FIXED_STRING(128) 图键 | 人物身份与 SQL 回查 | experts／resume | id；来源主表类别 | 生成 p:expert:<id>／p:resume:<id>；正十进制原键。NULL、缺人物或归属矛盾阻断。 |
| source_system STRING NOT NULL | 来源过滤 | experts／resume | 来源主表类别，无同名源列 | 派生 expert／resume，须与 VID 一致；不是 source_type 获客渠道。 |
| serial_number STRING NOT NULL | 业务编号展示与定位 | experts／resume | serial_number | 保留有效原值；源 CHAR(19)，拒绝空白／超长。同源唯一，跨源重号不合并人物。 |

person 不含 name 或任何姓名替代字段。姓名、昵称、地区、工作年限及人物学历摘要仅在展示请求中回 SQL，不复制到节点、边、payload 或姓名散列索引。业务编号仍能回连个人，不能把无姓名图称为完全匿名。

## 4 公司学校专业节点

### 公司节点 company

| 图字段与类型 | 用途 | MySQL 来源表 | MySQL 来源字段 | 转换与空值规则 |
| --- | --- | --- | --- | --- |
| VID FIXED_STRING(128) 图键 | 公司身份 | graph_company_entity | id | 生成 e:<UUID>，统一合法 UUID 表示；三表跨类型 UUID 冲突须阻断。 |
| name STRING NOT NULL | 公司标准名称展示 | graph_company_entity | standard_name | 拒绝空白，允许同名；改名不更换 UUID，不按名称判断相同实体。 |
| company_code STRING NOT NULL | 公司业务编号 | graph_company_entity | company_code | 源 VARCHAR(64)，保留有效原值并核对同表唯一；业务编号不代替 UUID。 |

### 学校节点 school

| 图字段与类型 | 用途 | MySQL 来源表 | MySQL 来源字段 | 转换与空值规则 |
| --- | --- | --- | --- | --- |
| VID FIXED_STRING(128) 图键 | 学校身份 | graph_school_entity | id | 生成 e:<UUID>，统一合法 UUID 表示；三表跨类型 UUID 冲突须阻断。 |
| name STRING NOT NULL | 学校标准名称展示 | graph_school_entity | standard_name | 拒绝空白，允许同名；改名不更换 UUID，不按名称判断相同实体。 |
| school_code STRING NOT NULL | 学校业务编号 | graph_school_entity | school_code | 源 VARCHAR(64)，保留有效原值并核对同表唯一；业务编号不代替 UUID。 |

### 专业节点 major

| 图字段与类型 | 用途 | MySQL 来源表 | MySQL 来源字段 | 转换与空值规则 |
| --- | --- | --- | --- | --- |
| VID FIXED_STRING(128) 图键 | 专业身份 | graph_major_entity | id | 生成 e:<UUID>，统一合法 UUID 表示；三表跨类型 UUID 冲突须阻断。 |
| name STRING NOT NULL | 专业标准名称展示 | graph_major_entity | standard_name | 拒绝空白，允许同名；改名不更换 UUID，不按名称判断相同实体。 |
| major_code STRING NOT NULL | 专业业务编号 | graph_major_entity | major_code | 源 VARCHAR(64)，保留有效原值并核对同表唯一；业务编号不代替 UUID。 |

三个节点各自使用 company／school／major TAG，不再保存重复 id／kind。school_code 不等于 official_code，major.name 不代表个人学历或岗位；历史名称、学校地区与官方代码仅从 SQL 按需展示。

## 5 任职经历边 worked_at

| 图字段与类型 | 用途 | MySQL 来源表 | MySQL 来源字段 | 转换与空值规则 |
| --- | --- | --- | --- | --- |
| src VID 图键 | 具体经历所属人物 | graph_edge_mapping；experts_work_experience／resume_work_experience；原人物表 | source_system、source_person_id；expert_id／resume_id；id | 按来源生成人物 VID；槽位与原经历归属须一致且有效。 |
| dst VID 图键 | 标准公司身份 | graph_edge_mapping；graph_name_mapping；graph_company_entity | standard_entity_id；company_id；id | 三个 UUID 必须一致且类别正确，生成 e:<UUID>。 |
| type 图键 | 经历关系类型 | graph_edge_mapping | edge_type、source_table、source_field | 固定 worked_at；相应原表字段必须为 company_name。 |
| Rank INT64 图键 | 事实来源引用 | graph_edge_mapping | id | 有符号64位正数；不是原经历 ID、映射 UUID 或局部序号。 |
| experience_key STRING NOT NULL | 任职经历归组 | graph_edge_mapping；experts_work_experience／resume_work_experience | source_system、source_table、source_field_id；原行 id | 派生 <来源>:<原表>:<原行ID>；核对无损回连，非上游同名列。 |
| position_title STRING NULL | 该次任职职位 | experts_work_experience／resume_work_experience | position_title | 有效原文保留，空字符串／纯空白转 NULL；未得到职位归一 ID，不自行造 role_id。 |
| start_month INT32 NULL | 开始月份 | experts_work_experience／resume_work_experience | start_date | 合法原日期转 YYYYMM；NULL 保留未知，先检查日级区间。 |
| end_month INT32 NULL | 结束月份 | experts_work_experience／resume_work_experience | end_date | 合法日期转 YYYYMM；NULL 不能单独解释为在职。 |
| is_current BOOL NOT NULL | 当前任职状态 | experts_work_experience／resume_work_experience | is_employed | 1→true、2→false；其他值阻断；true 时原结束日期必须为空。 |

公司、职位和日期必须来自同一条工作行。company_name 的原文留 SQL，目标取确认的标准 UUID；工作内容不混入职位字段，人物主表 company／job_name 不能替代此经历事实。

## 6 学校经历边 studied_at

| 图字段与类型 | 用途 | MySQL 来源表 | MySQL 来源字段 | 转换与空值规则 |
| --- | --- | --- | --- | --- |
| src VID 图键 | 具体经历所属人物 | graph_edge_mapping；experts_education_experience／resume_education_experience；原人物表 | source_system、source_person_id；expert_id／resume_id；id | 按来源生成人物 VID；槽位与原经历归属须一致且有效。 |
| dst VID 图键 | 标准学校身份 | graph_edge_mapping；graph_name_mapping；graph_school_entity | standard_entity_id；school_id；id | 三个 UUID 必须一致且类别正确，生成 e:<UUID>。 |
| type 图键 | 经历关系类型 | graph_edge_mapping | edge_type、source_table、source_field | 固定 studied_at；相应原表字段必须为 school_name。 |
| Rank INT64 图键 | 事实来源引用 | graph_edge_mapping | id | 有符号64位正数；不是原经历 ID、映射 UUID 或局部序号。 |
| experience_key STRING NOT NULL | 同条教育配对 | graph_edge_mapping；experts_education_experience／resume_education_experience | source_system、source_table、source_field_id；原行 id | 派生经历组键，与同原行专业边一致；不靠 Rank 序号配对。 |
| education_level STRING NULL | 此次教育学历 | experts_education_experience／resume_education_experience | education_level | 保留原有效文本，空白转 NULL；不从主表 education 或专业名称猜填。 |
| is_regular_enrollment STRING NULL | 此次统招信息 | experts_education_experience／resume_education_experience | is_regular_enrollment | 原 VARCHAR(255) 文本保留，空白转 NULL；不猜测 BOOL／枚举。 |
| start_month INT32 NULL | 教育开始月份 | experts_education_experience／resume_education_experience | start_date | 合法原日期转 YYYYMM；未知保留 NULL。 |
| end_month INT32 NULL | 教育结束月份 | experts_education_experience／resume_education_experience | end_date | 合法原日期转 YYYYMM；未知不推断在读／毕业。 |

同校不要求教育日期，也不证明同届或实际认识。无学校确认映射时不伪造目标；已确认的专业事实仍可独立保留。

## 7 专业经历边 studied_major

| 图字段与类型 | 用途 | MySQL 来源表 | MySQL 来源字段 | 转换与空值规则 |
| --- | --- | --- | --- | --- |
| src VID 图键 | 具体经历所属人物 | graph_edge_mapping；experts_education_experience／resume_education_experience；原人物表 | source_system、source_person_id；expert_id／resume_id；id | 按来源生成人物 VID；槽位与原经历归属须一致且有效。 |
| dst VID 图键 | 标准专业身份 | graph_edge_mapping；graph_name_mapping；graph_major_entity | standard_entity_id；major_id；id | 三个 UUID 必须一致且类别正确，生成 e:<UUID>。 |
| type 图键 | 经历关系类型 | graph_edge_mapping | edge_type、source_table、source_field | 固定 studied_major；相应原表字段必须为 major。 |
| Rank INT64 图键 | 事实来源引用 | graph_edge_mapping | id | 有符号64位正数；不是原经历 ID、映射 UUID 或局部序号。 |
| experience_key STRING NOT NULL | 同条教育配对 | graph_edge_mapping；experts_education_experience／resume_education_experience | source_system、source_table、source_field_id；原行 id | 派生经历组键，与同原行专业边一致；不靠 Rank 序号配对。 |
| education_level STRING NULL | 此次教育学历 | experts_education_experience／resume_education_experience | education_level | 保留原有效文本，空白转 NULL；不从主表 education 或专业名称猜填。 |
| is_regular_enrollment STRING NULL | 此次统招信息 | experts_education_experience／resume_education_experience | is_regular_enrollment | 原 VARCHAR(255) 文本保留，空白转 NULL；不猜测 BOOL／枚举。 |
| start_month INT32 NULL | 教育开始月份 | experts_education_experience／resume_education_experience | start_date | 合法原日期转 YYYYMM；未知保留 NULL。 |
| end_month INT32 NULL | 教育结束月份 | experts_education_experience／resume_education_experience | end_date | 合法原日期转 YYYYMM；未知不推断在读／毕业。 |

同一 education 原行投影的学校／专业边，其 experience_key、学历、统招和时间应一致；这不是两次教育。专业和学校并非按名称、item_no 或目标列表位置配对。

## 8 预计算人物关系边

| 图键项 | 生成依据 | 回查规则 |
| --- | --- | --- |
| src／dst VID | 人物对按 ASCII VID 从小到大存一个方向，查询可双向 | src、dst 各自回查原人物主表；反向查询不交换属性中左／右定义。 |
| type | same_company／company_overlap／same_school／same_major | 图内计算的规则类别，没有直接对应的 MySQL 人物关系列。 |
| 人物关系 Rank | 同 type、src、dst 内按 (entity_vid,left_fact_rank,right_fact_rank) 排序编号 1..N | 快照局部证据序号，不查 graph_edge_mapping.id；跨版本不保证不变。 |

### 同公司 same_company

| 图字段与类型 | 用途 | MySQL 来源表 | MySQL 来源字段 | 转换与空值规则 |
| --- | --- | --- | --- | --- |
| entity_vid STRING NOT NULL | 共同标准实体 | graph_company_entity；graph_edge_mapping | id；双方 standard_entity_id | 取两条 worked_at 的共同终点；由图关系派生，不按名称相似匹配。 |
| left_fact_rank INT64 NOT NULL | 存储 src 的经历证据 | graph_edge_mapping | id（src 的 worked_at 槽位） | 取图事实 Rank；须存在 src→entity 的对应事实。 |
| right_fact_rank INT64 NOT NULL | 存储 dst 的经历证据 | graph_edge_mapping | id（dst 的 worked_at 槽位） | 取另一条事实 Rank；须存在 dst→entity 的对应事实。 |

### 同公司同期 company_overlap

| 图字段与类型 | 用途 | MySQL 来源表 | MySQL 来源字段 | 转换与空值规则 |
| --- | --- | --- | --- | --- |
| entity_vid STRING NOT NULL | 共同标准实体 | graph_company_entity；graph_edge_mapping | id；双方 standard_entity_id | 取两条 worked_at 的共同终点；由图关系派生，不按名称相似匹配。 |
| left_fact_rank INT64 NOT NULL | 存储 src 的经历证据 | graph_edge_mapping | id（src 的 worked_at 槽位） | 取图事实 Rank；须存在 src→entity 的对应事实。 |
| right_fact_rank INT64 NOT NULL | 存储 dst 的经历证据 | graph_edge_mapping | id（dst 的 worked_at 槽位） | 取另一条事实 Rank；须存在 dst→entity 的对应事实。 |
| overlap_start_month INT32 NOT NULL | 交集开始 | experts_work_experience／resume_work_experience | 双方 start_date | 图内取双方开始月较大值；双方区间须已知且有效。 |
| overlap_end_month INT32 NOT NULL | 交集结束 | experts_work_experience／resume_work_experience；发布清单 | 双方 end_date、is_employed；reference_month | 图内取有效结束月较小值；当前任职空结束仅用基准月解释。 |

### 同校 same_school

| 图字段与类型 | 用途 | MySQL 来源表 | MySQL 来源字段 | 转换与空值规则 |
| --- | --- | --- | --- | --- |
| entity_vid STRING NOT NULL | 共同标准实体 | graph_school_entity；graph_edge_mapping | id；双方 standard_entity_id | 取两条 studied_at 的共同终点；由图关系派生，不按名称相似匹配。 |
| left_fact_rank INT64 NOT NULL | 存储 src 的经历证据 | graph_edge_mapping | id（src 的 studied_at 槽位） | 取图事实 Rank；须存在 src→entity 的对应事实。 |
| right_fact_rank INT64 NOT NULL | 存储 dst 的经历证据 | graph_edge_mapping | id（dst 的 studied_at 槽位） | 取另一条事实 Rank；须存在 dst→entity 的对应事实。 |

### 同专业 same_major

| 图字段与类型 | 用途 | MySQL 来源表 | MySQL 来源字段 | 转换与空值规则 |
| --- | --- | --- | --- | --- |
| entity_vid STRING NOT NULL | 共同标准实体 | graph_major_entity；graph_edge_mapping | id；双方 standard_entity_id | 取两条 studied_major 的共同终点；由图关系派生，不按名称相似匹配。 |
| left_fact_rank INT64 NOT NULL | 存储 src 的经历证据 | graph_edge_mapping | id（src 的 studied_major 槽位） | 取图事实 Rank；须存在 src→entity 的对应事实。 |
| right_fact_rank INT64 NOT NULL | 存储 dst 的经历证据 | graph_edge_mapping | id（dst 的 studied_major 槽位） | 取另一条事实 Rank；须存在 dst→entity 的对应事实。 |

同公司可非同期或日期未知；同期是同公司的子集。同校不要求同期，同专业不要求同校／同期。每条人物边对应一对事实证据，多次经历分别保留；列表去重人物，不累加评分，也不推断实际认识。“同校同专业”还须核对双方各自的同条教育组键，不能拼接独立关系。

## 9 投影控制节点 projection_meta

| 图字段与类型 | 用途 | MySQL 来源表 | MySQL 来源字段 | 转换与空值规则 |
| --- | --- | --- | --- | --- |
| VID 图键 | 控制节点定位 | 无 MySQL 来源 | 项目常量 | 固定 meta:projection，仅一条，不进入人物关系搜索。 |
| schema_version STRING NOT NULL | 识别物理模型 | 无直接 MySQL 来源 | 项目常量 | 固定 uuid-relations-v5，不能修改旧空间标记冒充迁移。 |
| projection_id STRING NOT NULL | 整份投影唯一身份 | 无单列直接来源 | 构建／发布清单生成 | 不是 graph_sync_batch.id，标识不得包含人物姓名。 |
| snapshot_sha256 FIXED_STRING(64) NOT NULL | 成对来源完整性 | 本批次覆盖的原表、实体、归一和槽位 | 冻结范围及逻辑内容 | 整体规范化摘要，64位小写十六进制；不是某个姓名散列。 |
| reference_month INT32 NOT NULL | 当前任职解释基准 | 无直接 MySQL 来源 | 发布配置显式给定 | 合法 YYYYMM，与 SQL／图／API 一致，不能从系统当前日期暗取。 |
| state STRING NOT NULL | 发布就绪状态 | 无直接 MySQL 来源 | 构建阶段管理 | staging／ready；事实、人物边和来源回读均完整后才可 ready。 |

graph_sync_batch.status 的完成枚举、snapshot_at 与计数仅是来源发布线索，不直接转换为 ready。最近 sync_batch_id 不要求全表每行同号；完整 SQL／图清单、覆盖来源、截止点、删除与历史保留仍需发布契约。

## 10 人物显示字段回查

以下描述允许规划的回查范围，不代表已完成前端或权限实现。默认取关系页面必需的信息；可选详情仅按请求及权限读取，不做 SELECT *。姓名从配套冻结 SQL 按来源批量回查，不进图、不进图写入日志或显示 DTO 的回写负载；若将来要展示实时库最新姓名，须另定版本语义。

| 展示项 | MySQL 来源表 | 来源字段 | 用途与空值规则 | 使用边界 |
| --- | --- | --- | --- | --- |
| 姓名 | experts／resume | name | 由 VID 定位；原 NOT NULL，空白／缺行需明确显示状态。 | 页面及人物卡片必需；只在授权响应中展示。 |
| 业务编号 | experts／resume | serial_number | 图已有副本，详情可回 SQL 核对；同源定位。 | 不能据编号跨库自动合并。 |
| 人物列表摘要 | experts／resume | company、job_name、job_status | 保留来源主表摘要，1现任／2曾任按原枚举。 | 不是标准公司目标，也不替代具体工作事实。 |
| 地区 | experts／resume | country、province、city | 源空字符串视作未提供，不猜所在地。 | 可选详情／条件，不写入本版人物节点。 |
| 工作年限与学历摘要 | experts／resume | work_years、education | 保留原值，NULL／空串不计算补齐。 | 可选摘要，不能替代每次教育的 education_level。 |
| 来源更新时间 | experts／resume | updated_at | 显示原行更新时间，NULL 保留未知。 | 不是图发布日期或 reference_month。 |
| 来源链接与简介 | experts／resume | source_link、personal_intro、background | 按需回查，控制长文本范围。 | 可选详情，不自动进入图、关系证据或默认导出。 |

昵称、年龄、性别、评价、费率、附件、联系方式等不属于本版默认人物关系展示。phone 在提供 DDL 中已标弃用，不能把它当有效联系方式来源；若后续要展示电话，需另取有效联系方式表契约与权限。旧 edu_experience JSON 不默认替代结构化教育表，冲突由上游确认。

## 11 履历证据和实体详情回查

| 展示项 | MySQL 来源表 | 来源字段 | 用途与空值规则 | 使用边界 |
| --- | --- | --- | --- | --- |
| 工作原文与详情 | experts_work_experience／resume_work_experience | company_name、position_title、start_date、end_date、is_employed、work_description | 从事实 Rank 回槽位后按原行 id 查询；保留完整日期和具体内容。 | 职位、公司、日期必须同一工作行。 |
| 教育原文与详情 | experts_education_experience／resume_education_experience | school_name、major、education_level、is_regular_enrollment、start_date、end_date | 按相同原教育行查全字段，NULL 不补齐。 | 可展示未归一原文，但不能冒充标准实体关系。 |
| 经历修改时间 | experts_work_experience／resume_work_experience；experts_education_experience／resume_education_experience | updated_at | 原行更新时间，可 NULL。 | 帮助定位来源修正，不在图新增每行更新时间属性。 |
| 标准实体名称与编号 | graph_company_entity／graph_school_entity／graph_major_entity | standard_name；company_code／school_code／major_code | 按实体类型与 UUID 读取，可核对图中副本。 | 同名不同 UUID 必须区分。 |
| 公司学校历史名称 | graph_company_entity／graph_school_entity | former_names | JSON 数组按原结构展示；NULL 为未提供。 | 别名有歧义，不凭名称自动改变经历归一结果。 |
| 学校官方标识与地区 | graph_school_entity | official_code、country_region、city | 允许 NULL，official_code 非唯一。 | 可选实体详情，school_code 是另一个字段。 |
| 核验与来源更新时间 | 三张 *_entity 标准表 | verification_status、source_updated_at | 原值展示需解释已确认枚举。 | 核验放行规则未定时不能自称已审核。 |

实体有效性、归一映射和原经历仍应来自同批次完整范围；发生缺行、失效、目标或属性漂移时按错误／明确状态处理，不拿旧姓名或其他经历的职位、学历补位。

## 12 回查步骤和关联示例

| 环节 | 定位方法 | 必须保持的条件 |
| --- | --- | --- |
| 人物姓名 | 拆分 p:expert:101 → experts.id=101；按来源分组后批量读取 name | 源表必须在允许列表；不能用客户传入的任意表名拼 SQL。 |
| 事实证据 | worked_at Rank=7001 → graph_edge_mapping.id=7001 → 原经历表.id=source_field_id | source_person_id、目标、类型与图一致，取同批冻结 SQL。 |
| 人物关系证据 | 读取 left_fact_rank／right_fact_rank，各自按事实流程回查 | 人物边本身的 Rank 不是源表 ID；左／右按存储 src／dst。 |
| 学校专业配对 | 双方教育边 experience_key 相同，回查为同一教育表原行 | 不比较数组位置，不把同人物两段教育拼接。 |

虚构示例：人物边 p:expert:101→p:resume:102，type=company_overlap、人物 Rank=1、left_fact_rank=7001、right_fact_rank=7003。先回查槽位 7001／7003，取得各自原工作行，而不是查询槽位 1；再分别读取双方 name 和 work_description 用于展示。人物业务号、时间、岗位及共同实体副本须与本投影来源一致，API 装配后的姓名不回写图。

SQL 负责来源详情与完整性核对，不重新搜索候选或计算人物关系。权限拒绝或 SQL 故障不得伪装成“没有关系”。当前生产身份认证、字段权限、API 新模型回查和导出权限尚未完成，本文是对应契约，不是上线验收。

## 13 有效性与发布校验

| 校验项 | MySQL 依据 | 对图的影响 |
| --- | --- | --- |
| 原人物／经历有效 | 原表 deleted_at 为空，归属存在 | 失效人物或经历不投影；经历失效后其人物证据也不进新版本。 |
| 标准目标有效 | *_entity.is_deleted=0，核验及发布范围确认 | 目标有效且类型正确；is_deleted 与 deleted_at 矛盾需定位。 |
| 归一映射有效 | graph_name_mapping.processing_status、is_deleted 与唯一确认目标 | 须已匹配且 is_deleted=0；多目标不取第一条、不无条件复制日期。 |
| 事实槽位有效 | graph_edge_mapping.deleted_at 为空，来源／人物／目标／类型一致 | 稳定 id 不等于旧边已清理；完整键变化须重建验证。 |
| 时间合法 | 原 start_date／end_date、is_employed | 先日级合法与顺序，再转 YYYYMM；非当前缺结束不推断同期。 |
| 版本完整 | 覆盖清单、来源批次及整体摘要 | 事实和四类人物边均完成才 ready；预算不足不截断冒充完整。 |

父子公司关系不扩大同公司，JSON 数字 0 同时可能是无关系或未知，不能推断确认没有关系；SQL NULL 语义仍待确认。公司层级、项目、推荐关系、证书等没有因本文件列出源字段就自动纳入图范围。

本轮仅文档与覆盖核对，未运行新数据库／API 验收。现有图独立样例验证见 graph-business-fields-validation.md，其 24 项结果不是本轮新增验证，更不是生产容量结论。

## 14 MySQL 逐字段去向附录

附录覆盖 15 表 251 列。源类型／可空性按原 DDL 和最新字段表保留，图的必需性单独定义；尤其边映射表可空性原文未列，不将图要求伪装成上游已有约束。每列标明入图、构建、仅回查或本版不使用；“仅回查”不代表默认开放全部字段。

| 表或表组 | 字段数量 | 本版作用 |
| --- | --- | --- |
| experts／resume | 各47 | 人物来源、业务编号；姓名及人物详情回查。 |
| 两张工作表 | 各13 | 人物任职、职位、月份及原文证据。 |
| 两张教育表 | 各13 | 学校／专业、教育附属信息及同条经历。 |
| 两张项目表 | 各12 | 留原库，本版不投影或默认查询。 |
| 三张标准实体表 | 13／14／10 | UUID、名称、业务code与有效性。 |
| graph_name_mapping | 12 | 归一目标及来源关联与删除过滤。 |
| graph_company_relation | 11 | 来源保留，本版不投影层级关系。 |
| graph_sync_batch | 10 | 来源批次线索，不直接替代图发布清单。 |
| graph_edge_mapping | 11 | 事实 Rank、源行、人物与目标槽位。 |

### experts

| experts 字段 | 源类型 | 源可空性 | 本版去向 |
| --- | --- | --- | --- |
| id | INT | NOT NULL | 生成 person VID，回查身份；不重复存 source_id。 |
| serial_number | CHAR(19) | NOT NULL | 写 person.serial_number；详情可核对。 |
| name | VARCHAR(50) | NOT NULL | 仅 SQL 批量回查显示，禁止写图或姓名替代属性。 |
| interview_nickname | VARCHAR(50) | NOT NULL | 个人附属信息留 SQL，本版不默认展示或投影。 |
| company | VARCHAR(100) | NOT NULL | 仅 SQL 主表摘要；不是标准任职关系目标。 |
| job_status | TINYINT | NOT NULL | 仅 SQL 摘要状态，不替代每次工作 is_employed。 |
| job_name | VARCHAR(255) | NOT NULL | 仅 SQL 主表职位摘要，不替代工作行 position_title。 |
| contact_status | TINYINT | NOT NULL | 原业务字段保留 SQL，本版不投影、不默认查询或推导关系。 |
| doubtful_flag | TINYINT | NOT NULL | 原业务字段保留 SQL，本版不投影、不默认查询或推导关系。 |
| country | VARCHAR(50) | NOT NULL | 可选 SQL 地区详情，不入图。 |
| province | VARCHAR(50) | NOT NULL | 可选 SQL 地区详情，不入图。 |
| city | VARCHAR(50) | NOT NULL | 可选 SQL 地区详情，不入图。 |
| email | VARCHAR(64) | NOT NULL | 联系方式留 SQL，本版不默认查询、不入图；另行定义授权用途。 |
| country_code | VARCHAR(5) | NOT NULL | 联系方式留 SQL，本版不默认查询、不入图；另行定义授权用途。 |
| phone | VARCHAR(30) | NOT NULL | 原字段已弃用；本版不使用，不作为有效联系方式来源。 |
| abroad_flag | TINYINT | NOT NULL | 原业务字段保留 SQL，本版不投影、不默认查询或推导关系。 |
| other_contacts | VARCHAR(50) | NOT NULL | 联系方式留 SQL，本版不默认查询、不入图；另行定义授权用途。 |
| currency | CHAR(10) | NOT NULL | 原业务字段保留 SQL，本版不投影、不默认查询或推导关系。 |
| rate_value | DECIMAL(22,4) | NOT NULL | 原业务字段保留 SQL，本版不投影、不默认查询或推导关系。 |
| rate_type | TINYINT | 可 NULL | 原业务字段保留 SQL，本版不投影、不默认查询或推导关系。 |
| background | TEXT | NOT NULL | 可选 SQL 背景详情，不入图。 |
| comment | TEXT | 可 NULL | 原业务字段保留 SQL，本版不投影、不默认查询或推导关系。 |
| edu_experience | TEXT | 可 NULL | 旧教育 JSON 留 SQL，不默认替代结构化教育经历。 |
| personal_intro | TEXT | 可 NULL | 可选 SQL 个人简介，不入图。 |
| remark | TEXT | 可 NULL | 原业务字段保留 SQL，本版不投影、不默认查询或推导关系。 |
| certification_file | VARCHAR(500) | 可 NULL | 原业务字段保留 SQL，本版不投影、不默认查询或推导关系。 |
| source_type | TINYINT | NOT NULL | 仅 SQL 获客渠道，可选详情；不作 person.source_system。 |
| source_link | VARCHAR(255) | 可 NULL | 可选 SQL 来源链接，不入图。 |
| recommend_expert_id | INT | 可 NULL | 原推荐业务留 SQL，本版不生成推荐人物边。 |
| supplier_contract_id | INT | 可 NULL | 原业务字段保留 SQL，本版不投影、不默认查询或推导关系。 |
| collaborate_num | INT | NOT NULL | 原业务字段保留 SQL，本版不投影、不默认查询或推导关系。 |
| last_collaborate_time | INT | NOT NULL | 原业务字段保留 SQL，本版不投影、不默认查询或推导关系。 |
| create_by | BIGINT | 可 NULL | 原业务字段保留 SQL，本版不投影、不默认查询或推导关系。 |
| update_by | BIGINT | 可 NULL | 原业务字段保留 SQL，本版不投影、不默认查询或推导关系。 |
| created_at | DATETIME(3) | 可 NULL | 原业务字段保留 SQL，本版不投影、不默认查询或推导关系。 |
| updated_at | DATETIME(3) | 可 NULL | 仅 SQL 原行更新时间，不是图版本时间。 |
| deleted_at | DATETIME(3) | 可 NULL | 构建有效人物过滤；删除时间不写 person。 |
| age | INT | 可 NULL | 个人附属信息留 SQL，本版不默认展示或投影。 |
| education | VARCHAR(20) | NOT NULL | 可选 SQL 学历摘要，不替代教育行学历。 |
| work_years | INT | 可 NULL | 可选 SQL 工作年限，不自动计算补齐。 |
| gender | TINYINT(1) | NOT NULL | 个人附属信息留 SQL，本版不默认展示或投影。 |
| certifications | TEXT | 可 NULL | 原业务字段保留 SQL，本版不投影、不默认查询或推导关系。 |
| self_appraisal | TEXT | 可 NULL | 原业务字段保留 SQL，本版不投影、不默认查询或推导关系。 |
| content_version | BIGINT UNSIGNED | NOT NULL | 原合规内容版本留 SQL，不等于 projection_id／图版本。 |
| update_resume_time | VARCHAR(30) | NOT NULL | 原业务字段保留 SQL，本版不投影、不默认查询或推导关系。 |
| resume_id | INT | 可 NULL | 原业务关联留 SQL，不据此自行跨库统一人物。 |
| is_plugin | TINYINT | 可 NULL | 原业务字段保留 SQL，本版不投影、不默认查询或推导关系。 |

### experts_work_experience

| experts_work_experience 字段 | 源类型 | 源可空性 | 本版去向 |
| --- | --- | --- | --- |
| id | INT | NOT NULL | 派生 worked_at.experience_key，回查原行；不是事实 Rank。 |
| company_name | VARCHAR(255) | NOT NULL | 确认公司归一、worked_at 目标核对；原文仅 SQL 展示。 |
| start_date | DATETIME | 可 NULL | 写 worked_at.start_month；原完整日期留 SQL 证据。 |
| end_date | DATETIME | 可 NULL | 写 worked_at.end_month；原完整日期留 SQL 证据。 |
| position_title | VARCHAR(255) | NOT NULL | 写 worked_at.position_title；原文可回 SQL，不造标准 role_id。 |
| work_description | TEXT | 可 NULL | 工作长文本仅 SQL 按需详情，不入图。 |
| create_by | BIGINT | 可 NULL | 原经历管理字段留 SQL，本版不投影或默认查询。 |
| update_by | BIGINT | 可 NULL | 原经历管理字段留 SQL，本版不投影或默认查询。 |
| created_at | DATETIME | 可 NULL | 原经历管理字段留 SQL，本版不投影或默认查询。 |
| updated_at | DATETIME | 可 NULL | 仅 SQL 来源修改时间；用于接入核对，不写图属性。 |
| deleted_at | DATETIME | 可 NULL | 构建经历有效性过滤，失效事实与派生人物边不进新图。 |
| expert_id | INT | 可 NULL | 核对原人物归属并生成事实 src VID；不存为普通属性。 |
| is_employed | INT | NOT NULL | 写 worked_at.is_current；1／2转换，其余阻断。 |

### experts_education_experience

| experts_education_experience 字段 | 源类型 | 源可空性 | 本版去向 |
| --- | --- | --- | --- |
| id | INT | NOT NULL | 派生 studied_at／studied_major.experience_key，回查原行；不是事实 Rank。 |
| expert_id | INT | 可 NULL | 核对原人物归属并生成事实 src VID；不存为普通属性。 |
| school_name | VARCHAR(255) | 可 NULL | 确认学校映射与 studied_at 目标；原文仅 SQL 展示。 |
| major | VARCHAR(255) | 可 NULL | 确认专业映射与 studied_major 目标；原文仅 SQL 展示。 |
| education_level | VARCHAR(255) | 可 NULL | 写两类教育边 education_level；同条行内容一致。 |
| is_regular_enrollment | VARCHAR(255) | 可 NULL | 写两类教育边同名 STRING 属性；不猜 BOOL。 |
| start_date | DATETIME | 可 NULL | 写 studied_at／studied_major.start_month；原完整日期留 SQL 证据。 |
| end_date | DATETIME | 可 NULL | 写 studied_at／studied_major.end_month；原完整日期留 SQL 证据。 |
| create_by | BIGINT | NOT NULL | 原经历管理字段留 SQL，本版不投影或默认查询。 |
| update_by | BIGINT | 可 NULL | 原经历管理字段留 SQL，本版不投影或默认查询。 |
| created_at | DATETIME | 可 NULL | 原经历管理字段留 SQL，本版不投影或默认查询。 |
| updated_at | DATETIME | 可 NULL | 仅 SQL 来源修改时间；用于接入核对，不写图属性。 |
| deleted_at | DATETIME | 可 NULL | 构建经历有效性过滤，失效事实与派生人物边不进新图。 |

### experts_project_experience

| experts_project_experience 字段 | 源类型 | 源可空性 | 本版去向 |
| --- | --- | --- | --- |
| id | INT | NOT NULL | 项目原业务留 SQL；本版不投影、不默认查询，不当任职事实。 |
| company_name | VARCHAR(255) | NOT NULL | 项目原业务留 SQL；本版不投影、不默认查询，不当任职事实。 |
| start_date | DATETIME | 可 NULL | 项目原业务留 SQL；本版不投影、不默认查询，不当任职事实。 |
| end_date | DATETIME | 可 NULL | 项目原业务留 SQL；本版不投影、不默认查询，不当任职事实。 |
| project_title | VARCHAR(255) | NOT NULL | 项目原业务留 SQL；本版不投影、不默认查询，不当任职事实。 |
| work_description | TEXT | 可 NULL | 项目原业务留 SQL；本版不投影、不默认查询，不当任职事实。 |
| create_by | BIGINT | 可 NULL | 项目原业务留 SQL；本版不投影、不默认查询，不当任职事实。 |
| update_by | BIGINT | 可 NULL | 项目原业务留 SQL；本版不投影、不默认查询，不当任职事实。 |
| created_at | DATETIME | 可 NULL | 项目原业务留 SQL；本版不投影、不默认查询，不当任职事实。 |
| updated_at | DATETIME | 可 NULL | 项目原业务留 SQL；本版不投影、不默认查询，不当任职事实。 |
| deleted_at | DATETIME | 可 NULL | 项目原业务留 SQL；本版不投影、不默认查询，不当任职事实。 |
| expert_id | INT | 可 NULL | 项目原业务留 SQL；本版不投影、不默认查询，不当任职事实。 |

### resume

| resume 字段 | 源类型 | 源可空性 | 本版去向 |
| --- | --- | --- | --- |
| id | INT | NOT NULL | 生成 person VID，回查身份；不重复存 source_id。 |
| serial_number | CHAR(19) | NOT NULL | 写 person.serial_number；详情可核对。 |
| name | VARCHAR(50) | NOT NULL | 仅 SQL 批量回查显示，禁止写图或姓名替代属性。 |
| interview_nickname | VARCHAR(50) | NOT NULL | 个人附属信息留 SQL，本版不默认展示或投影。 |
| company | VARCHAR(100) | NOT NULL | 仅 SQL 主表摘要；不是标准任职关系目标。 |
| job_status | TINYINT | NOT NULL | 仅 SQL 摘要状态，不替代每次工作 is_employed。 |
| job_name | VARCHAR(255) | NOT NULL | 仅 SQL 主表职位摘要，不替代工作行 position_title。 |
| contact_status | TINYINT | NOT NULL | 原业务字段保留 SQL，本版不投影、不默认查询或推导关系。 |
| doubtful_flag | TINYINT | NOT NULL | 原业务字段保留 SQL，本版不投影、不默认查询或推导关系。 |
| country | VARCHAR(50) | NOT NULL | 可选 SQL 地区详情，不入图。 |
| province | VARCHAR(50) | NOT NULL | 可选 SQL 地区详情，不入图。 |
| city | VARCHAR(50) | NOT NULL | 可选 SQL 地区详情，不入图。 |
| email | VARCHAR(64) | NOT NULL | 联系方式留 SQL，本版不默认查询、不入图；另行定义授权用途。 |
| country_code | VARCHAR(5) | NOT NULL | 联系方式留 SQL，本版不默认查询、不入图；另行定义授权用途。 |
| phone | VARCHAR(30) | NOT NULL | 原字段已弃用；本版不使用，不作为有效联系方式来源。 |
| abroad_flag | TINYINT | NOT NULL | 原业务字段保留 SQL，本版不投影、不默认查询或推导关系。 |
| other_contacts | VARCHAR(50) | NOT NULL | 联系方式留 SQL，本版不默认查询、不入图；另行定义授权用途。 |
| currency | CHAR(10) | NOT NULL | 原业务字段保留 SQL，本版不投影、不默认查询或推导关系。 |
| rate_value | DECIMAL(22,4) | NOT NULL | 原业务字段保留 SQL，本版不投影、不默认查询或推导关系。 |
| rate_type | TINYINT | 可 NULL | 原业务字段保留 SQL，本版不投影、不默认查询或推导关系。 |
| background | TEXT | NOT NULL | 可选 SQL 背景详情，不入图。 |
| comment | TEXT | 可 NULL | 原业务字段保留 SQL，本版不投影、不默认查询或推导关系。 |
| edu_experience | TEXT | 可 NULL | 旧教育 JSON 留 SQL，不默认替代结构化教育经历。 |
| personal_intro | TEXT | 可 NULL | 可选 SQL 个人简介，不入图。 |
| remark | TEXT | 可 NULL | 原业务字段保留 SQL，本版不投影、不默认查询或推导关系。 |
| certification_file | VARCHAR(500) | 可 NULL | 原业务字段保留 SQL，本版不投影、不默认查询或推导关系。 |
| source_type | TINYINT | NOT NULL | 仅 SQL 获客渠道，可选详情；不作 person.source_system。 |
| source_link | VARCHAR(255) | 可 NULL | 可选 SQL 来源链接，不入图。 |
| recommend_resume_id | INT | 可 NULL | 原推荐业务留 SQL，本版不生成推荐人物边。 |
| supplier_contract_id | INT | 可 NULL | 原业务字段保留 SQL，本版不投影、不默认查询或推导关系。 |
| collaborate_num | INT | NOT NULL | 原业务字段保留 SQL，本版不投影、不默认查询或推导关系。 |
| last_collaborate_time | INT | NOT NULL | 原业务字段保留 SQL，本版不投影、不默认查询或推导关系。 |
| create_by | BIGINT | 可 NULL | 原业务字段保留 SQL，本版不投影、不默认查询或推导关系。 |
| update_by | BIGINT | 可 NULL | 原业务字段保留 SQL，本版不投影、不默认查询或推导关系。 |
| created_at | DATETIME(3) | 可 NULL | 原业务字段保留 SQL，本版不投影、不默认查询或推导关系。 |
| updated_at | DATETIME(3) | 可 NULL | 仅 SQL 原行更新时间，不是图版本时间。 |
| deleted_at | DATETIME(3) | 可 NULL | 构建有效人物过滤；删除时间不写 person。 |
| age | INT | 可 NULL | 个人附属信息留 SQL，本版不默认展示或投影。 |
| education | VARCHAR(20) | NOT NULL | 可选 SQL 学历摘要，不替代教育行学历。 |
| work_years | INT | 可 NULL | 可选 SQL 工作年限，不自动计算补齐。 |
| gender | TINYINT(1) | NOT NULL | 个人附属信息留 SQL，本版不默认展示或投影。 |
| certifications | TEXT | 可 NULL | 原业务字段保留 SQL，本版不投影、不默认查询或推导关系。 |
| self_appraisal | TEXT | 可 NULL | 原业务字段保留 SQL，本版不投影、不默认查询或推导关系。 |
| content_version | BIGINT UNSIGNED | NOT NULL | 原合规内容版本留 SQL，不等于 projection_id／图版本。 |
| update_resume_time | VARCHAR(30) | NOT NULL | 原业务字段保留 SQL，本版不投影、不默认查询或推导关系。 |
| resume_id | INT | 可 NULL | 原业务关联留 SQL，不据此自行跨库统一人物。 |
| is_plugin | TINYINT | 可 NULL | 原业务字段保留 SQL，本版不投影、不默认查询或推导关系。 |

### resume_work_experience

| resume_work_experience 字段 | 源类型 | 源可空性 | 本版去向 |
| --- | --- | --- | --- |
| id | INT | NOT NULL | 派生 worked_at.experience_key，回查原行；不是事实 Rank。 |
| company_name | VARCHAR(255) | NOT NULL | 确认公司归一、worked_at 目标核对；原文仅 SQL 展示。 |
| start_date | DATETIME | 可 NULL | 写 worked_at.start_month；原完整日期留 SQL 证据。 |
| end_date | DATETIME | 可 NULL | 写 worked_at.end_month；原完整日期留 SQL 证据。 |
| position_title | VARCHAR(255) | NOT NULL | 写 worked_at.position_title；原文可回 SQL，不造标准 role_id。 |
| work_description | TEXT | 可 NULL | 工作长文本仅 SQL 按需详情，不入图。 |
| create_by | BIGINT | 可 NULL | 原经历管理字段留 SQL，本版不投影或默认查询。 |
| update_by | BIGINT | 可 NULL | 原经历管理字段留 SQL，本版不投影或默认查询。 |
| created_at | DATETIME | 可 NULL | 原经历管理字段留 SQL，本版不投影或默认查询。 |
| updated_at | DATETIME | 可 NULL | 仅 SQL 来源修改时间；用于接入核对，不写图属性。 |
| deleted_at | DATETIME | 可 NULL | 构建经历有效性过滤，失效事实与派生人物边不进新图。 |
| resume_id | INT | 可 NULL | 核对原人物归属并生成事实 src VID；不存为普通属性。 |
| is_employed | INT | NOT NULL | 写 worked_at.is_current；1／2转换，其余阻断。 |

### resume_education_experience

| resume_education_experience 字段 | 源类型 | 源可空性 | 本版去向 |
| --- | --- | --- | --- |
| id | INT | NOT NULL | 派生 studied_at／studied_major.experience_key，回查原行；不是事实 Rank。 |
| resume_id | INT | 可 NULL | 核对原人物归属并生成事实 src VID；不存为普通属性。 |
| school_name | VARCHAR(255) | 可 NULL | 确认学校映射与 studied_at 目标；原文仅 SQL 展示。 |
| major | VARCHAR(255) | 可 NULL | 确认专业映射与 studied_major 目标；原文仅 SQL 展示。 |
| education_level | VARCHAR(255) | 可 NULL | 写两类教育边 education_level；同条行内容一致。 |
| is_regular_enrollment | VARCHAR(255) | 可 NULL | 写两类教育边同名 STRING 属性；不猜 BOOL。 |
| start_date | DATETIME | 可 NULL | 写 studied_at／studied_major.start_month；原完整日期留 SQL 证据。 |
| end_date | DATETIME | 可 NULL | 写 studied_at／studied_major.end_month；原完整日期留 SQL 证据。 |
| create_by | BIGINT | NOT NULL | 原经历管理字段留 SQL，本版不投影或默认查询。 |
| update_by | BIGINT | 可 NULL | 原经历管理字段留 SQL，本版不投影或默认查询。 |
| created_at | DATETIME | 可 NULL | 原经历管理字段留 SQL，本版不投影或默认查询。 |
| updated_at | DATETIME | 可 NULL | 仅 SQL 来源修改时间；用于接入核对，不写图属性。 |
| deleted_at | DATETIME | 可 NULL | 构建经历有效性过滤，失效事实与派生人物边不进新图。 |

### resume_project_experience

| resume_project_experience 字段 | 源类型 | 源可空性 | 本版去向 |
| --- | --- | --- | --- |
| id | INT | NOT NULL | 项目原业务留 SQL；本版不投影、不默认查询，不当任职事实。 |
| company_name | VARCHAR(255) | NOT NULL | 项目原业务留 SQL；本版不投影、不默认查询，不当任职事实。 |
| start_date | DATETIME | 可 NULL | 项目原业务留 SQL；本版不投影、不默认查询，不当任职事实。 |
| end_date | DATETIME | 可 NULL | 项目原业务留 SQL；本版不投影、不默认查询，不当任职事实。 |
| project_title | VARCHAR(255) | NOT NULL | 项目原业务留 SQL；本版不投影、不默认查询，不当任职事实。 |
| work_description | TEXT | 可 NULL | 项目原业务留 SQL；本版不投影、不默认查询，不当任职事实。 |
| create_by | BIGINT | 可 NULL | 项目原业务留 SQL；本版不投影、不默认查询，不当任职事实。 |
| update_by | BIGINT | 可 NULL | 项目原业务留 SQL；本版不投影、不默认查询，不当任职事实。 |
| created_at | DATETIME | 可 NULL | 项目原业务留 SQL；本版不投影、不默认查询，不当任职事实。 |
| updated_at | DATETIME | 可 NULL | 项目原业务留 SQL；本版不投影、不默认查询，不当任职事实。 |
| deleted_at | DATETIME | 可 NULL | 项目原业务留 SQL；本版不投影、不默认查询，不当任职事实。 |
| resume_id | INT | 可 NULL | 项目原业务留 SQL；本版不投影、不默认查询，不当任职事实。 |

### graph_company_entity

| graph_company_entity 字段 | 源类型 | 源可空性 | 本版去向 |
| --- | --- | --- | --- |
| id | CHAR(36) | NOT NULL | 生成 company VID=e:<UUID>；核对事实 dst 与共同实体。 |
| company_code | VARCHAR(64) | NOT NULL | 写 company.company_code；业务编号不代替 UUID。 |
| standard_name | VARCHAR(255) | NOT NULL | 写 company.name，SQL 详情可核对；不按名称合并。 |
| former_names | JSON | 可 NULL | 仅 SQL 历史名称／别名查询与详情，不入本版节点。 |
| verification_status | VARCHAR(64) | NOT NULL | 发布放行校验，枚举待确认；可选 SQL 核验详情。 |
| child_company_codes | JSON | 可 NULL | 来源层级信息保留，不投影层级边、不扩大同公司；0不区分无关系与未知。 |
| parent_company_codes | JSON | 可 NULL | 来源层级信息保留，不投影层级边、不扩大同公司；0不区分无关系与未知。 |
| source_created_at | DATETIME(6) | NOT NULL | 来源管理／追溯信息留 SQL，不直接写图属性。 |
| source_updated_at | DATETIME(6) | NOT NULL | 仅 SQL 来源更新时间与冻结一致性核对，不单独写节点。 |
| sync_batch_id | BIGINT UNSIGNED | NOT NULL | 来源最近批次核对，不等于整图 projection_id。 |
| synced_at | DATETIME(6) | NOT NULL | 来源管理／追溯信息留 SQL，不直接写图属性。 |
| is_deleted | TINYINT UNSIGNED | NOT NULL | 构建目标有效性过滤；删除实体事实及派生关系不进新图。 |
| deleted_at | DATETIME(6) | 可 NULL | 来源失效追溯及矛盾核对，不写图属性。 |

### graph_school_entity

| graph_school_entity 字段 | 源类型 | 源可空性 | 本版去向 |
| --- | --- | --- | --- |
| id | CHAR(36) | NOT NULL | 生成 school VID=e:<UUID>；核对事实 dst 与共同实体。 |
| school_code | VARCHAR(64) | NOT NULL | 写 school.school_code；业务编号不代替 UUID。 |
| standard_name | VARCHAR(255) | NOT NULL | 写 school.name，SQL 详情可核对；不按名称合并。 |
| former_names | JSON | 可 NULL | 仅 SQL 历史名称／别名查询与详情，不入本版节点。 |
| official_code | VARCHAR(64) | 可 NULL | 可选 SQL 学校详情，不入图；官方代码不保证唯一。 |
| country_region | VARCHAR(128) | 可 NULL | 可选 SQL 学校详情，不入图；官方代码不保证唯一。 |
| city | VARCHAR(128) | 可 NULL | 可选 SQL 学校详情，不入图；官方代码不保证唯一。 |
| verification_status | VARCHAR(64) | NOT NULL | 发布放行校验，枚举待确认；可选 SQL 核验详情。 |
| source_created_at | DATETIME(6) | NOT NULL | 来源管理／追溯信息留 SQL，不直接写图属性。 |
| source_updated_at | DATETIME(6) | NOT NULL | 仅 SQL 来源更新时间与冻结一致性核对，不单独写节点。 |
| sync_batch_id | BIGINT UNSIGNED | NOT NULL | 来源最近批次核对，不等于整图 projection_id。 |
| synced_at | DATETIME(6) | NOT NULL | 来源管理／追溯信息留 SQL，不直接写图属性。 |
| is_deleted | TINYINT UNSIGNED | NOT NULL | 构建目标有效性过滤；删除实体事实及派生关系不进新图。 |
| deleted_at | DATETIME(6) | 可 NULL | 来源失效追溯及矛盾核对，不写图属性。 |

### graph_major_entity

| graph_major_entity 字段 | 源类型 | 源可空性 | 本版去向 |
| --- | --- | --- | --- |
| id | CHAR(36) | NOT NULL | 生成 major VID=e:<UUID>；核对事实 dst 与共同实体。 |
| major_code | VARCHAR(64) | NOT NULL | 写 major.major_code；业务编号不代替 UUID。 |
| standard_name | VARCHAR(255) | NOT NULL | 写 major.name，SQL 详情可核对；不按名称合并。 |
| verification_status | VARCHAR(64) | NOT NULL | 发布放行校验，枚举待确认；可选 SQL 核验详情。 |
| source_created_at | DATETIME(6) | NOT NULL | 来源管理／追溯信息留 SQL，不直接写图属性。 |
| source_updated_at | DATETIME(6) | NOT NULL | 仅 SQL 来源更新时间与冻结一致性核对，不单独写节点。 |
| sync_batch_id | BIGINT UNSIGNED | NOT NULL | 来源最近批次核对，不等于整图 projection_id。 |
| synced_at | DATETIME(6) | NOT NULL | 来源管理／追溯信息留 SQL，不直接写图属性。 |
| is_deleted | TINYINT UNSIGNED | NOT NULL | 构建目标有效性过滤；删除实体事实及派生关系不进新图。 |
| deleted_at | DATETIME(6) | 可 NULL | 来源失效追溯及矛盾核对，不写图属性。 |

### graph_name_mapping

| graph_name_mapping 字段 | 源类型 | 源可空性 | 本版去向 |
| --- | --- | --- | --- |
| id | CHAR(36) | NOT NULL | 归一记录追溯 UUID，留在发布追溯；不作事实 Rank。 |
| entity_type | VARCHAR(16) | NOT NULL | 选择 company／school／major 目标类别，构建核对。 |
| source_namespace | VARCHAR(128) | NOT NULL | 与 source_field_id 定位来源系统、表与字段，须明确契约。 |
| source_field_id | VARCHAR(128) | NOT NULL | 字符串原经历定位；无损回连原表 id，不当人物键。 |
| company_id | CHAR(36) | 可 NULL | 确认 worked_at 的标准公司目标 UUID。 |
| school_id | CHAR(36) | 可 NULL | 确认 studied_at 的标准学校目标 UUID。 |
| major_id | CHAR(36) | 可 NULL | 确认 studied_major 的标准专业目标 UUID。 |
| processing_status | VARCHAR(64) | NOT NULL | 仅已匹配并在确认发布范围的映射可消费。 |
| source_updated_at | DATETIME(6) | NOT NULL | 来源变更与原经历冻结关联校验，不直接入图。 |
| sync_batch_id | BIGINT UNSIGNED | NOT NULL | 来源批次线索，不单独代表完整发布。 |
| synced_at | DATETIME(6) | NOT NULL | 来源同步追溯，不是图构建完成时间。 |
| is_deleted | TINYINT UNSIGNED | NOT NULL | 必须为0才有效；1时不生成事实及其人物关系。 |

### graph_edge_mapping

| graph_edge_mapping 字段 | 源类型 | 源可空性 | 本版去向 |
| --- | --- | --- | --- |
| id | BIGINT | 原文未列 | 事实 Rank；人物边左右事实 Rank 回查此列，不是人物边自身序号。 |
| source_system | VARCHAR(16) | 原文未列 | 核对人物来源，参与事实 src 与 experience_key。 |
| source_table | VARCHAR(64) | 原文未列 | 白名单定位原经历表，参与 experience_key 和类型校验。 |
| source_field_id | BIGINT | 原文未列 | 定位原经历 id，参与 experience_key；不是 source_person_id。 |
| source_field | VARCHAR(64) | 原文未列 | company_name／school_name／major 槽位及目标类别校验。 |
| source_person_id | BIGINT | 原文未列 | 核对原行人物归属并生成事实 src VID。 |
| standard_entity_id | CHAR(36) | 原文未列 | 确认 CHAR(36) UUID，生成事实 dst VID。 |
| edge_type | VARCHAR(64) | 原文未列 | 生成三类事实边类型，不直接写人物关系类型。 |
| created_at | DATETIME(6) | 原文未列 | 槽位管理／追溯留 SQL，不作任职或教育开始时间。 |
| updated_at | DATETIME(6) | 原文未列 | 槽位变更追溯，不作任职结束或图基准月。 |
| deleted_at | DATETIME(6) | 原文未列 | 事实槽位有效性过滤；失效证据及派生人物边不进新版本。 |

### graph_company_relation

| graph_company_relation 字段 | 源类型 | 源可空性 | 本版去向 |
| --- | --- | --- | --- |
| id | CHAR(36) | NOT NULL | 公司层级来源留 SQL，本版不投影或默认查询；不得扩展同公司。 |
| parent_company_id | CHAR(36) | NOT NULL | 公司层级来源留 SQL，本版不投影或默认查询；不得扩展同公司。 |
| child_company_id | CHAR(36) | NOT NULL | 公司层级来源留 SQL，本版不投影或默认查询；不得扩展同公司。 |
| relation_type | VARCHAR(32) | NOT NULL | 公司层级来源留 SQL，本版不投影或默认查询；不得扩展同公司。 |
| verification_status | VARCHAR(64) | NOT NULL | 公司层级来源留 SQL，本版不投影或默认查询；不得扩展同公司。 |
| source_created_at | DATETIME(6) | NOT NULL | 公司层级来源留 SQL，本版不投影或默认查询；不得扩展同公司。 |
| source_updated_at | DATETIME(6) | NOT NULL | 公司层级来源留 SQL，本版不投影或默认查询；不得扩展同公司。 |
| sync_batch_id | BIGINT UNSIGNED | NOT NULL | 公司层级来源留 SQL，本版不投影或默认查询；不得扩展同公司。 |
| synced_at | DATETIME(6) | NOT NULL | 公司层级来源留 SQL，本版不投影或默认查询；不得扩展同公司。 |
| is_deleted | TINYINT UNSIGNED | NOT NULL | 公司层级来源留 SQL，本版不投影或默认查询；不得扩展同公司。 |
| deleted_at | DATETIME(6) | 可 NULL | 公司层级来源留 SQL，本版不投影或默认查询；不得扩展同公司。 |

### graph_sync_batch

| graph_sync_batch 字段 | 源类型 | 源可空性 | 本版去向 |
| --- | --- | --- | --- |
| id | BIGINT UNSIGNED | NOT NULL | 来源批次／冻结与完成线索留 SQL；不直接复制为控制节点或据此自动ready。 |
| source_project_id | VARCHAR(64) | NOT NULL | 来源批次／冻结与完成线索留 SQL；不直接复制为控制节点或据此自动ready。 |
| sync_mode | VARCHAR(16) | NOT NULL | 来源批次／冻结与完成线索留 SQL；不直接复制为控制节点或据此自动ready。 |
| status | VARCHAR(16) | NOT NULL | 来源批次／冻结与完成线索留 SQL；不直接复制为控制节点或据此自动ready。 |
| started_at | DATETIME(6) | NOT NULL | 来源批次／冻结与完成线索留 SQL；不直接复制为控制节点或据此自动ready。 |
| snapshot_at | DATETIME(6) | 可 NULL | 来源批次／冻结与完成线索留 SQL；不直接复制为控制节点或据此自动ready。 |
| finished_at | DATETIME(6) | 可 NULL | 来源批次／冻结与完成线索留 SQL；不直接复制为控制节点或据此自动ready。 |
| expected_counts | JSON | 可 NULL | 来源批次／冻结与完成线索留 SQL；不直接复制为控制节点或据此自动ready。 |
| actual_counts | JSON | 可 NULL | 来源批次／冻结与完成线索留 SQL；不直接复制为控制节点或据此自动ready。 |
| error_message | TEXT | 可 NULL | 来源批次／冻结与完成线索留 SQL；不直接复制为控制节点或据此自动ready。 |

## 15 待确认事项与核对记录

仍需确认：正式来源命名空间、UUID 与事实槽位生命周期、一字段多目标拆分、原文与归一冻结对应、核验／批次完成枚举、删除通知与恢复、SQL NULL 层级含义及成对历史保留。已确认的简历结构、standard_entity_id CHAR(36) 和名称映射 is_deleted 不重复列为缺项。

本次以当前 DDL 独立逐字段核对 12 个图对象的 42 个属性及图键，反向覆盖 15 张源表的 251 列；Word 与 Markdown 同源。原始核对文件、DDL 及新清单摘要保存于 docs/data-sources/mysql-graph-mapping-v5-verification.json。此次没有数据库、服务或应用代码改动。

维护入口：[主架构](query-system-architecture.md)、[图 DDL](graph-ddl.md)、[姓名隐私边界](graph-privacy.md)、[数据交接](data-handoff.md)、[待确认问题](stable-identifiers-and-publishing-questions.md)。当前模型历史图验证见 [业务字段验证](graph-business-fields-validation.md)，不是本轮真实源或生产验证。

修订：v5.0，2026-11-06，按 uuid-relations-v5 重写图优先映射，新增只回查展示清单、双 Rank／组键说明，并更新逐列附录。旧 v3.3 文档已归档，不再作为当前图模型依据。
