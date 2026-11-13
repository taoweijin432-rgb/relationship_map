> 历史 v3.2；用户随后确认补回 is_deleted，当前见 ../mysql-to-graph-fields.md。

# 人物关系图谱图字段与 MySQL 来源规范

文档版本 v3.2 ｜核对日期 2026-11-06 ｜设计基线 v0.16.3 ｜运行代码仍为 v0.16

本文以用户最新提供的《人物关系图谱MySQL表结构设计说明_映射表精简版(3).docx》为唯一最新表设计依据，重新说明每种图节点和边的字段用途、MySQL 来源及空值规则。旧《图数据库投影三表设计与独立词典维护方案》已废弃，不再要求独立实体词典、独立别名表或本项目自行匹配建词。精简版(1)与(2)均由本版替换，不再作为当前依据。

最新文件明确三类 UUID 标准实体和三类经历边，并已将 standard_entity_id 定为 CHAR(36)。用户确认简历原表 DDL 与专家一致，只将 expert 对应改为 resume；该规则不再列为待确认。映射字段数量、删除与上下级状态仍有说明差异，继续单列。本文逐项标明原文、建议修订和待确认内容，不能作为已经无歧义的正式 DDL 或已完成迁移的证明。全文仅做本地文档核对，没有访问数据库、修改云端或切换现有服务。

## 1 新基线与适用范围

| 事项 | 本次采用的口径 | 状态 |
| --- | --- | --- |
| 标准实体来源 | graph_company_entity、graph_school_entity、graph_major_entity；主键为 CHAR(36) UUID | 新文件明确 |
| 来源名称映射 | graph_name_mapping；字段表实际为 11 列，未列 is_deleted | 表名已统一；文字仍称 12 列并引用删除标志，须确认最终结构 |
| 边投影来源 | graph_edge_mapping；保留 BIGINT id 作为 Rank | 新文件明确；目标列 CHAR(36) 已获用户确认，数据库迁移尚未执行 |
| 人物与时间 | 专家原表按已提供 DDL；简历原表沿用同一结构，expert 对应改为 resume | 2026-11-06 用户确认；人物统一结果与真实数据另行交付 |
| 图节点 | person 人物；entity 标签按 organization、school、major 区分 | 标签格式沿用原型的建议，不是新 Word 中的完整图 DDL |
| 图边 | worked_at、studied_at、studied_major | 新文件明确；不纳入 held_role、participated_in、collaborated with |
| 图与 SQL 分工 | 图计算关系、同期和有界路径；SQL 回查原人物与经历证据 | 保留用户已确认方向；不采用旧式图只召回、SQL 重算路径 |
| 现有实现 | source-slots-v2 仍使用旧三表与数字实体键 | 属于历史模拟验证；本次未迁移，不宣称新结构已通过运行验收 |

图字段表中的“建议”表示为复用查询规则而提出的目标投影格式；“待确认”表示文件尚不能给出唯一映射。源表名、字段名与空值直接从新文件核对；无法核对的列不从废弃方案补入。附录反查 15 张已知表的 250 个字段，其中 8 张原表共 170 列、最新 7 张来源／投影表共 80 列。

## 2 已确认修订与剩余文档问题

| 问题 | 文件中的原文或现象 | 本文处理与建议 |
| --- | --- | --- |
| 目标 ID 类型已落实到文档 | graph_edge_mapping.standard_entity_id 与三张标准表 id 均为 CHAR(36) | 与上一轮用户确认一致；字符集／排序与目标保持一致，边 id／Rank 继续 BIGINT。原型数据库尚未迁移 |
| 名称映射字段与删除冲突 | 字段表实际 11 列；文字称十二列，并引用 source_record_id、item_no、raw_name、is_deleted | 按字段表列出 11 列，不补回旧列。is_deleted 是否漏列或改用其他失效方式必须确认；同步更新索引，不能继续执行不存在的列过滤 |
| 标准实体表引用残留 | 章节正文改为 graph_company_entity／graph_school_entity／graph_major_entity；总览、公司关系和代码说明仍引用旧名 | 本文以章节正文和名称映射的目标引用为准；旧短表名不当作并行存在的表，DDL 与引用须统一 |
| 来源表拼写 | experts/resume_work_expertience；graph_conpany/school/major_entity；实体节点读取说明仍有旧短表名 | 按真实 DDL 使用 *_work_experience；标准表采用 *_entity。斜杠是备选说明，不是表名；graph_conpany 为拼写问题 |
| 上下级状态合并 | 最新正文将确认无关系和尚未确认均表示为 JSON 数字 0；字段描述还允许 SQL NULL | 0 只表示未提供明确关系，不能推断确认无关系。SQL NULL 含义待确认；不再沿用上一版三态区分 |
| 项目表范围残留 | source_table 描述仍提三类经历表，但 source_field 和末尾边表仅列 company_name、school_name、major | 本基线只投影工作公司、教育学校和专业。项目经历不因有 company_name 就自动变任职事实，待明确后再扩展 |
| 发布状态缺列 | 边表描述称保存发布状态，11 列中只有创建、更新、删除时间 | 不虚构 published、ready 或版本列；继续单独清单管理投影版本；生产发布契约待确认 |

standard_entity_id 是多类型目标引用。一个普通外键不能按行选择三张不同的目标表，需按 source_table、source_field 和 edge_type 共同确定目标类别，再校验对应 UUID 存在；正式 DDL 或应用约束的实现方式仍待确认。

graph_sync_batch.status 的具体完成枚举、verification_status 的可发布取值尚未列明，不能猜测“成功”或“已核验”字符串。sync_batch_id 表示最近同步批次，不天然意味着各表所有行必须拥有同一个批次号；完整快照仍需单独声明覆盖范围与数据截止点。

## 3 图键和关联链

简历 DDL 对应规则已由用户确认：当前命名为 resume、resume_work_experience、resume_project_experience、resume_education_experience；归属 expert_id 对应 resume_id，recommend_expert_id 对应 recommend_resume_id，其余字段类型、空值和默认规则沿用已提供专家 DDL。此确认只说明结构，不证明跨库人物已经统一或源数据已经可用。

建议保留人物 VID=p:expert:<原人物主键> 或 p:resume:<原人物主键>。按新文件，实体 VID=e:<标准实体 UUID>；例如 e:11111111-1111-4111-8111-111111111111。实体 id 属性由旧 INT 改为 STRING，保存同一个 UUID，不再建设 UUID 到 BIGINT 的词典桥接。人物主键与边 Rank 的 BIGINT 不受此变更影响。

沿用 FIXED_STRING(128) 可容纳这些 VID，构建前核验 UTF-8 字节长度，超长拒绝。e:<UUID> 依赖三张实体表之间不出现相同 UUID 的异类实体；应做跨表冲突预检，不能让一个节点同时成为公司和学校。若来源无法保证，另行确认带类型命名空间的 VID，不在本次暗改文件约定。

| 步骤 | 读取与连接 | 必须核对的内容 |
| --- | --- | --- |
| 原经历定位 | 归一映射 source_namespace＋source_field_id → 原经历表.id | 命名空间需显式指向来源系统、表和含义；不能仅凭 id 或 expert 字样猜测，字符串经历 ID 须无损对应原主键 |
| 人物归属 | 原工作／教育行 expert_id 或 resume_id → experts／resume.id | 人物有效；graph_edge_mapping.source_person_id 与原归属一致；source_field_id 不是人物 ID |
| 标准目标 | entity_type 选择 company_id、school_id 或 major_id → 对应标准表.id | 映射须为已匹配且属于明确发布范围；没有可用映射删除列，不能假装按 is_deleted 过滤。正确类型恰有一个目标，实体存在且未删除 |
| 边槽位 | graph_edge_mapping 的来源系统、表、行、字段 → 同一条确认结果 | standard_entity_id 与上一步 UUID 一致；Rank 使用独立槽位 id；名称不决定实体身份 |
| 图事实 | 起点人物 → 标准实体 UUID；日期从同一原经历读取 | 完整边键为起点、终点、类型、Rank；目标或人物变化须清理旧完整键 |

graph_name_mapping 字段表本版没有 is_deleted：预检和发布必须报告删除契约缺口，不能以虚构的列过滤，也不能静默默认所有映射永远有效。完整快照差分需上游声明覆盖完整；生产增量删除方式另行确认。

新归一映射已没有 raw_name。可以回查“当前原文”，但不能再证明它等于当初归一时的原文。需要冻结的原经历快照或双方认可的版本／更新时间关联；不以 former_names 包含某个文本就自行认定映射正确。多条同目标映射保留追溯后可以归并，一条来源字段出现多个不同目标时必须阻断或取得明确拆分结果；不取第一条，也不将同一日期和职位复制给所有目标。

## 4 人物节点 person

建议格式沿用 person(id STRING, name STRING, active BOOL)。专家和简历同数字 ID 仍为两个来源节点；上游未提供人物统一结果时，本项目不按姓名或 experts.resume_id 自行合并。

| 图字段及类型 | 用途 | MySQL 来源表 | MySQL 来源字段 | 转换与空值规则 |
| --- | --- | --- | --- | --- |
| VID 图键 | 唯一人物节点 | experts 或 resume | id；来源主表确定 expert／resume | 必须存在有效人物行，生成带来源前缀的 VID；NULL 主键或归属悬空阻断 |
| person.id STRING | 图内人物引用 | experts 或 resume | id；来源同上 | 写完整 VID；非空，不是单独的数字主键 |
| person.name STRING | 人物姓名展示 | experts 或 resume | name | 原 DDL 为 NOT NULL；建议拒绝空白显示名或交付前明确脱敏名，不据姓名合并 |
| person.active BOOL | 投影有效标志 | experts 或 resume | deleted_at | 原人物未删除才投影 true；失效人物不投影成 false；新快照移除旧节点及边 |

虚构样例：VID=p:expert:101；person={id:"p:expert:101", name:"示例人物甲", active:true}。city、job_name 仍可用于 SQL 列表摘要；邮箱、手机号、费率、评价等不因此入图。source_type 是获客渠道，不是 expert／resume。

## 5 公司节点 organization

建议格式：VID=e:<graph_company_entity.id>；标签 entity(id STRING, kind STRING, name STRING)；本类 kind="organization"。不从已废弃的 entity_type／canonical_name 词典列取值。

| 图字段及类型 | 用途 | MySQL 来源表 | MySQL 来源字段 | 转换与空值规则 |
| --- | --- | --- | --- | --- |
| VID 图键 | organization 节点身份 | graph_company_entity | id | 必须是非空有效 UUID；生成 e:<UUID>，不得按 standard_name 编号或合并；三表交叉 UUID 冲突须拒绝 |
| entity.id STRING | 保留标准实体主键 | graph_company_entity | id | 保存 UUID 字符串；由旧图 INT 改为 STRING；不写 BIGINT 或业务 code；本版已删除 entity_key |
| entity.kind STRING | 图区分类别 | graph_company_entity | 由所读表名派生，无同名列 | 固定为 organization；graph_name_mapping.entity_type=company 用于核对；非空 |
| entity.name STRING | 标准名称展示 | graph_company_entity | standard_name | 源列 NOT NULL 但名称不唯一；建议拒绝空白；允许改名，保留 UUID，不被原经历文本覆盖 |

虚构样例：VID=e:11111111-1111-4111-8111-111111111111；entity={id:"11111111-1111-4111-8111-111111111111", kind:"organization", name:"示例科技有限公司"}。过滤依据为 graph_company_entity.is_deleted=0，删除时间保留追溯；建议对 is_deleted 与 deleted_at 的矛盾记录报错，不擅自恢复。verification_status 需按正式放行值判断，不能以非空代表通过。

former_names 用于 MySQL 搜索／追溯，不再生成独立别名表。company_code 可保留来源定位，但不替代 UUID；本版已删除 entity_key。上下级 JSON 数字 0 同时覆盖确认无关系和未知，不可据此认定无关系。上下级数组和 graph_company_relation 不自动合并公司，不扩大同公司关系。

## 6 学校节点 school

建议格式：VID=e:<graph_school_entity.id>；标签 entity(id STRING, kind STRING, name STRING)；本类 kind="school"。不从已废弃的 entity_type／canonical_name 词典列取值。

| 图字段及类型 | 用途 | MySQL 来源表 | MySQL 来源字段 | 转换与空值规则 |
| --- | --- | --- | --- | --- |
| VID 图键 | school 节点身份 | graph_school_entity | id | 必须是非空有效 UUID；生成 e:<UUID>，不得按 standard_name 编号或合并；三表交叉 UUID 冲突须拒绝 |
| entity.id STRING | 保留标准实体主键 | graph_school_entity | id | 保存 UUID 字符串；由旧图 INT 改为 STRING；不写 BIGINT 或业务 code；本版已删除 entity_key |
| entity.kind STRING | 图区分类别 | graph_school_entity | 由所读表名派生，无同名列 | 固定为 school；graph_name_mapping.entity_type=school 用于核对；非空 |
| entity.name STRING | 标准名称展示 | graph_school_entity | standard_name | 源列 NOT NULL 但名称不唯一；建议拒绝空白；允许改名，保留 UUID，不被原经历文本覆盖 |

虚构样例：VID=e:22222222-2222-4222-8222-222222222222；entity={id:"22222222-2222-4222-8222-222222222222", kind:"school", name:"示例大学"}。过滤依据为 graph_school_entity.is_deleted=0，删除时间保留追溯；建议对 is_deleted 与 deleted_at 的矛盾记录报错，不擅自恢复。verification_status 需按正式放行值判断，不能以非空代表通过。

former_names、official_code、country_region、city 留在 MySQL 搜索／消歧展示，当前不增加图属性。official_code 在新设计中不唯一。学校和专业来自同一教育行也不表示可按拆分序号自动配对。

## 7 专业节点 major

建议格式：VID=e:<graph_major_entity.id>；标签 entity(id STRING, kind STRING, name STRING)；本类 kind="major"。不从已废弃的 entity_type／canonical_name 词典列取值。

| 图字段及类型 | 用途 | MySQL 来源表 | MySQL 来源字段 | 转换与空值规则 |
| --- | --- | --- | --- | --- |
| VID 图键 | major 节点身份 | graph_major_entity | id | 必须是非空有效 UUID；生成 e:<UUID>，不得按 standard_name 编号或合并；三表交叉 UUID 冲突须拒绝 |
| entity.id STRING | 保留标准实体主键 | graph_major_entity | id | 保存 UUID 字符串；由旧图 INT 改为 STRING；不写 BIGINT 或业务 code；本版已删除 entity_key |
| entity.kind STRING | 图区分类别 | graph_major_entity | 由所读表名派生，无同名列 | 固定为 major；graph_name_mapping.entity_type=major 用于核对；非空 |
| entity.name STRING | 标准名称展示 | graph_major_entity | standard_name | 源列 NOT NULL 但名称不唯一；建议拒绝空白；允许改名，保留 UUID，不被原经历文本覆盖 |

虚构样例：VID=e:33333333-3333-4333-8333-333333333333；entity={id:"33333333-3333-4333-8333-333333333333", kind:"major", name:"计算机科学"}。过滤依据为 graph_major_entity.is_deleted=0，删除时间保留追溯；建议对 is_deleted 与 deleted_at 的矛盾记录报错，不擅自恢复。verification_status 需按正式放行值判断，不能以非空代表通过。

专业有独立标准实体，不代替职位或学历等级。新设计没有专业 former_names 列，不能套用学校或公司别名结构。studied_major 可以投影，但当前运行中的人际关系／路径没有因此新增“同专业”能力。

## 8 任职边 worked_at

格式：person → entity(kind=organization)，边类型 worked_at，Rank=graph_edge_mapping.id。原表为 experts_work_experience 或 resume_work_experience；source_field=company_name。边类型、字段、原表类别、实体类型必须作为同一组验证，不能仅凭一个实体 UUID 生成未经原经历确认的事实。

本边表示一条原工作经历；共同公司与同期基于此边。职位保留在这条工作行的 position_title 中供 SQL 展示，不生成标准职位节点、held_role 或旧 role_id。新基线不承诺原有标准职位筛选可直接沿用。

| 图字段及类型 | 用途 | MySQL 来源表 | MySQL 来源字段 | 转换与空值规则 |
| --- | --- | --- | --- | --- |
| 起点 VID 图键 | 人物归属 | graph_edge_mapping；experts_work_experience 或 resume_work_experience；experts 或 resume | source_system、source_person_id；expert_id／resume_id；主表 id | 均须有效且归属一致；生成 p:expert:<id> 或 p:resume:<id>；缺人物或所有者矛盾阻断 |
| 终点 VID 图键 | 确认后的标准目标 | graph_edge_mapping；graph_name_mapping；graph_company_entity | standard_entity_id；company_id；id | 最新文件已将 standard_entity_id 定为 CHAR(36)，与 company_id 和 graph_company_entity.id 一致；生成 e:<UUID>。运行库尚未迁移，不以名称或 BIGINT 桥接替代 |
| 边类型 图键 | 本字段语义 | graph_edge_mapping | edge_type、source_table、source_field | 必须为 worked_at，并匹配 work_experience.company_name；非空 |
| Rank INT 图键 | 稳定边槽位编号 | graph_edge_mapping | id | 正有符号 BIGINT，1 至 2^63−1；不是实体 UUID、映射 UUID或原经历 ID。分配及重用规则仍需明确 |

### 完整边属性及来源

| worked_at 属性及类型 | 用途 | MySQL 来源表 | MySQL 来源字段 | 转换与空值规则 |
| --- | --- | --- | --- | --- |
| fact_id STRING | 回查边槽位与证据 | graph_edge_mapping | id | 建议沿用 slot:<id>；非空，与 Rank 一致，如 slot:7001 |
| kind STRING | 经历类别 | graph_edge_mapping | source_table | 由合法表名派生，本边固定 employment；非空 |
| active BOOL | 有效事实标记 | graph_edge_mapping；experts_work_experience 或 resume_work_experience；原人物表；graph_company_entity；graph_name_mapping | deleted_at；deleted_at；deleted_at；is_deleted；processing_status | 建议只有原人物／经历／槽位有效、目标未删除，且归一已匹配并纳入确认发布范围才写 true。映射无删除列，失效契约未确定前不能据它做生产增量清边 |
| start_date INT | 经历开始月份 | experts_work_experience 或 resume_work_experience | start_date | DATETIME 转 YYYYMM；NULL 保持未知。沿用原型月份范围 190001 至 210012 作为建议，正式历史日期范围待确认 |
| end_date INT | 经历结束月份 | experts_work_experience 或 resume_work_experience | end_date | DATETIME 转 YYYYMM；允许 NULL，未知不补齐；两端已知且开始晚于结束时拒绝 |
| is_current BOOL | 当前任职解释 | experts_work_experience 或 resume_work_experience | is_employed | 工作：1→true、2→false；其他值拒绝；true 时 end_date 必须 NULL |
| source_system STRING | 来源系统 | graph_edge_mapping | source_system | 非空 expert／resume；与原表及人物前缀一致，不取原主表 source_type |
| source_record_id STRING | 含表名的来源引用 | graph_edge_mapping；experts_work_experience 或 resume_work_experience | source_table；原行 id | 建议保留此图属性，派生 <source_table>:<原经历 id>。这是图字段，不是要求恢复新归一表已删除的同名 SQL 列 |
| source_table STRING | 来源表定位 | graph_edge_mapping | source_table | 必须为 experts_work_experience 或 resume_work_experience；项目表不允许用作本边 |
| source_field_id INT | 原经历行定位 | graph_edge_mapping；experts_work_experience 或 resume_work_experience | source_field_id；id | 这里为原经历数值主键，与原行 id 相等；归一映射的同名列是 VARCHAR(128)，须校验无损关联，不得粗暴转换异常文本 |
| source_field STRING | 原始字段定位 | graph_edge_mapping；experts_work_experience 或 resume_work_experience | source_field；company_name | 固定 company_name；原字段应为有效名称。没有映射时不自行匹配或创建实体，不能借用其他经历 |

完整虚构样例：p:expert:101 → e:11111111-1111-4111-8111-111111111111，type=worked_at，rank=7001；属性 fact_id="slot:7001"、kind="employment"、active=true、start_date=202001、end_date=202212、is_current=false、source_system="expert"、source_record_id="experts_work_experience:9001"、source_table="experts_work_experience"、source_field_id=9001、source_field="company_name"。UUID 和编号均为说明样例。

本方案每类边建议保留 11 个属性，旧 role_id 已移除。一个人重复任职／就读保留独立经历；同一槽位重复归一记录不生成重复边。图事实引用可定位到 graph_edge_mapping，再按来源回查原文；归一映射 UUID 的精确追溯目前不在这 11 列边表中，需另存发布追溯文件，不能声称可由当前字段唯一反查。

## 9 就读边 studied_at

格式：person → entity(kind=school)，边类型 studied_at，Rank=graph_edge_mapping.id。原表为 experts_education_experience 或 resume_education_experience；source_field=school_name。边类型、字段、原表类别、实体类型必须作为同一组验证，不能仅凭一个实体 UUID 生成未经原经历确认的事实。

本边表示一条原教育经历中的学校；日期未知仍可形成同校事实，但不能据此推断同期就读、同班或实际认识。

| 图字段及类型 | 用途 | MySQL 来源表 | MySQL 来源字段 | 转换与空值规则 |
| --- | --- | --- | --- | --- |
| 起点 VID 图键 | 人物归属 | graph_edge_mapping；experts_education_experience 或 resume_education_experience；experts 或 resume | source_system、source_person_id；expert_id／resume_id；主表 id | 均须有效且归属一致；生成 p:expert:<id> 或 p:resume:<id>；缺人物或所有者矛盾阻断 |
| 终点 VID 图键 | 确认后的标准目标 | graph_edge_mapping；graph_name_mapping；graph_school_entity | standard_entity_id；school_id；id | 最新文件已将 standard_entity_id 定为 CHAR(36)，与 school_id 和 graph_school_entity.id 一致；生成 e:<UUID>。运行库尚未迁移，不以名称或 BIGINT 桥接替代 |
| 边类型 图键 | 本字段语义 | graph_edge_mapping | edge_type、source_table、source_field | 必须为 studied_at，并匹配 education_experience.school_name；非空 |
| Rank INT 图键 | 稳定边槽位编号 | graph_edge_mapping | id | 正有符号 BIGINT，1 至 2^63−1；不是实体 UUID、映射 UUID或原经历 ID。分配及重用规则仍需明确 |

### 完整边属性及来源

| studied_at 属性及类型 | 用途 | MySQL 来源表 | MySQL 来源字段 | 转换与空值规则 |
| --- | --- | --- | --- | --- |
| fact_id STRING | 回查边槽位与证据 | graph_edge_mapping | id | 建议沿用 slot:<id>；非空，与 Rank 一致，如 slot:7002 |
| kind STRING | 经历类别 | graph_edge_mapping | source_table | 由合法表名派生，本边固定 education；非空 |
| active BOOL | 有效事实标记 | graph_edge_mapping；experts_education_experience 或 resume_education_experience；原人物表；graph_school_entity；graph_name_mapping | deleted_at；deleted_at；deleted_at；is_deleted；processing_status | 建议只有原人物／经历／槽位有效、目标未删除，且归一已匹配并纳入确认发布范围才写 true。映射无删除列，失效契约未确定前不能据它做生产增量清边 |
| start_date INT | 经历开始月份 | experts_education_experience 或 resume_education_experience | start_date | DATETIME 转 YYYYMM；NULL 保持未知。沿用原型月份范围 190001 至 210012 作为建议，正式历史日期范围待确认 |
| end_date INT | 经历结束月份 | experts_education_experience 或 resume_education_experience | end_date | DATETIME 转 YYYYMM；允许 NULL，未知不补齐；两端已知且开始晚于结束时拒绝 |
| is_current BOOL | 当前任职解释 | experts_education_experience 或 resume_education_experience | 无对应列，由边类别派生 | 建议写 false；不表示在读与否，不从教育日期猜测 |
| source_system STRING | 来源系统 | graph_edge_mapping | source_system | 非空 expert／resume；与原表及人物前缀一致，不取原主表 source_type |
| source_record_id STRING | 含表名的来源引用 | graph_edge_mapping；experts_education_experience 或 resume_education_experience | source_table；原行 id | 建议保留此图属性，派生 <source_table>:<原经历 id>。这是图字段，不是要求恢复新归一表已删除的同名 SQL 列 |
| source_table STRING | 来源表定位 | graph_edge_mapping | source_table | 必须为 experts_education_experience 或 resume_education_experience；项目表不允许用作本边 |
| source_field_id INT | 原经历行定位 | graph_edge_mapping；experts_education_experience 或 resume_education_experience | source_field_id；id | 这里为原经历数值主键，与原行 id 相等；归一映射的同名列是 VARCHAR(128)，须校验无损关联，不得粗暴转换异常文本 |
| source_field STRING | 原始字段定位 | graph_edge_mapping；experts_education_experience 或 resume_education_experience | source_field；school_name | 固定 school_name；原字段应为有效名称。没有映射时不自行匹配或创建实体，不能借用其他经历 |

完整虚构样例：p:expert:101 → e:22222222-2222-4222-8222-222222222222，type=studied_at，rank=7002；属性 fact_id="slot:7002"、kind="education"、active=true、start_date=202001、end_date=202212、is_current=false、source_system="expert"、source_record_id="experts_education_experience:9001"、source_table="experts_education_experience"、source_field_id=9001、source_field="school_name"。UUID 和编号均为说明样例。

本方案每类边建议保留 11 个属性，旧 role_id 已移除。一个人重复任职／就读保留独立经历；同一槽位重复归一记录不生成重复边。图事实引用可定位到 graph_edge_mapping，再按来源回查原文；归一映射 UUID 的精确追溯目前不在这 11 列边表中，需另存发布追溯文件，不能声称可由当前字段唯一反查。

## 10 专业边 studied_major

格式：person → entity(kind=major)，边类型 studied_major，Rank=graph_edge_mapping.id。原表为 experts_education_experience 或 resume_education_experience；source_field=major。边类型、字段、原表类别、实体类型必须作为同一组验证，不能仅凭一个实体 UUID 生成未经原经历确认的事实。

本边表示原教育经历中的专业。不得拿个人主表 education 代替 major，也不自动增加“同专业认识”或“同专业路径”。

| 图字段及类型 | 用途 | MySQL 来源表 | MySQL 来源字段 | 转换与空值规则 |
| --- | --- | --- | --- | --- |
| 起点 VID 图键 | 人物归属 | graph_edge_mapping；experts_education_experience 或 resume_education_experience；experts 或 resume | source_system、source_person_id；expert_id／resume_id；主表 id | 均须有效且归属一致；生成 p:expert:<id> 或 p:resume:<id>；缺人物或所有者矛盾阻断 |
| 终点 VID 图键 | 确认后的标准目标 | graph_edge_mapping；graph_name_mapping；graph_major_entity | standard_entity_id；major_id；id | 最新文件已将 standard_entity_id 定为 CHAR(36)，与 major_id 和 graph_major_entity.id 一致；生成 e:<UUID>。运行库尚未迁移，不以名称或 BIGINT 桥接替代 |
| 边类型 图键 | 本字段语义 | graph_edge_mapping | edge_type、source_table、source_field | 必须为 studied_major，并匹配 education_experience.major；非空 |
| Rank INT 图键 | 稳定边槽位编号 | graph_edge_mapping | id | 正有符号 BIGINT，1 至 2^63−1；不是实体 UUID、映射 UUID或原经历 ID。分配及重用规则仍需明确 |

### 完整边属性及来源

| studied_major 属性及类型 | 用途 | MySQL 来源表 | MySQL 来源字段 | 转换与空值规则 |
| --- | --- | --- | --- | --- |
| fact_id STRING | 回查边槽位与证据 | graph_edge_mapping | id | 建议沿用 slot:<id>；非空，与 Rank 一致，如 slot:7003 |
| kind STRING | 经历类别 | graph_edge_mapping | source_table | 由合法表名派生，本边固定 education；非空 |
| active BOOL | 有效事实标记 | graph_edge_mapping；experts_education_experience 或 resume_education_experience；原人物表；graph_major_entity；graph_name_mapping | deleted_at；deleted_at；deleted_at；is_deleted；processing_status | 建议只有原人物／经历／槽位有效、目标未删除，且归一已匹配并纳入确认发布范围才写 true。映射无删除列，失效契约未确定前不能据它做生产增量清边 |
| start_date INT | 经历开始月份 | experts_education_experience 或 resume_education_experience | start_date | DATETIME 转 YYYYMM；NULL 保持未知。沿用原型月份范围 190001 至 210012 作为建议，正式历史日期范围待确认 |
| end_date INT | 经历结束月份 | experts_education_experience 或 resume_education_experience | end_date | DATETIME 转 YYYYMM；允许 NULL，未知不补齐；两端已知且开始晚于结束时拒绝 |
| is_current BOOL | 当前任职解释 | experts_education_experience 或 resume_education_experience | 无对应列，由边类别派生 | 建议写 false；不表示在读与否，不从教育日期猜测 |
| source_system STRING | 来源系统 | graph_edge_mapping | source_system | 非空 expert／resume；与原表及人物前缀一致，不取原主表 source_type |
| source_record_id STRING | 含表名的来源引用 | graph_edge_mapping；experts_education_experience 或 resume_education_experience | source_table；原行 id | 建议保留此图属性，派生 <source_table>:<原经历 id>。这是图字段，不是要求恢复新归一表已删除的同名 SQL 列 |
| source_table STRING | 来源表定位 | graph_edge_mapping | source_table | 必须为 experts_education_experience 或 resume_education_experience；项目表不允许用作本边 |
| source_field_id INT | 原经历行定位 | graph_edge_mapping；experts_education_experience 或 resume_education_experience | source_field_id；id | 这里为原经历数值主键，与原行 id 相等；归一映射的同名列是 VARCHAR(128)，须校验无损关联，不得粗暴转换异常文本 |
| source_field STRING | 原始字段定位 | graph_edge_mapping；experts_education_experience 或 resume_education_experience | source_field；major | 固定 major；原字段应为有效名称。没有映射时不自行匹配或创建实体，不能借用其他经历 |

完整虚构样例：p:expert:101 → e:33333333-3333-4333-8333-333333333333，type=studied_major，rank=7003；属性 fact_id="slot:7003"、kind="education"、active=true、start_date=202001、end_date=202212、is_current=false、source_system="expert"、source_record_id="experts_education_experience:9001"、source_table="experts_education_experience"、source_field_id=9001、source_field="major"。UUID 和编号均为说明样例。

本方案每类边建议保留 11 个属性，旧 role_id 已移除。一个人重复任职／就读保留独立经历；同一槽位重复归一记录不生成重复边。图事实引用可定位到 graph_edge_mapping，再按来源回查原文；归一映射 UUID 的精确追溯目前不在这 11 列边表中，需另存发布追溯文件，不能声称可由当前字段唯一反查。

## 11 控制节点与非入图信息

lab_projection 是当前程序的控制标签，不是最新 Word 要求的业务表。建议后续适配继续保留，用于识别构建状态和内容；它不需要增建同名 MySQL 表，也不把 graph_sync_batch.status 直接写成 ready。

| 图字段及类型 | 用途 | MySQL 来源表 | MySQL 来源字段 | 转换与空值规则 |
| --- | --- | --- | --- | --- |
| VID 图键 | 控制节点定位 | 无 | 程序常量 | 沿用 meta\|projection；每个独立图空间一个 |
| status STRING | 图批次状态 | 无 | 程序构建与验证流程生成 | 非空，当前程序为 building／ready；图 ready 与 API 清单发布是不同阶段，不能单靠 ready 证明查询已通过 |
| digest STRING | 匹配 SQL 与图快照 | 原人物／经历及新来源／边表的确定快照范围 | 程序对冻结输入生成摘要 | 非空；新模型应重新定义摘要输入与 manifest 版本，不能复用旧 11 表摘要或伪造同版本内容 |

正式发布还需要完整快照标识、基准月、覆盖表与来源、追溯、行数和图回读校验。这些内容建议继续写独立清单；graph_sync_batch.id 不是经历 Rank，业务来源 source_project_id 也不是“标准项目实体”。

公司上下级表暂不生成新业务图边：新文件没有定义其图边名称和查询规则。该表仍用于来源结构校验；不能将其直接改成任职边，也不能用母子公司关系把两个实体合成同公司。如需集团专题或层级展示，另行确定方向、类型和查询边界。

## 12 空值与待处理数据规则

| 情形 | 建议处理 | 能力边界 |
| --- | --- | --- |
| 日期为空 | 图月份保留 NULL；只有当前任职且结束为空时，查询使用明确基准月份 | 同公司可以成立；未知区间不能认定同期；不回写虚构结束月 |
| 姓名／标准名为空白 | 交付预检报错或采用已确认的展示处理 | NOT NULL 不等于非空白；不自动造名字 |
| 原名称为空 | 没有有效映射时不生成相应边；有效映射指向空字段时定位问题 | 不能自行补目标或从主表摘要替代原经历 |
| 归一未匹配／待确认／部分匹配 | 留在预检报告和未发布清单，不选第一条目标 | 不能把处理中缺映射当作确认删除；覆盖不足要显示数据范围 |
| 映射失效无明确列 | 标准实体用 is_deleted；原人物／经历和槽位用 deleted_at。归一映射只列 processing_status，缺独立删除标志 | 确认删除清单或权威完整快照后再清边；不能仅凭处理中缺行当作删除 |
| 同字段多个不同目标 | 阻断该投影批次，或采用双方确认的更细事实与稳定子项键 | 新字段表已无 item_no，不能按旧序号拆分或自动配对学校与专业 |
| 批次／状态为空 | 必需批次引用缺失时拒绝；允许空的 snapshot_at／finished_at 保持未知 | 完成枚举未定，不把空错误文本、数量相等或 finished_at 非空当作唯一完成证明 |

建议发布前检查 UUID 格式和三表全局冲突、来源命名空间、人物归属、目标类型、已匹配状态、日期、槽位唯一和完整图键。新边表未提供 NOT NULL／索引／唯一约束的完整 DDL；正文必需规则是构建要求，附录不会把它们伪称为原表已有约束。

## 13 与当前程序的差异和后续验证

| 受影响部分 | 需要调整的内容 | 本次状态 |
| --- | --- | --- |
| SQL 适配 | 去掉运行依赖的旧三表，读取 *_entity 标准表、11 列归一映射和 graph_edge_mapping；实体 ID 改为 UUID；补齐映射失效契约 | 仅记录设计；代码未改 |
| 图写入与读取 | entity.id 从 INT 改 STRING；e:<UUID> 端点；新模型只投影三类边；移除 role_id 依赖 | 需新空间和新清单，不能覆盖旧图或当作兼容旧 format_version=2 |
| 关系和路径 | 同公司／同期／同校继续在图内计算；SQL 仅按来源定位取证据；专业先不新增人际语义 | 规则方向保留；需独立期望对照 |
| 职位／项目功能 | 原职位文字留 SQL；原标准职位筛选、职位节点、项目边不再有本轮正式数据依据 | 后续适配需明确禁用／提示／缩小能力，不能用虚构旧词典补齐 |
| 别名搜索 | 公司／学校用 former_names；专业按 standard_name；原名称来自原经历 | 无独立 alias 表；不执行相似匹配、择优或自动建实体 |
| 修正与发布 | 继续新 SQL／图快照完整构建、回读、停服切换／回退；追溯绑定映射 UUID | 沿用流程原则，重新定义输入摘要和发布契约；未实施生产增量 |

建议验证顺序：目标类型已确认，先落实 CHAR(36) 定义、统一第 2 节剩余问题并交付命名空间样例；再用新字段表生成独立模拟库，预检原经历→映射→UUID 目标→边槽位；建立人工预期，验证重复经历、同名、失效、未知日期、跨年、同期、同校与一位中间人；核对新图与 SQL 证据；最后检查两个入口、来源详情和版本切换。不能因文档核对通过就宣称数据库建表、真实数据接入或生产容量通过。

## 附录索引 MySQL 每个字段的去向

附录 A 按已提供专家 DDL 及用户确认的简历对应规则 列出 8 表 170 列；附录 B 按更正文件的字段表逐项列出 7 表 80 列，共 15 表 250 列。已删除的旧列不补回；未入图的列也逐行说明用途。新边表的原文可空性未给出，统一标为“原文未列”，与正文的建议必需性分开。

最新 Word 不是完整 CREATE TABLE SQL。其字段表、正文和索引说明尚有冲突，因此附录 B 按最新文件列出字段；standard_entity_id 已在原文列为 CHAR(36)，未对类型另作覆盖，不表示已从真实数据库核验现行结构。没有 Relationship_Graph_entity 或 Relationship_Graph_entity_alias 附录。简历字段按用户确认的 expert→resume 对应规则列出，recommend_resume_id 仅说明源列命名，不新增推荐关系。

| 分组 | 表 | 字段数 |
| --- | --- | --- |
| A 原表 | experts | 47 |
| A 原表 | experts_work_experience | 13 |
| A 原表 | experts_project_experience | 12 |
| A 原表 | experts_education_experience | 13 |
| A 原表 | resume | 47 |
| A 原表 | resume_work_experience | 13 |
| A 原表 | resume_project_experience | 12 |
| A 原表 | resume_education_experience | 13 |
| B 新设计 | graph_company_entity | 13 |
| B 新设计 | graph_school_entity | 14 |
| B 新设计 | graph_major_entity | 10 |
| B 新设计 | graph_name_mapping | 11 |
| B 新设计 | graph_company_relation | 11 |
| B 新设计 | graph_sync_batch | 10 |
| B 新设计 | graph_edge_mapping | 11 |

## 附录 A01 experts

专家已提供的原表 DDL。本表 47 个字段；以下每列均列出去向。

| experts 字段 | MySQL 类型 | 原表空值 | 新基线去向与说明 |
| --- | --- | --- | --- |
| id | INT | NOT NULL | 生成 person VID／person.id；连接原经历归属，不按姓名合并 |
| serial_number | CHAR(19) | NOT NULL | 原系统留存；本基线不入图，也不据此扩展人物关系 |
| name | VARCHAR(50) | NOT NULL | 写 person.name；SQL 人物显示与定位 |
| interview_nickname | VARCHAR(50) | NOT NULL | 原系统留存；本基线不入图，也不据此扩展人物关系 |
| company | VARCHAR(100) | NOT NULL | 原系统留存；本基线不入图，也不据此扩展人物关系 |
| job_status | TINYINT | NOT NULL | 原系统留存；本基线不入图，也不据此扩展人物关系 |
| job_name | VARCHAR(255) | NOT NULL | SQL 列表摘要；不是标准职位实体，不生成 held_role |
| contact_status | TINYINT | NOT NULL | 原系统留存；本基线不入图，也不据此扩展人物关系 |
| doubtful_flag | TINYINT | NOT NULL | 原系统留存；本基线不入图，也不据此扩展人物关系 |
| country | VARCHAR(50) | NOT NULL | 原系统留存；本基线不入图，也不据此扩展人物关系 |
| province | VARCHAR(50) | NOT NULL | 原系统留存；本基线不入图，也不据此扩展人物关系 |
| city | VARCHAR(50) | NOT NULL | SQL 列表 city；不入图 |
| email | VARCHAR(64) | NOT NULL | 原系统留存；本基线不入图，也不据此扩展人物关系 |
| country_code | VARCHAR(5) | NOT NULL | 原系统留存；本基线不入图，也不据此扩展人物关系 |
| phone | VARCHAR(30) | NOT NULL | 原系统留存；本基线不入图，也不据此扩展人物关系 |
| abroad_flag | TINYINT | NOT NULL | 原系统留存；本基线不入图，也不据此扩展人物关系 |
| other_contacts | VARCHAR(50) | NOT NULL | 原系统留存；本基线不入图，也不据此扩展人物关系 |
| currency | CHAR(10) | NOT NULL | 原系统留存；本基线不入图，也不据此扩展人物关系 |
| rate_value | DECIMAL(22,4) | NOT NULL | 原系统留存；本基线不入图，也不据此扩展人物关系 |
| rate_type | TINYINT | 可 NULL | 原系统留存；本基线不入图，也不据此扩展人物关系 |
| background | TEXT | NOT NULL | 原系统留存；本基线不入图，也不据此扩展人物关系 |
| comment | TEXT | 可 NULL | 原系统留存；本基线不入图，也不据此扩展人物关系 |
| edu_experience | TEXT | 可 NULL | 原系统 JSON 留存；不与结构化教育经历重复投影 |
| personal_intro | TEXT | 可 NULL | 原系统留存；本基线不入图，也不据此扩展人物关系 |
| remark | TEXT | 可 NULL | 原系统留存；本基线不入图，也不据此扩展人物关系 |
| certification_file | VARCHAR(500) | 可 NULL | 原系统留存；本基线不入图，也不据此扩展人物关系 |
| source_type | TINYINT | NOT NULL | 获客渠道留存；不能写入图 source_system |
| source_link | VARCHAR(255) | 可 NULL | 原系统留存；本基线不入图，也不据此扩展人物关系 |
| recommend_expert_id | INT | 可 NULL | 原系统留存；本基线不入图，也不据此扩展人物关系 |
| supplier_contract_id | INT | 可 NULL | 原系统留存；本基线不入图，也不据此扩展人物关系 |
| collaborate_num | INT | NOT NULL | 原系统留存；本基线不入图，也不据此扩展人物关系 |
| last_collaborate_time | INT | NOT NULL | 原系统留存；本基线不入图，也不据此扩展人物关系 |
| create_by | BIGINT | 可 NULL | 原业务审计留存；不入图，空值按原 DDL |
| update_by | BIGINT | 可 NULL | 原业务审计留存；不入图，空值按原 DDL |
| created_at | DATETIME(3) | 可 NULL | 原业务维护与后续同步线索；不入图，不能直接作为已确认增量水位 |
| updated_at | DATETIME(3) | 可 NULL | 原业务维护与后续同步线索；不入图，不能直接作为已确认增量水位 |
| deleted_at | DATETIME(3) | 可 NULL | 控制人物投影与 SQL 有效性；时间本身不入图 |
| age | INT | 可 NULL | 原系统留存；本基线不入图，也不据此扩展人物关系 |
| education | VARCHAR(20) | NOT NULL | 原系统留存；本基线不入图，也不据此扩展人物关系 |
| work_years | INT | 可 NULL | 原系统留存；本基线不入图，也不据此扩展人物关系 |
| gender | TINYINT(1) | NOT NULL | 原系统留存；本基线不入图，也不据此扩展人物关系 |
| certifications | TEXT | 可 NULL | 原系统留存；本基线不入图，也不据此扩展人物关系 |
| self_appraisal | TEXT | 可 NULL | 原系统留存；本基线不入图，也不据此扩展人物关系 |
| content_version | BIGINT UNSIGNED | NOT NULL | 原业务内容版本；不是本项目发布版本，不入图 |
| update_resume_time | VARCHAR(30) | NOT NULL | 原系统留存；本基线不入图，也不据此扩展人物关系 |
| resume_id | INT | 可 NULL | 原系统关联留存；本项目不据此自行跨库合并 |
| is_plugin | TINYINT | 可 NULL | 原系统留存；本基线不入图，也不据此扩展人物关系 |

## 附录 A02 experts_work_experience

专家已提供的原表 DDL。本表 13 个字段；以下每列均列出去向。

| experts_work_experience 字段 | MySQL 类型 | 原表空值 | 新基线去向与说明 |
| --- | --- | --- | --- |
| id | INT | NOT NULL | 写 worked_at.source_field_id，派生 source_record_id；不是图 Rank |
| company_name | VARCHAR(255) | NOT NULL | 对应确认映射和 worked_at 公司目标；原文留 SQL，不按名称自行匹配 |
| start_date | DATETIME | 可 NULL | 写 worked_at.start_date，DATETIME 转 YYYYMM；NULL 保留 |
| end_date | DATETIME | 可 NULL | 写 worked_at.end_date，DATETIME 转 YYYYMM；NULL 保留 |
| position_title | VARCHAR(255) | NOT NULL | 同条工作经历的原职位文本，留 SQL 展示；本基线无 held_role／role_id／标准职位词典 |
| work_description | TEXT | 可 NULL | 原经历说明留 SQL；不写图属性 |
| create_by | BIGINT | 可 NULL | 原业务审计留存；不入图，空值按原 DDL |
| update_by | BIGINT | 可 NULL | 原业务审计留存；不入图，空值按原 DDL |
| created_at | DATETIME | 可 NULL | 原业务维护与后续同步线索；不入图，不能直接作为已确认增量水位 |
| updated_at | DATETIME | 可 NULL | 原业务维护与后续同步线索；不入图，不能直接作为已确认增量水位 |
| deleted_at | DATETIME | 可 NULL | 控制 worked_at 是否进入新投影；删除时间本身不入图 |
| expert_id | INT | 可 NULL | 生成 worked_at 起点 p:expert:<id>；核对槽位 source_person_id |
| is_employed | INT | NOT NULL | 写 worked_at.is_current；1 为当前，2 为非当前；矛盾日期报错 |

## 附录 A03 experts_project_experience

专家已提供的原表 DDL。本表 12 个字段；以下每列均列出去向。

| experts_project_experience 字段 | MySQL 类型 | 原表空值 | 新基线去向与说明 |
| --- | --- | --- | --- |
| id | INT | NOT NULL | 原项目行主键，留 SQL 定位；不生成图 Rank 或项目边 |
| company_name | VARCHAR(255) | NOT NULL | 原项目关联公司文本，留 SQL；不等于雇主，不生成 worked_at |
| start_date | DATETIME | 可 NULL | 原项目开始时间，留 SQL；不写入工作任期或新图边 |
| end_date | DATETIME | 可 NULL | 原项目结束时间，留 SQL；不据此补充任职时间 |
| project_title | VARCHAR(255) | NOT NULL | 原项目名称，留 SQL；本基线无标准项目实体或 participated_in |
| work_description | TEXT | 可 NULL | 原项目说明留 SQL；不生成图属性 |
| create_by | BIGINT | 可 NULL | 原项目创建人审计，留 SQL；不入图 |
| update_by | BIGINT | 可 NULL | 原项目修改人审计，留 SQL；不入图 |
| created_at | DATETIME | 可 NULL | 原项目创建追溯，留 SQL；不入图或当作发布水位 |
| updated_at | DATETIME | 可 NULL | 原项目更新追溯，留 SQL；本基线未建设项目增量同步 |
| deleted_at | DATETIME | 可 NULL | 原项目删除时间，留 SQL；不控制其他工作／教育边 |
| expert_id | INT | 可 NULL | 原项目所属专家引用，留 SQL；不因此生成经历边 |

## 附录 A04 experts_education_experience

专家已提供的原表 DDL。本表 13 个字段；以下每列均列出去向。

| experts_education_experience 字段 | MySQL 类型 | 原表空值 | 新基线去向与说明 |
| --- | --- | --- | --- |
| id | INT | NOT NULL | 写 studied_at／studied_major.source_field_id，派生 source_record_id；不是图 Rank |
| expert_id | INT | 可 NULL | 生成 studied_at／studied_major 起点 p:expert:<id>；核对槽位 source_person_id |
| school_name | VARCHAR(255) | 可 NULL | 对应确认映射和 studied_at 学校目标；原文留 SQL |
| major | VARCHAR(255) | 可 NULL | 对应确认映射和 studied_major 专业目标；不代替职位或学历 |
| education_level | VARCHAR(255) | 可 NULL | 教育详情留 SQL；不是 major，不写图属性 |
| is_regular_enrollment | VARCHAR(255) | 可 NULL | 教育详情留 SQL；不写图属性 |
| start_date | DATETIME | 可 NULL | 写 studied_at／studied_major.start_date，DATETIME 转 YYYYMM；NULL 保留 |
| end_date | DATETIME | 可 NULL | 写 studied_at／studied_major.end_date，DATETIME 转 YYYYMM；NULL 保留 |
| create_by | BIGINT | NOT NULL | 原业务审计留存；不入图，空值按原 DDL |
| update_by | BIGINT | 可 NULL | 原业务审计留存；不入图，空值按原 DDL |
| created_at | DATETIME | 可 NULL | 原业务维护与后续同步线索；不入图，不能直接作为已确认增量水位 |
| updated_at | DATETIME | 可 NULL | 原业务维护与后续同步线索；不入图，不能直接作为已确认增量水位 |
| deleted_at | DATETIME | 可 NULL | 控制 studied_at／studied_major 是否进入新投影；删除时间本身不入图 |

## 附录 A05 resume

用户已确认简历原表结构沿用专家 DDL，expert 对应改为 resume。本表 47 个字段；以下每列均列出去向。

| resume 字段 | MySQL 类型 | 原表空值 | 新基线去向与说明 |
| --- | --- | --- | --- |
| id | INT | NOT NULL | 生成 person VID／person.id；连接原经历归属，不按姓名合并 |
| serial_number | CHAR(19) | NOT NULL | 原系统留存；本基线不入图，也不据此扩展人物关系 |
| name | VARCHAR(50) | NOT NULL | 写 person.name；SQL 人物显示与定位 |
| interview_nickname | VARCHAR(50) | NOT NULL | 原系统留存；本基线不入图，也不据此扩展人物关系 |
| company | VARCHAR(100) | NOT NULL | 原系统留存；本基线不入图，也不据此扩展人物关系 |
| job_status | TINYINT | NOT NULL | 原系统留存；本基线不入图，也不据此扩展人物关系 |
| job_name | VARCHAR(255) | NOT NULL | SQL 列表摘要；不是标准职位实体，不生成 held_role |
| contact_status | TINYINT | NOT NULL | 原系统留存；本基线不入图，也不据此扩展人物关系 |
| doubtful_flag | TINYINT | NOT NULL | 原系统留存；本基线不入图，也不据此扩展人物关系 |
| country | VARCHAR(50) | NOT NULL | 原系统留存；本基线不入图，也不据此扩展人物关系 |
| province | VARCHAR(50) | NOT NULL | 原系统留存；本基线不入图，也不据此扩展人物关系 |
| city | VARCHAR(50) | NOT NULL | SQL 列表 city；不入图 |
| email | VARCHAR(64) | NOT NULL | 原系统留存；本基线不入图，也不据此扩展人物关系 |
| country_code | VARCHAR(5) | NOT NULL | 原系统留存；本基线不入图，也不据此扩展人物关系 |
| phone | VARCHAR(30) | NOT NULL | 原系统留存；本基线不入图，也不据此扩展人物关系 |
| abroad_flag | TINYINT | NOT NULL | 原系统留存；本基线不入图，也不据此扩展人物关系 |
| other_contacts | VARCHAR(50) | NOT NULL | 原系统留存；本基线不入图，也不据此扩展人物关系 |
| currency | CHAR(10) | NOT NULL | 原系统留存；本基线不入图，也不据此扩展人物关系 |
| rate_value | DECIMAL(22,4) | NOT NULL | 原系统留存；本基线不入图，也不据此扩展人物关系 |
| rate_type | TINYINT | 可 NULL | 原系统留存；本基线不入图，也不据此扩展人物关系 |
| background | TEXT | NOT NULL | 原系统留存；本基线不入图，也不据此扩展人物关系 |
| comment | TEXT | 可 NULL | 原系统留存；本基线不入图，也不据此扩展人物关系 |
| edu_experience | TEXT | 可 NULL | 原系统 JSON 留存；不与结构化教育经历重复投影 |
| personal_intro | TEXT | 可 NULL | 原系统留存；本基线不入图，也不据此扩展人物关系 |
| remark | TEXT | 可 NULL | 原系统留存；本基线不入图，也不据此扩展人物关系 |
| certification_file | VARCHAR(500) | 可 NULL | 原系统留存；本基线不入图，也不据此扩展人物关系 |
| source_type | TINYINT | NOT NULL | 获客渠道留存；不能写入图 source_system |
| source_link | VARCHAR(255) | 可 NULL | 原系统留存；本基线不入图，也不据此扩展人物关系 |
| recommend_resume_id | INT | 可 NULL | 原系统留存；本基线不入图，也不据此扩展人物关系 |
| supplier_contract_id | INT | 可 NULL | 原系统留存；本基线不入图，也不据此扩展人物关系 |
| collaborate_num | INT | NOT NULL | 原系统留存；本基线不入图，也不据此扩展人物关系 |
| last_collaborate_time | INT | NOT NULL | 原系统留存；本基线不入图，也不据此扩展人物关系 |
| create_by | BIGINT | 可 NULL | 原业务审计留存；不入图，空值按原 DDL |
| update_by | BIGINT | 可 NULL | 原业务审计留存；不入图，空值按原 DDL |
| created_at | DATETIME(3) | 可 NULL | 原业务维护与后续同步线索；不入图，不能直接作为已确认增量水位 |
| updated_at | DATETIME(3) | 可 NULL | 原业务维护与后续同步线索；不入图，不能直接作为已确认增量水位 |
| deleted_at | DATETIME(3) | 可 NULL | 控制人物投影与 SQL 有效性；时间本身不入图 |
| age | INT | 可 NULL | 原系统留存；本基线不入图，也不据此扩展人物关系 |
| education | VARCHAR(20) | NOT NULL | 原系统留存；本基线不入图，也不据此扩展人物关系 |
| work_years | INT | 可 NULL | 原系统留存；本基线不入图，也不据此扩展人物关系 |
| gender | TINYINT(1) | NOT NULL | 原系统留存；本基线不入图，也不据此扩展人物关系 |
| certifications | TEXT | 可 NULL | 原系统留存；本基线不入图，也不据此扩展人物关系 |
| self_appraisal | TEXT | 可 NULL | 原系统留存；本基线不入图，也不据此扩展人物关系 |
| content_version | BIGINT UNSIGNED | NOT NULL | 原业务内容版本；不是本项目发布版本，不入图 |
| update_resume_time | VARCHAR(30) | NOT NULL | 原系统留存；本基线不入图，也不据此扩展人物关系 |
| resume_id | INT | 可 NULL | 原系统关联留存；本项目不据此自行跨库合并 |
| is_plugin | TINYINT | 可 NULL | 原系统留存；本基线不入图，也不据此扩展人物关系 |

## 附录 A06 resume_work_experience

用户已确认简历原表结构沿用专家 DDL，expert 对应改为 resume。本表 13 个字段；以下每列均列出去向。

| resume_work_experience 字段 | MySQL 类型 | 原表空值 | 新基线去向与说明 |
| --- | --- | --- | --- |
| id | INT | NOT NULL | 写 worked_at.source_field_id，派生 source_record_id；不是图 Rank |
| company_name | VARCHAR(255) | NOT NULL | 对应确认映射和 worked_at 公司目标；原文留 SQL，不按名称自行匹配 |
| start_date | DATETIME | 可 NULL | 写 worked_at.start_date，DATETIME 转 YYYYMM；NULL 保留 |
| end_date | DATETIME | 可 NULL | 写 worked_at.end_date，DATETIME 转 YYYYMM；NULL 保留 |
| position_title | VARCHAR(255) | NOT NULL | 同条工作经历的原职位文本，留 SQL 展示；本基线无 held_role／role_id／标准职位词典 |
| work_description | TEXT | 可 NULL | 原经历说明留 SQL；不写图属性 |
| create_by | BIGINT | 可 NULL | 原业务审计留存；不入图，空值按原 DDL |
| update_by | BIGINT | 可 NULL | 原业务审计留存；不入图，空值按原 DDL |
| created_at | DATETIME | 可 NULL | 原业务维护与后续同步线索；不入图，不能直接作为已确认增量水位 |
| updated_at | DATETIME | 可 NULL | 原业务维护与后续同步线索；不入图，不能直接作为已确认增量水位 |
| deleted_at | DATETIME | 可 NULL | 控制 worked_at 是否进入新投影；删除时间本身不入图 |
| resume_id | INT | 可 NULL | 生成 worked_at 起点 p:resume:<id>；核对槽位 source_person_id |
| is_employed | INT | NOT NULL | 写 worked_at.is_current；1 为当前，2 为非当前；矛盾日期报错 |

## 附录 A07 resume_project_experience

用户已确认简历原表结构沿用专家 DDL，expert 对应改为 resume。本表 12 个字段；以下每列均列出去向。

| resume_project_experience 字段 | MySQL 类型 | 原表空值 | 新基线去向与说明 |
| --- | --- | --- | --- |
| id | INT | NOT NULL | 原项目行主键，留 SQL 定位；不生成图 Rank 或项目边 |
| company_name | VARCHAR(255) | NOT NULL | 原项目关联公司文本，留 SQL；不等于雇主，不生成 worked_at |
| start_date | DATETIME | 可 NULL | 原项目开始时间，留 SQL；不写入工作任期或新图边 |
| end_date | DATETIME | 可 NULL | 原项目结束时间，留 SQL；不据此补充任职时间 |
| project_title | VARCHAR(255) | NOT NULL | 原项目名称，留 SQL；本基线无标准项目实体或 participated_in |
| work_description | TEXT | 可 NULL | 原项目说明留 SQL；不生成图属性 |
| create_by | BIGINT | 可 NULL | 原项目创建人审计，留 SQL；不入图 |
| update_by | BIGINT | 可 NULL | 原项目修改人审计，留 SQL；不入图 |
| created_at | DATETIME | 可 NULL | 原项目创建追溯，留 SQL；不入图或当作发布水位 |
| updated_at | DATETIME | 可 NULL | 原项目更新追溯，留 SQL；本基线未建设项目增量同步 |
| deleted_at | DATETIME | 可 NULL | 原项目删除时间，留 SQL；不控制其他工作／教育边 |
| resume_id | INT | 可 NULL | 原项目所属简历引用，留 SQL；不因此生成经历边 |

## 附录 A08 resume_education_experience

用户已确认简历原表结构沿用专家 DDL，expert 对应改为 resume。本表 13 个字段；以下每列均列出去向。

| resume_education_experience 字段 | MySQL 类型 | 原表空值 | 新基线去向与说明 |
| --- | --- | --- | --- |
| id | INT | NOT NULL | 写 studied_at／studied_major.source_field_id，派生 source_record_id；不是图 Rank |
| resume_id | INT | 可 NULL | 生成 studied_at／studied_major 起点 p:resume:<id>；核对槽位 source_person_id |
| school_name | VARCHAR(255) | 可 NULL | 对应确认映射和 studied_at 学校目标；原文留 SQL |
| major | VARCHAR(255) | 可 NULL | 对应确认映射和 studied_major 专业目标；不代替职位或学历 |
| education_level | VARCHAR(255) | 可 NULL | 教育详情留 SQL；不是 major，不写图属性 |
| is_regular_enrollment | VARCHAR(255) | 可 NULL | 教育详情留 SQL；不写图属性 |
| start_date | DATETIME | 可 NULL | 写 studied_at／studied_major.start_date，DATETIME 转 YYYYMM；NULL 保留 |
| end_date | DATETIME | 可 NULL | 写 studied_at／studied_major.end_date，DATETIME 转 YYYYMM；NULL 保留 |
| create_by | BIGINT | NOT NULL | 原业务审计留存；不入图，空值按原 DDL |
| update_by | BIGINT | 可 NULL | 原业务审计留存；不入图，空值按原 DDL |
| created_at | DATETIME | 可 NULL | 原业务维护与后续同步线索；不入图，不能直接作为已确认增量水位 |
| updated_at | DATETIME | 可 NULL | 原业务维护与后续同步线索；不入图，不能直接作为已确认增量水位 |
| deleted_at | DATETIME | 可 NULL | 控制 studied_at／studied_major 是否进入新投影；删除时间本身不入图 |

## 附录 B01 graph_company_entity

逐列来自更正文件的字段表；公共六列只展开到三张标准实体表和公司关系表。本表 13 个字段；以下每列均列出去向。

| graph_company_entity 字段 | MySQL 类型 | 原表空值 | 新基线去向与说明 |
| --- | --- | --- | --- |
| id | CHAR(36) | NOT NULL | 直接生成 e:<UUID> 并写 entity.id STRING；由表名派生 entity.kind=organization，不经 BIGINT 词典 |
| company_code | VARCHAR(64) | NOT NULL | 标准实体业务编号与唯一约束；用于来源定位／组织代码核对，不替代图 UUID |
| standard_name | VARCHAR(255) | NOT NULL | 直接写 entity.name；SQL 标准名搜索显示；同名不合并 |
| former_names | JSON | 可 NULL | 公司／学校旧名数组，供 SQL 搜索和追溯；不建独立 alias 表或别名节点 |
| verification_status | VARCHAR(64) | NOT NULL | 实体核验追溯；正式可发布枚举待确认，非空不等于通过 |
| child_company_codes | JSON | 可 NULL | 直接子／分公司编号数组；JSON 数字 0 同时覆盖确认无关系和未知，不能区分；SQL NULL 含义待确认，不生成本轮图边 |
| parent_company_codes | JSON | 可 NULL | 直接母／总公司编号数组；JSON 数字 0 不能证明确认无关系；SQL NULL 含义待确认；不递归合并或扩大同公司 |
| source_created_at | DATETIME(6) | NOT NULL | 来源创建追溯；不入图 |
| source_updated_at | DATETIME(6) | NOT NULL | 归一处理更新时间；用于快照核对，不是任期，不是已确认水位 |
| sync_batch_id | BIGINT UNSIGNED | NOT NULL | 来源批次外键／对账；不作 Rank，不直接写图属性 |
| synced_at | DATETIME(6) | NOT NULL | 同步落地时间；不等于数据截止点，不入图 |
| is_deleted | TINYINT UNSIGNED | NOT NULL | 标准实体有效性判断；graph_name_mapping 字段表未列此列，不能套用；不直接新增图属性 |
| deleted_at | DATETIME(6) | 可 NULL | 标准实体删除时间追溯；与 is_deleted 核对，不直接入图 |

## 附录 B02 graph_school_entity

逐列来自更正文件的字段表；公共六列只展开到三张标准实体表和公司关系表。本表 14 个字段；以下每列均列出去向。

| graph_school_entity 字段 | MySQL 类型 | 原表空值 | 新基线去向与说明 |
| --- | --- | --- | --- |
| id | CHAR(36) | NOT NULL | 直接生成 e:<UUID> 并写 entity.id STRING；由表名派生 entity.kind=school，不经 BIGINT 词典 |
| school_code | VARCHAR(64) | NOT NULL | 标准实体业务编号与唯一约束；用于来源定位／组织代码核对，不替代图 UUID |
| standard_name | VARCHAR(255) | NOT NULL | 直接写 entity.name；SQL 标准名搜索显示；同名不合并 |
| former_names | JSON | 可 NULL | 公司／学校旧名数组，供 SQL 搜索和追溯；不建独立 alias 表或别名节点 |
| official_code | VARCHAR(64) | 可 NULL | 学校官方代码，原设计不唯一；SQL 辅助定位，不入图 |
| country_region | VARCHAR(128) | 可 NULL | 学校地区，SQL 辅助展示／消歧；不入图 |
| city | VARCHAR(128) | 可 NULL | 学校城市辅助信息；不等于人物 city，不入图 |
| verification_status | VARCHAR(64) | NOT NULL | 实体核验追溯；正式可发布枚举待确认，非空不等于通过 |
| source_created_at | DATETIME(6) | NOT NULL | 来源创建追溯；不入图 |
| source_updated_at | DATETIME(6) | NOT NULL | 归一处理更新时间；用于快照核对，不是任期，不是已确认水位 |
| sync_batch_id | BIGINT UNSIGNED | NOT NULL | 来源批次外键／对账；不作 Rank，不直接写图属性 |
| synced_at | DATETIME(6) | NOT NULL | 同步落地时间；不等于数据截止点，不入图 |
| is_deleted | TINYINT UNSIGNED | NOT NULL | 标准实体有效性判断；graph_name_mapping 字段表未列此列，不能套用；不直接新增图属性 |
| deleted_at | DATETIME(6) | 可 NULL | 标准实体删除时间追溯；与 is_deleted 核对，不直接入图 |

## 附录 B03 graph_major_entity

逐列来自更正文件的字段表；公共六列只展开到三张标准实体表和公司关系表。本表 10 个字段；以下每列均列出去向。

| graph_major_entity 字段 | MySQL 类型 | 原表空值 | 新基线去向与说明 |
| --- | --- | --- | --- |
| id | CHAR(36) | NOT NULL | 直接生成 e:<UUID> 并写 entity.id STRING；由表名派生 entity.kind=major，不经 BIGINT 词典 |
| major_code | VARCHAR(64) | NOT NULL | 标准实体业务编号与唯一约束；用于来源定位／组织代码核对，不替代图 UUID |
| standard_name | VARCHAR(255) | NOT NULL | 直接写 entity.name；SQL 标准名搜索显示；同名不合并 |
| verification_status | VARCHAR(64) | NOT NULL | 实体核验追溯；正式可发布枚举待确认，非空不等于通过 |
| source_created_at | DATETIME(6) | NOT NULL | 来源创建追溯；不入图 |
| source_updated_at | DATETIME(6) | NOT NULL | 归一处理更新时间；用于快照核对，不是任期，不是已确认水位 |
| sync_batch_id | BIGINT UNSIGNED | NOT NULL | 来源批次外键／对账；不作 Rank，不直接写图属性 |
| synced_at | DATETIME(6) | NOT NULL | 同步落地时间；不等于数据截止点，不入图 |
| is_deleted | TINYINT UNSIGNED | NOT NULL | 标准实体有效性判断；graph_name_mapping 字段表未列此列，不能套用；不直接新增图属性 |
| deleted_at | DATETIME(6) | 可 NULL | 标准实体删除时间追溯；与 is_deleted 核对，不直接入图 |

## 附录 B04 graph_name_mapping

逐列来自更正文件的字段表；公共六列只展开到三张标准实体表和公司关系表。本表 11 个字段；以下每列均列出去向。

| graph_name_mapping 字段 | MySQL 类型 | 原表空值 | 新基线去向与说明 |
| --- | --- | --- | --- |
| id | CHAR(36) | NOT NULL | 归一映射 UUID 追溯；不是图 Rank；精确追溯需发布文件关联槽位 ID |
| entity_type | VARCHAR(16) | NOT NULL | company／school／major 决定目标表和图 kind／边类型；不是角色或项目 |
| source_namespace | VARCHAR(128) | NOT NULL | 与 source_field_id 定位原经历及字段含义；需命名空间白名单，不按字符串猜测 |
| source_field_id | VARCHAR(128) | NOT NULL | VARCHAR 原经历行 ID；须无损对应原表 id；不是人物键或 BIGINT 槽位 ID |
| company_id | CHAR(36) | 可 NULL | 目标公司 UUID，经 graph_company_entity.id 核对后形成 worked_at 终点 |
| school_id | CHAR(36) | 可 NULL | 目标学校 UUID，经 graph_school_entity.id 核对后形成 studied_at 终点 |
| major_id | CHAR(36) | 可 NULL | 目标专业 UUID，经 graph_major_entity.id 核对后形成 studied_major 终点 |
| processing_status | VARCHAR(64) | NOT NULL | 只消费已匹配且纳入确认发布范围的记录；当前无映射删除列，不能假装执行 is_deleted 过滤；其他状态不猜目标 |
| source_updated_at | DATETIME(6) | NOT NULL | 归一处理更新时间；用于快照核对，不是任期，不是已确认水位 |
| sync_batch_id | BIGINT UNSIGNED | NOT NULL | 来源批次外键／对账；不作 Rank，不直接写图属性 |
| synced_at | DATETIME(6) | NOT NULL | 同步落地时间；不等于数据截止点，不入图 |

## 附录 B05 graph_company_relation

逐列来自更正文件的字段表；公共六列只展开到三张标准实体表和公司关系表。本表 11 个字段；以下每列均列出去向。

| graph_company_relation 字段 | MySQL 类型 | 原表空值 | 新基线去向与说明 |
| --- | --- | --- | --- |
| id | CHAR(36) | NOT NULL | 组织关系来源 UUID；本基线未定义对应图边，不入图 |
| parent_company_id | CHAR(36) | NOT NULL | 直接父公司 UUID，校验 graph_company_entity 引用；不扩大同公司 |
| child_company_id | CHAR(36) | NOT NULL | 直接子／分公司 UUID，校验存在且不同于父端；不自动合并 |
| relation_type | VARCHAR(32) | NOT NULL | 子公司／分公司语义留存，当前不生成任职或层级图边 |
| verification_status | VARCHAR(64) | NOT NULL | 组织关系核验信息；未定义放行枚举，不入图 |
| source_created_at | DATETIME(6) | NOT NULL | 组织关系维护／批次追溯；不入图 |
| source_updated_at | DATETIME(6) | NOT NULL | 组织关系维护／批次追溯；不入图 |
| sync_batch_id | BIGINT UNSIGNED | NOT NULL | 组织关系维护／批次追溯；不入图 |
| synced_at | DATETIME(6) | NOT NULL | 组织关系维护／批次追溯；不入图 |
| is_deleted | TINYINT UNSIGNED | NOT NULL | 关系有效性校验；本基线不投影组织边 |
| deleted_at | DATETIME(6) | 可 NULL | 关系删除追溯；不入图 |

## 附录 B06 graph_sync_batch

逐列来自更正文件的字段表；公共六列只展开到三张标准实体表和公司关系表。本表 10 个字段；以下每列均列出去向。

| graph_sync_batch 字段 | MySQL 类型 | 原表空值 | 新基线去向与说明 |
| --- | --- | --- | --- |
| id | BIGINT UNSIGNED | NOT NULL | 批次追溯／引用与对账；不是实体 ID、Rank 或图 data_version |
| source_project_id | VARCHAR(64) | NOT NULL | 源系统项目定位；不是标准项目实体，不建项目节点 |
| sync_mode | VARCHAR(16) | NOT NULL | full／incremental 交付描述；不代表已实现增量 Worker |
| status | VARCHAR(16) | NOT NULL | 来源批次放行依据待定；不直接映射 lab_projection.status |
| started_at | DATETIME(6) | NOT NULL | 来源批次开始追溯；不入图 |
| snapshot_at | DATETIME(6) | 可 NULL | 快照截止线索；NULL 为未知，不自动作为任职日期或基准月 |
| finished_at | DATETIME(6) | 可 NULL | 批次结束追溯；单独非空不证明跨表完整 |
| expected_counts | JSON | 可 NULL | 对账预期数量；JSON 留 SQL／发布材料，不入图 |
| actual_counts | JSON | 可 NULL | 对账实际数量；不入图 |
| error_message | TEXT | 可 NULL | 来源错误定位；不入图 |

## 附录 B07 graph_edge_mapping

逐列来自更正文件的字段表；公共六列只展开到三张标准实体表和公司关系表。本表 11 个字段；以下每列均列出去向。

| graph_edge_mapping 字段 | MySQL 类型 | 原表空值 | 新基线去向与说明 |
| --- | --- | --- | --- |
| id | BIGINT | 原文未列 | 图 Rank；派生 fact_id=slot:<id>，不是实体 ID |
| source_system | VARCHAR(16) | 原文未列 | 写边 source_system 并生成起点人物来源前缀 |
| source_table | VARCHAR(64) | 原文未列 | 写边 source_table；派生 kind 与 source_record_id；定位经历表 |
| source_field_id | BIGINT | 原文未列 | 写边 source_field_id；回连原经历行，派生 source_record_id |
| source_field | VARCHAR(64) | 原文未列 | 写边 source_field，限定本次为 company_name／school_name／major |
| source_person_id | BIGINT | 原文未列 | 生成边起点并核对原经历所属人物，不是额外属性 |
| standard_entity_id | CHAR(36) | 原文未列 | 生成边终点 e:<UUID>；本版已列为与目标一致的 CHAR(36)；不经实体编号桥接，数据库迁移尚未执行 |
| edge_type | VARCHAR(64) | 原文未列 | 边类型键：worked_at／studied_at／studied_major；核对原表及字段 |
| created_at | DATETIME(6) | 原文未列 | 槽位维护时间；不入图、不等于发布完成 |
| updated_at | DATETIME(6) | 原文未列 | 槽位维护时间；不入图，更新／清理语义待确认 |
| deleted_at | DATETIME(6) | 原文未列 | 槽位失效过滤；图中新快照不投影该边。原文件未列本列可空性，建议有效行为空 |

## 依据与修订记录

最新设计文件：人物关系图谱MySQL表结构设计说明_映射表精简版(3).docx，SHA256=568229068f9930598b16ecb6703dc717eb00b9e111e777eae7bec247684b5a8e。已完整读取旧三表方案与误发精简版(1)用于确认废弃范围；两者不再提供当前字段规范。专家原字段依据 docs/examples/expert-source-tables.sql；简历按用户本轮确认的同结构对应规则列出，不再标作未确认模拟 DDL。

本轮核对成果：四类业务节点、三类边的完整图键与各 11 个建议属性；一个投影控制节点；15 表 250 列反向去向；字段类型、残留说明、表名、来源定位和发布缺口。新字段模型尚未运行，现有 v0.16 演示也未被替换，不能引用旧实验结果作为 UUID 新模型通过的证据。

修订记录：v1.0 按 MySQL 表展开；v1.1 改为图字段优先；v1.2 增加节点边分项与反查附录；v2.0 整理图构建规范。2026-11-06 v3.0 根据用户更正的精简版(2)废弃独立三表方案，改为 UUID 标准表直投、三类边与新 12 列归一映射，恢复全字段反查，列出源文件冲突和程序迁移差异。v3.0 对应设计基线 v0.16.1；同日 v3.1 按用户确认将 standard_entity_id 类型定为 CHAR(36)，更新三类边、附录和待确认状态，设计基线升为 v0.16.2。同日 v3.2 以精简版(3)为准，采用 *_entity 表名、删除 entity_key、按 11 列映射记录删除契约缺口，更新上下级 0 的含义，并记录用户确认的简历 DDL 对应规则。设计基线为 v0.16.3，运行代码仍为 v0.16。

相关材料：[主架构](query-system-architecture.md)、[数据交接](data-handoff.md)、[稳定标识与发布确认清单](stable-identifiers-and-publishing-questions.md)。本次所有样例均虚构，未访问 Supabase 或本机数据库，未执行新建表、图构建、服务切换或性能测试。
