> 已废弃的字段规范，供历史核对；当前依据为 docs/mysql-to-graph-fields.md v3.0。

# 人物关系图谱图数据库构建字段规范

文档版本 v2.0 ｜修订日期 2026-11-06 ｜对应实现 v0.16

本规范面向图数据库构建和数据交付人员，以图中的节点、边及其字段为唯一编排主线，规定每个图字段取自 MySQL 的哪张表、哪个字段，以及连接、转换、空值和校验规则。构建时先确定图对象，再按本规范回取来源，不按 MySQL 全字段清单决定入图范围。

适用基线为当前 source-slots-v2 原表与三表模型，API 清单格式为 format_version=2。已明确的字段映射作为后续构建基线；正式简历 DDL、职位与项目归一、稳定标识和发布契约仍须按第 17 节补齐后确认。本文不将本地模拟实现直接宣布为已确认的生产标准。

## 1 图模型与字段使用约定

业务图包含人物及五类标准实体，存储六类人物到实体的经历边。人物使用 person 标签；公司、学校、职位、专业、项目共用 entity 标签，通过 kind 区分。控制节点使用 lab_projection 标签。图负责关系与路径计算，MySQL 提供人物和原经历来源。

| 图对象 | 物理标签或边名 | 图标识与字段范围 |
| --- | --- | --- |
| 人物及五类标准实体 | person；entity | 第 2 至 7 节；逐类列出 VID 和全部标签属性 |
| 六类经历边 | worked_at、held_role、studied_at、studied_major、participated_in、collaborated with | 第 8 至 13 节；每类四项图键和 12 项属性；最后一种边名含空格 |
| 投影控制节点 | lab_projection | 第 14 节；VID、status、digest |

每个字段表按“图字段及类型、用途、MySQL 来源表、MySQL 来源字段、转换与空值规则”描述。来源表列和字段列用分号对应；出现多张表时，同时列出取值表和校验表。程序生成值明确注明无对应 MySQL 列，不要求源库增加同名字段。

图 VID 为 FIXED_STRING(128) 的键，不是普通属性；本基线要求 UTF-8 编码不超过 128 字节，超长拒绝而非截断。边完整键为起点 VID、终点 VID、边类型、Rank。STRING、BOOL、INT 为图属性类型，INT 使用有符号 64 位整数。实体 ID 和 Rank 均使用 1 至 2^63−1。

MySQL 表名大小写按本文保留。experts 和三类 experts 经历表依据已提供 DDL；resume 和三类 resume 经历表仅按当前模拟规则列出，正式接入前须核对真实表名、归属列和状态语义。Relationship_Graph_entity、Relationship_Graph_entity_alias、Relationship_Graph_edge_mapping 是本项目词典与投影层候选表，非上游六表的别名。

图构建直接读取原人物、原经历和三表。上游 graph_company、graph_school、graph_major 的归一结果经确认桥接进入实体词典；其 UUID 不直接作为本模型的实体 VID 或 Rank。正文不再逐列列出未入图的 MySQL 字段，控制摘要读取全行也不扩大业务图字段范围。

## 2 人物节点 person

格式：VID=p:expert:<人物 ID> 或 p:resume:<人物 ID>；标签 person；属性 id STRING、name STRING、active BOOL。专家和简历同数字主键仍生成不同节点，不按姓名合并。

| 图字段及类型 | 用途 | MySQL 来源表 | MySQL 来源字段 | 转换与空值规则 |
| --- | --- | --- | --- | --- |
| VID 图键 | 人物唯一标识 | experts 或 resume | id；来源由所取主表确定 | 必有主键；专家生成 p:expert:<id>，简历生成 p:resume:<id>；不以 serial_number 或姓名替代 |
| person.id STRING | 标签内人物引用 | experts 或 resume | id；来源同上 | 必有；写完整 VID，例如 p:expert:101，不是单独数字 101 |
| person.name STRING | 人物显示姓名 | experts 或 resume | name | 原 DDL 列 NOT NULL；原值写入。空字符串应交付前核对，不能用来合并或补造身份 |
| person.active BOOL | 已投影人物有效标记 | experts 或 resume | deleted_at | 仅 deleted_at=NULL 时投影，写 true；失效人物不投影为 active=false 节点 |

样例：VID=p:expert:101；person={id:"p:expert:101", name:"示例人物甲", active:true}。城市 city、摘要 job_name 当前留在 SQL 显示，不是图节点属性。source_type 是获客渠道，不是 expert／resume 来源。experts.resume_id 不自动用于跨库去重。

人物删除后，对应原经历和槽位应一致失效；仍有效的经历指向失效人物时，当前预检会阻断。此处只是本地冻结快照规则，生产删除通知仍待上游确认。

## 3 公司节点 organization

格式：VID=e:<实体 ID>；标签 entity；kind="organization"。本类节点由实体表 entity_type=organization 且 deleted_at=NULL 的行产生；接收 worked_at 和 collaborated with。

| 图字段及类型 | 用途 | MySQL 来源表 | MySQL 来源字段 | 转换与空值规则 |
| --- | --- | --- | --- | --- |
| VID 图键 | 公司唯一标识 | Relationship_Graph_entity | id | 必有正有符号 BIGINT；生成 e:<id>。示例 e:501；不能直接填上游 UUID |
| entity.id INT | 公司数字实体键 | Relationship_Graph_entity | id | 原值保存；必有，范围与正有符号 64 位 ID 一致；同名可有不同 ID |
| entity.kind STRING | 区分实体业务类别 | Relationship_Graph_entity | entity_type | 必有，值为 organization；与指向该节点的边类型核对，不从名称猜类型 |
| entity.name STRING | 公司标准显示名称 | Relationship_Graph_entity | canonical_name | 原 DDL 列 NOT NULL；原值保存，不使用原经历文本覆盖。空白名须交付前核对，不自动补名 |

样例：VID=e:501；entity={id:501, kind:"organization", name:"示例科技有限公司"}。当前没有 entity.active 属性；有效性来自 MySQL 的 deleted_at 过滤。

来源补充：graph_company 的 UUID、standard_name 经过明确桥接进入本地实体词典。母子／分公司仍是独立实体，不扩大同公司查询。 别名表的 entity_id、alias_name、deleted_at 用于搜索和原文校验，不写成独立图属性或别名节点。

实体更名只改变 name 的输入，不由名称重新选键。UUID→BIGINT 的长期登记、合并／拆分、旧 ID 重定向需正式约定；当前实验桥接不是生产 ID 分配器。有效槽位指向失效实体时预检拒绝。

## 4 学校节点 school

格式：VID=e:<实体 ID>；标签 entity；kind="school"。本类节点由实体表 entity_type=school 且 deleted_at=NULL 的行产生；接收 studied_at。

| 图字段及类型 | 用途 | MySQL 来源表 | MySQL 来源字段 | 转换与空值规则 |
| --- | --- | --- | --- | --- |
| VID 图键 | 学校唯一标识 | Relationship_Graph_entity | id | 必有正有符号 BIGINT；生成 e:<id>。示例 e:502；不能直接填上游 UUID |
| entity.id INT | 学校数字实体键 | Relationship_Graph_entity | id | 原值保存；必有，范围与正有符号 64 位 ID 一致；同名可有不同 ID |
| entity.kind STRING | 区分实体业务类别 | Relationship_Graph_entity | entity_type | 必有，值为 school；与指向该节点的边类型核对，不从名称猜类型 |
| entity.name STRING | 学校标准显示名称 | Relationship_Graph_entity | canonical_name | 原 DDL 列 NOT NULL；原值保存，不使用原经历文本覆盖。空白名须交付前核对，不自动补名 |

样例：VID=e:502；entity={id:502, kind:"school", name:"示例大学"}。当前没有 entity.active 属性；有效性来自 MySQL 的 deleted_at 过滤。

来源补充：graph_school 的 UUID、standard_name 经过桥接进入词典。同名学校不得直接合并；同校不推断同期、同班或认识。 别名表的 entity_id、alias_name、deleted_at 用于搜索和原文校验，不写成独立图属性或别名节点。

实体更名只改变 name 的输入，不由名称重新选键。UUID→BIGINT 的长期登记、合并／拆分、旧 ID 重定向需正式约定；当前实验桥接不是生产 ID 分配器。有效槽位指向失效实体时预检拒绝。

## 5 职位节点 role

格式：VID=e:<实体 ID>；标签 entity；kind="role"。本类节点由实体表 entity_type=role 且 deleted_at=NULL 的行产生；接收 held_role；任职边另以 role_id 引用。

| 图字段及类型 | 用途 | MySQL 来源表 | MySQL 来源字段 | 转换与空值规则 |
| --- | --- | --- | --- | --- |
| VID 图键 | 职位唯一标识 | Relationship_Graph_entity | id | 必有正有符号 BIGINT；生成 e:<id>。示例 e:601；不能直接填上游 UUID |
| entity.id INT | 职位数字实体键 | Relationship_Graph_entity | id | 原值保存；必有，范围与正有符号 64 位 ID 一致；同名可有不同 ID |
| entity.kind STRING | 区分实体业务类别 | Relationship_Graph_entity | entity_type | 必有，值为 role；与指向该节点的边类型核对，不从名称猜类型 |
| entity.name STRING | 职位标准显示名称 | Relationship_Graph_entity | canonical_name | 原 DDL 列 NOT NULL；原值保存，不使用原经历文本覆盖。空白名须交付前核对，不自动补名 |

样例：VID=e:601；entity={id:601, kind:"role", name:"研发经理"}。当前没有 entity.active 属性；有效性来自 MySQL 的 deleted_at 过滤。

来源补充：职位正式归一交付未确定；实验词典来自显式虚构治理结果。专业 major 不能替代 role，同职位不构成人际关系。 别名表的 entity_id、alias_name、deleted_at 用于搜索和原文校验，不写成独立图属性或别名节点。

实体更名只改变 name 的输入，不由名称重新选键。UUID→BIGINT 的长期登记、合并／拆分、旧 ID 重定向需正式约定；当前实验桥接不是生产 ID 分配器。有效槽位指向失效实体时预检拒绝。

## 6 专业节点 major

格式：VID=e:<实体 ID>；标签 entity；kind="major"。本类节点由实体表 entity_type=major 且 deleted_at=NULL 的行产生；接收 studied_major。

| 图字段及类型 | 用途 | MySQL 来源表 | MySQL 来源字段 | 转换与空值规则 |
| --- | --- | --- | --- | --- |
| VID 图键 | 专业唯一标识 | Relationship_Graph_entity | id | 必有正有符号 BIGINT；生成 e:<id>。示例 e:602；不能直接填上游 UUID |
| entity.id INT | 专业数字实体键 | Relationship_Graph_entity | id | 原值保存；必有，范围与正有符号 64 位 ID 一致；同名可有不同 ID |
| entity.kind STRING | 区分实体业务类别 | Relationship_Graph_entity | entity_type | 必有，值为 major；与指向该节点的边类型核对，不从名称猜类型 |
| entity.name STRING | 专业标准显示名称 | Relationship_Graph_entity | canonical_name | 原 DDL 列 NOT NULL；原值保存，不使用原经历文本覆盖。空白名须交付前核对，不自动补名 |

样例：VID=e:602；entity={id:602, kind:"major", name:"计算机科学"}。当前没有 entity.active 属性；有效性来自 MySQL 的 deleted_at 过滤。

来源补充：graph_major 归一来源经桥接进入词典。专业关联不证明学历等级，不产生当前“同专业”人际关系。 别名表的 entity_id、alias_name、deleted_at 用于搜索和原文校验，不写成独立图属性或别名节点。

实体更名只改变 name 的输入，不由名称重新选键。UUID→BIGINT 的长期登记、合并／拆分、旧 ID 重定向需正式约定；当前实验桥接不是生产 ID 分配器。有效槽位指向失效实体时预检拒绝。

## 7 项目节点 project

格式：VID=e:<实体 ID>；标签 entity；kind="project"。本类节点由实体表 entity_type=project 且 deleted_at=NULL 的行产生；接收 participated_in。

| 图字段及类型 | 用途 | MySQL 来源表 | MySQL 来源字段 | 转换与空值规则 |
| --- | --- | --- | --- | --- |
| VID 图键 | 项目唯一标识 | Relationship_Graph_entity | id | 必有正有符号 BIGINT；生成 e:<id>。示例 e:701；不能直接填上游 UUID |
| entity.id INT | 项目数字实体键 | Relationship_Graph_entity | id | 原值保存；必有，范围与正有符号 64 位 ID 一致；同名可有不同 ID |
| entity.kind STRING | 区分实体业务类别 | Relationship_Graph_entity | entity_type | 必有，值为 project；与指向该节点的边类型核对，不从名称猜类型 |
| entity.name STRING | 项目标准显示名称 | Relationship_Graph_entity | canonical_name | 原 DDL 列 NOT NULL；原值保存，不使用原经历文本覆盖。空白名须交付前核对，不自动补名 |

样例：VID=e:701；entity={id:701, kind:"project", name:"示例联合项目"}。当前没有 entity.active 属性；有效性来自 MySQL 的 deleted_at 过滤。

来源补充：当前项目词典来自明确虚构样例，正式项目归一待确认。同名项目不自动合并，当前未实现共同项目人际查询。 别名表的 entity_id、alias_name、deleted_at 用于搜索和原文校验，不写成独立图属性或别名节点。

实体更名只改变 name 的输入，不由名称重新选键。UUID→BIGINT 的长期登记、合并／拆分、旧 ID 重定向需正式约定；当前实验桥接不是生产 ID 分配器。有效槽位指向失效实体时预检拒绝。

## 8 任职边

格式：person → entity(kind=organization)；边类型 worked_at；Rank=映射槽位 id。表示该人一次原工作经历中的公司。现有同公司、同公司同期和有界连接链使用本边。

原经历表：experts_work_experience（归属 expert_id）或 resume_work_experience（归属 resume_id）。槽位条件：source_table 为对应表名、source_field=company_name、edge_type=worked_at；下列两张表分别给出本类边的四项图键和全部 12 个属性。

| 图字段及类型 | 用途 | MySQL 来源表 | MySQL 来源字段 | 转换与空值规则 |
| --- | --- | --- | --- | --- |
| 起点 VID 图键 | 经历所属人物 | Relationship_Graph_edge_mapping；experts_work_experience 或 resume_work_experience；experts 或 resume | source_system、source_person_id；expert_id／resume_id；人物 id | 必有；原经历归属与 source_person_id 一致且人物有效；生成 p:expert:<id> 或 p:resume:<id> |
| 终点 VID 图键 | 已确认标准实体 | Relationship_Graph_edge_mapping；Relationship_Graph_entity | entity_id；id、entity_type、deleted_at | 必有；生成 e:<entity_id>；有效目标 kind=organization。NULL、悬空、类型错误均阻断 |
| 边类型 图键 | 本类经历语义 | Relationship_Graph_edge_mapping | edge_type、source_table、source_field | 必有；本边为 worked_at，且必须满足上文槽位条件；不能用任意文本关系名 |
| Rank INT 图键 | 稳定事实槽位标识 | Relationship_Graph_edge_mapping | id | 必有正整数 1 至 2^63−1；不使用原经历 id 或 item_no；端点纠正后旧完整键仍需清理 |

### 边属性及 MySQL 来源

| worked_at 属性及类型 | 用途 | MySQL 来源表 | MySQL 来源字段 | 转换与空值规则 |
| --- | --- | --- | --- | --- |
| fact_id STRING | SQL 精确回查事实 | Relationship_Graph_edge_mapping | id | 必有；加 slot: 前缀，如 slot:7001；与本边 Rank 对应 |
| kind STRING | 事实类别 | Relationship_Graph_edge_mapping | source_table | 从合法表名派生，本边固定 employment；非空，不直接读取任意原类型文本 |
| active BOOL | 有效事实标记 | Relationship_Graph_edge_mapping；experts_work_experience 或 resume_work_experience；experts 或 resume；Relationship_Graph_entity | 各表 deleted_at；另校验归属、目标和原文 | 通过校验且均有效时写 true；NULL 删除时间表示有效；矛盾引用阻断，不把失效边保留为 false |
| start_date INT | 本次经历开始月 | experts_work_experience 或 resume_work_experience | start_date | DATETIME→年×100＋月；允许 NULL，不补日期；合法月份 190001 至 210012 |
| end_date INT | 本次经历结束月 | experts_work_experience 或 resume_work_experience | end_date | DATETIME→YYYYMM；允许 NULL；开始晚于结束拒绝；空值不自动等于至今 |
| is_current BOOL | 是否当前任职 | experts_work_experience 或 resume_work_experience | is_employed | 1→true、2→false；非空且仅允许 1／2；为 1 时 end_date 必须 NULL |
| role_id INT | 同条工作经历的职位键 | Relationship_Graph_edge_mapping；experts_work_experience 或 resume_work_experience | 同 source_system／source_table／source_field_id 且 source_field=position_title 的槽位 entity_id；原行 position_title | 使用同原工作行的职位目标；缺有效职位槽位可为 NULL，但原 position_title 非空而缺映射时预检阻断；不能借其他经历职位 |
| source_system STRING | 来源库类别 | Relationship_Graph_edge_mapping | source_system | 必有 expert／resume，并核对原表前缀；不是主表 source_type |
| source_record_id STRING | 含表名的经历引用 | Relationship_Graph_edge_mapping；experts_work_experience 或 resume_work_experience | source_table；原经历 id | 必有；拼接 <source_table>:<原经历 id>；不要求 MySQL 新增同名列 |
| source_table STRING | 原经历表定位 | Relationship_Graph_edge_mapping | source_table | 必有，仅 experts_work_experience 或 resume_work_experience；与 source_system 相符 |
| source_field_id INT | 原经历行定位 | Relationship_Graph_edge_mapping；experts_work_experience 或 resume_work_experience | source_field_id；原经历 id | 必有，二者相等；不能填人物 id、映射主键或上游 UUID |
| source_field STRING | 原字段定位 | Relationship_Graph_edge_mapping；experts_work_experience 或 resume_work_experience | source_field；原行 company_name | 必有且为 company_name；原字段值非空并通过对应目标别名校验，否则不能生成本边 |

原文校验依赖：experts_work_experience.company_name 或 resume_work_experience.company_name，以及 Relationship_Graph_entity_alias.entity_id、alias_name、deleted_at。先用映射 entity_id 明确目标，再按 NFKC 和首尾空白清理核对该目标的有效别名；不按别名猜唯一实体。

样例：起点 p:expert:101，终点 e:501，类型 worked_at，Rank=7001；fact_id=slot:7001，kind=employment，active=true，start_date=202001，end_date=202212，is_current=false，role_id=601；source_system=expert，source_table=experts_work_experience，source_field_id=9001，source_field=company_name，source_record_id=experts_work_experience:9001。

说明：公司与职位来自同一工作行。相同人多次任职保留各自槽位，不压成同人同公司一条事实。

## 9 职位边

格式：person → entity(kind=role)；边类型 held_role；Rank=映射槽位 id。表示该次任职中的标准职位。不是“同职位人物相识”的关系；当前连接链不沿职位节点探索。

原经历表：experts_work_experience（归属 expert_id）或 resume_work_experience（归属 resume_id）。槽位条件：source_table 为对应表名、source_field=position_title、edge_type=held_role；下列两张表分别给出本类边的四项图键和全部 12 个属性。

| 图字段及类型 | 用途 | MySQL 来源表 | MySQL 来源字段 | 转换与空值规则 |
| --- | --- | --- | --- | --- |
| 起点 VID 图键 | 经历所属人物 | Relationship_Graph_edge_mapping；experts_work_experience 或 resume_work_experience；experts 或 resume | source_system、source_person_id；expert_id／resume_id；人物 id | 必有；原经历归属与 source_person_id 一致且人物有效；生成 p:expert:<id> 或 p:resume:<id> |
| 终点 VID 图键 | 已确认标准实体 | Relationship_Graph_edge_mapping；Relationship_Graph_entity | entity_id；id、entity_type、deleted_at | 必有；生成 e:<entity_id>；有效目标 kind=role。NULL、悬空、类型错误均阻断 |
| 边类型 图键 | 本类经历语义 | Relationship_Graph_edge_mapping | edge_type、source_table、source_field | 必有；本边为 held_role，且必须满足上文槽位条件；不能用任意文本关系名 |
| Rank INT 图键 | 稳定事实槽位标识 | Relationship_Graph_edge_mapping | id | 必有正整数 1 至 2^63−1；不使用原经历 id 或 item_no；端点纠正后旧完整键仍需清理 |

### 边属性及 MySQL 来源

| held_role 属性及类型 | 用途 | MySQL 来源表 | MySQL 来源字段 | 转换与空值规则 |
| --- | --- | --- | --- | --- |
| fact_id STRING | SQL 精确回查事实 | Relationship_Graph_edge_mapping | id | 必有；加 slot: 前缀，如 slot:7002；与本边 Rank 对应 |
| kind STRING | 事实类别 | Relationship_Graph_edge_mapping | source_table | 从合法表名派生，本边固定 employment；非空，不直接读取任意原类型文本 |
| active BOOL | 有效事实标记 | Relationship_Graph_edge_mapping；experts_work_experience 或 resume_work_experience；experts 或 resume；Relationship_Graph_entity | 各表 deleted_at；另校验归属、目标和原文 | 通过校验且均有效时写 true；NULL 删除时间表示有效；矛盾引用阻断，不把失效边保留为 false |
| start_date INT | 本次经历开始月 | experts_work_experience 或 resume_work_experience | start_date | DATETIME→年×100＋月；允许 NULL，不补日期；合法月份 190001 至 210012 |
| end_date INT | 本次经历结束月 | experts_work_experience 或 resume_work_experience | end_date | DATETIME→YYYYMM；允许 NULL；开始晚于结束拒绝；空值不自动等于至今 |
| is_current BOOL | 是否当前任职 | experts_work_experience 或 resume_work_experience | is_employed | 1→true、2→false；非空且仅允许 1／2；为 1 时 end_date 必须 NULL |
| role_id INT | 同条工作经历的职位键 | Relationship_Graph_edge_mapping；experts_work_experience 或 resume_work_experience | 同 source_system／source_table／source_field_id 且 source_field=position_title 的槽位 entity_id；原行 position_title | 本边目标就是本工作行职位；有效 held_role 边的 role_id 等于本槽位 entity_id，不应为 NULL |
| source_system STRING | 来源库类别 | Relationship_Graph_edge_mapping | source_system | 必有 expert／resume，并核对原表前缀；不是主表 source_type |
| source_record_id STRING | 含表名的经历引用 | Relationship_Graph_edge_mapping；experts_work_experience 或 resume_work_experience | source_table；原经历 id | 必有；拼接 <source_table>:<原经历 id>；不要求 MySQL 新增同名列 |
| source_table STRING | 原经历表定位 | Relationship_Graph_edge_mapping | source_table | 必有，仅 experts_work_experience 或 resume_work_experience；与 source_system 相符 |
| source_field_id INT | 原经历行定位 | Relationship_Graph_edge_mapping；experts_work_experience 或 resume_work_experience | source_field_id；原经历 id | 必有，二者相等；不能填人物 id、映射主键或上游 UUID |
| source_field STRING | 原字段定位 | Relationship_Graph_edge_mapping；experts_work_experience 或 resume_work_experience | source_field；原行 position_title | 必有且为 position_title；原字段值非空并通过对应目标别名校验，否则不能生成本边 |

原文校验依赖：experts_work_experience.position_title 或 resume_work_experience.position_title，以及 Relationship_Graph_entity_alias.entity_id、alias_name、deleted_at。先用映射 entity_id 明确目标，再按 NFKC 和首尾空白清理核对该目标的有效别名；不按别名猜唯一实体。

样例：起点 p:expert:101，终点 e:601，类型 held_role，Rank=7002；fact_id=slot:7002，kind=employment，active=true，start_date=202001，end_date=202212，is_current=false，role_id=601；source_system=expert，source_table=experts_work_experience，source_field_id=9001，source_field=position_title，source_record_id=experts_work_experience:9001。

说明：role_id 等于本工作行职位槽位的目标 entity_id；该边自身就是职位槽位，不能用主表 job_name 或其他任职替代。

## 10 就读边

格式：person → entity(kind=school)；边类型 studied_at；Rank=映射槽位 id。表示一次原教育经历中的学校。现有同校和连接链使用本边，但不要求或推断同期就读。

原经历表：experts_education_experience（归属 expert_id）或 resume_education_experience（归属 resume_id）。槽位条件：source_table 为对应表名、source_field=school_name、edge_type=studied_at；下列两张表分别给出本类边的四项图键和全部 12 个属性。

| 图字段及类型 | 用途 | MySQL 来源表 | MySQL 来源字段 | 转换与空值规则 |
| --- | --- | --- | --- | --- |
| 起点 VID 图键 | 经历所属人物 | Relationship_Graph_edge_mapping；experts_education_experience 或 resume_education_experience；experts 或 resume | source_system、source_person_id；expert_id／resume_id；人物 id | 必有；原经历归属与 source_person_id 一致且人物有效；生成 p:expert:<id> 或 p:resume:<id> |
| 终点 VID 图键 | 已确认标准实体 | Relationship_Graph_edge_mapping；Relationship_Graph_entity | entity_id；id、entity_type、deleted_at | 必有；生成 e:<entity_id>；有效目标 kind=school。NULL、悬空、类型错误均阻断 |
| 边类型 图键 | 本类经历语义 | Relationship_Graph_edge_mapping | edge_type、source_table、source_field | 必有；本边为 studied_at，且必须满足上文槽位条件；不能用任意文本关系名 |
| Rank INT 图键 | 稳定事实槽位标识 | Relationship_Graph_edge_mapping | id | 必有正整数 1 至 2^63−1；不使用原经历 id 或 item_no；端点纠正后旧完整键仍需清理 |

### 边属性及 MySQL 来源

| studied_at 属性及类型 | 用途 | MySQL 来源表 | MySQL 来源字段 | 转换与空值规则 |
| --- | --- | --- | --- | --- |
| fact_id STRING | SQL 精确回查事实 | Relationship_Graph_edge_mapping | id | 必有；加 slot: 前缀，如 slot:7003；与本边 Rank 对应 |
| kind STRING | 事实类别 | Relationship_Graph_edge_mapping | source_table | 从合法表名派生，本边固定 education；非空，不直接读取任意原类型文本 |
| active BOOL | 有效事实标记 | Relationship_Graph_edge_mapping；experts_education_experience 或 resume_education_experience；experts 或 resume；Relationship_Graph_entity | 各表 deleted_at；另校验归属、目标和原文 | 通过校验且均有效时写 true；NULL 删除时间表示有效；矛盾引用阻断，不把失效边保留为 false |
| start_date INT | 本次经历开始月 | experts_education_experience 或 resume_education_experience | start_date | DATETIME→年×100＋月；允许 NULL，不补日期；合法月份 190001 至 210012 |
| end_date INT | 本次经历结束月 | experts_education_experience 或 resume_education_experience | end_date | DATETIME→YYYYMM；允许 NULL；开始晚于结束拒绝；空值不自动等于至今 |
| is_current BOOL | 是否当前任职 | 程序生成；本类原经历表无工作在职字段 | 无对应列 | 固定 false，不代表在读或项目是否进行中；不从主表 job_status 补取 |
| role_id INT | 同条工作经历的职位键 | 程序生成；本类不读取职位槽位 | 无对应列 | 固定 NULL；专业、学校、项目不当作标准职位 |
| source_system STRING | 来源库类别 | Relationship_Graph_edge_mapping | source_system | 必有 expert／resume，并核对原表前缀；不是主表 source_type |
| source_record_id STRING | 含表名的经历引用 | Relationship_Graph_edge_mapping；experts_education_experience 或 resume_education_experience | source_table；原经历 id | 必有；拼接 <source_table>:<原经历 id>；不要求 MySQL 新增同名列 |
| source_table STRING | 原经历表定位 | Relationship_Graph_edge_mapping | source_table | 必有，仅 experts_education_experience 或 resume_education_experience；与 source_system 相符 |
| source_field_id INT | 原经历行定位 | Relationship_Graph_edge_mapping；experts_education_experience 或 resume_education_experience | source_field_id；原经历 id | 必有，二者相等；不能填人物 id、映射主键或上游 UUID |
| source_field STRING | 原字段定位 | Relationship_Graph_edge_mapping；experts_education_experience 或 resume_education_experience | source_field；原行 school_name | 必有且为 school_name；原字段值非空并通过对应目标别名校验，否则不能生成本边 |

原文校验依赖：experts_education_experience.school_name 或 resume_education_experience.school_name，以及 Relationship_Graph_entity_alias.entity_id、alias_name、deleted_at。先用映射 entity_id 明确目标，再按 NFKC 和首尾空白清理核对该目标的有效别名；不按别名猜唯一实体。

样例：起点 p:expert:101，终点 e:502，类型 studied_at，Rank=7003；fact_id=slot:7003，kind=education，active=true，start_date=202001，end_date=202212，is_current=false，role_id=NULL；source_system=expert，source_table=experts_education_experience，source_field_id=9001，source_field=school_name，source_record_id=experts_education_experience:9001。

说明：没有教育日期仍可形成同校事实。学历等级和统招字段不写入本边；专业通过另一字段槽位表达。

## 11 专业边

格式：person → entity(kind=major)；边类型 studied_major；Rank=映射槽位 id。表示某次教育经历对应的标准专业。已实现投影回读；当前人际关系接口不增加“同专业”。

原经历表：experts_education_experience（归属 expert_id）或 resume_education_experience（归属 resume_id）。槽位条件：source_table 为对应表名、source_field=major、edge_type=studied_major；下列两张表分别给出本类边的四项图键和全部 12 个属性。

| 图字段及类型 | 用途 | MySQL 来源表 | MySQL 来源字段 | 转换与空值规则 |
| --- | --- | --- | --- | --- |
| 起点 VID 图键 | 经历所属人物 | Relationship_Graph_edge_mapping；experts_education_experience 或 resume_education_experience；experts 或 resume | source_system、source_person_id；expert_id／resume_id；人物 id | 必有；原经历归属与 source_person_id 一致且人物有效；生成 p:expert:<id> 或 p:resume:<id> |
| 终点 VID 图键 | 已确认标准实体 | Relationship_Graph_edge_mapping；Relationship_Graph_entity | entity_id；id、entity_type、deleted_at | 必有；生成 e:<entity_id>；有效目标 kind=major。NULL、悬空、类型错误均阻断 |
| 边类型 图键 | 本类经历语义 | Relationship_Graph_edge_mapping | edge_type、source_table、source_field | 必有；本边为 studied_major，且必须满足上文槽位条件；不能用任意文本关系名 |
| Rank INT 图键 | 稳定事实槽位标识 | Relationship_Graph_edge_mapping | id | 必有正整数 1 至 2^63−1；不使用原经历 id 或 item_no；端点纠正后旧完整键仍需清理 |

### 边属性及 MySQL 来源

| studied_major 属性及类型 | 用途 | MySQL 来源表 | MySQL 来源字段 | 转换与空值规则 |
| --- | --- | --- | --- | --- |
| fact_id STRING | SQL 精确回查事实 | Relationship_Graph_edge_mapping | id | 必有；加 slot: 前缀，如 slot:7004；与本边 Rank 对应 |
| kind STRING | 事实类别 | Relationship_Graph_edge_mapping | source_table | 从合法表名派生，本边固定 education；非空，不直接读取任意原类型文本 |
| active BOOL | 有效事实标记 | Relationship_Graph_edge_mapping；experts_education_experience 或 resume_education_experience；experts 或 resume；Relationship_Graph_entity | 各表 deleted_at；另校验归属、目标和原文 | 通过校验且均有效时写 true；NULL 删除时间表示有效；矛盾引用阻断，不把失效边保留为 false |
| start_date INT | 本次经历开始月 | experts_education_experience 或 resume_education_experience | start_date | DATETIME→年×100＋月；允许 NULL，不补日期；合法月份 190001 至 210012 |
| end_date INT | 本次经历结束月 | experts_education_experience 或 resume_education_experience | end_date | DATETIME→YYYYMM；允许 NULL；开始晚于结束拒绝；空值不自动等于至今 |
| is_current BOOL | 是否当前任职 | 程序生成；本类原经历表无工作在职字段 | 无对应列 | 固定 false，不代表在读或项目是否进行中；不从主表 job_status 补取 |
| role_id INT | 同条工作经历的职位键 | 程序生成；本类不读取职位槽位 | 无对应列 | 固定 NULL；专业、学校、项目不当作标准职位 |
| source_system STRING | 来源库类别 | Relationship_Graph_edge_mapping | source_system | 必有 expert／resume，并核对原表前缀；不是主表 source_type |
| source_record_id STRING | 含表名的经历引用 | Relationship_Graph_edge_mapping；experts_education_experience 或 resume_education_experience | source_table；原经历 id | 必有；拼接 <source_table>:<原经历 id>；不要求 MySQL 新增同名列 |
| source_table STRING | 原经历表定位 | Relationship_Graph_edge_mapping | source_table | 必有，仅 experts_education_experience 或 resume_education_experience；与 source_system 相符 |
| source_field_id INT | 原经历行定位 | Relationship_Graph_edge_mapping；experts_education_experience 或 resume_education_experience | source_field_id；原经历 id | 必有，二者相等；不能填人物 id、映射主键或上游 UUID |
| source_field STRING | 原字段定位 | Relationship_Graph_edge_mapping；experts_education_experience 或 resume_education_experience | source_field；原行 major | 必有且为 major；原字段值非空并通过对应目标别名校验，否则不能生成本边 |

原文校验依赖：experts_education_experience.major 或 resume_education_experience.major，以及 Relationship_Graph_entity_alias.entity_id、alias_name、deleted_at。先用映射 entity_id 明确目标，再按 NFKC 和首尾空白清理核对该目标的有效别名；不按别名猜唯一实体。

样例：起点 p:expert:101，终点 e:602，类型 studied_major，Rank=7004；fact_id=slot:7004，kind=education，active=true，start_date=202001，end_date=202212，is_current=false，role_id=NULL；source_system=expert，source_table=experts_education_experience，source_field_id=9001，source_field=major，source_record_id=experts_education_experience:9001。

说明：本边的来源字段是原教育行 major，不是个人主表 education；不能将专业当职位，也不用 item_no 猜学校和专业配对。

## 12 项目边

格式：person → entity(kind=project)；边类型 participated_in；Rank=映射槽位 id。表示该人在一次原项目经历中参与的标准项目。已实现投影，当前未实现共同项目人际查询。

原经历表：experts_project_experience（归属 expert_id）或 resume_project_experience（归属 resume_id）。槽位条件：source_table 为对应表名、source_field=project_title、edge_type=participated_in；下列两张表分别给出本类边的四项图键和全部 12 个属性。

| 图字段及类型 | 用途 | MySQL 来源表 | MySQL 来源字段 | 转换与空值规则 |
| --- | --- | --- | --- | --- |
| 起点 VID 图键 | 经历所属人物 | Relationship_Graph_edge_mapping；experts_project_experience 或 resume_project_experience；experts 或 resume | source_system、source_person_id；expert_id／resume_id；人物 id | 必有；原经历归属与 source_person_id 一致且人物有效；生成 p:expert:<id> 或 p:resume:<id> |
| 终点 VID 图键 | 已确认标准实体 | Relationship_Graph_edge_mapping；Relationship_Graph_entity | entity_id；id、entity_type、deleted_at | 必有；生成 e:<entity_id>；有效目标 kind=project。NULL、悬空、类型错误均阻断 |
| 边类型 图键 | 本类经历语义 | Relationship_Graph_edge_mapping | edge_type、source_table、source_field | 必有；本边为 participated_in，且必须满足上文槽位条件；不能用任意文本关系名 |
| Rank INT 图键 | 稳定事实槽位标识 | Relationship_Graph_edge_mapping | id | 必有正整数 1 至 2^63−1；不使用原经历 id 或 item_no；端点纠正后旧完整键仍需清理 |

### 边属性及 MySQL 来源

| participated_in 属性及类型 | 用途 | MySQL 来源表 | MySQL 来源字段 | 转换与空值规则 |
| --- | --- | --- | --- | --- |
| fact_id STRING | SQL 精确回查事实 | Relationship_Graph_edge_mapping | id | 必有；加 slot: 前缀，如 slot:7005；与本边 Rank 对应 |
| kind STRING | 事实类别 | Relationship_Graph_edge_mapping | source_table | 从合法表名派生，本边固定 project；非空，不直接读取任意原类型文本 |
| active BOOL | 有效事实标记 | Relationship_Graph_edge_mapping；experts_project_experience 或 resume_project_experience；experts 或 resume；Relationship_Graph_entity | 各表 deleted_at；另校验归属、目标和原文 | 通过校验且均有效时写 true；NULL 删除时间表示有效；矛盾引用阻断，不把失效边保留为 false |
| start_date INT | 本次经历开始月 | experts_project_experience 或 resume_project_experience | start_date | DATETIME→年×100＋月；允许 NULL，不补日期；合法月份 190001 至 210012 |
| end_date INT | 本次经历结束月 | experts_project_experience 或 resume_project_experience | end_date | DATETIME→YYYYMM；允许 NULL；开始晚于结束拒绝；空值不自动等于至今 |
| is_current BOOL | 是否当前任职 | 程序生成；本类原经历表无工作在职字段 | 无对应列 | 固定 false，不代表在读或项目是否进行中；不从主表 job_status 补取 |
| role_id INT | 同条工作经历的职位键 | 程序生成；本类不读取职位槽位 | 无对应列 | 固定 NULL；专业、学校、项目不当作标准职位 |
| source_system STRING | 来源库类别 | Relationship_Graph_edge_mapping | source_system | 必有 expert／resume，并核对原表前缀；不是主表 source_type |
| source_record_id STRING | 含表名的经历引用 | Relationship_Graph_edge_mapping；experts_project_experience 或 resume_project_experience | source_table；原经历 id | 必有；拼接 <source_table>:<原经历 id>；不要求 MySQL 新增同名列 |
| source_table STRING | 原经历表定位 | Relationship_Graph_edge_mapping | source_table | 必有，仅 experts_project_experience 或 resume_project_experience；与 source_system 相符 |
| source_field_id INT | 原经历行定位 | Relationship_Graph_edge_mapping；experts_project_experience 或 resume_project_experience | source_field_id；原经历 id | 必有，二者相等；不能填人物 id、映射主键或上游 UUID |
| source_field STRING | 原字段定位 | Relationship_Graph_edge_mapping；experts_project_experience 或 resume_project_experience | source_field；原行 project_title | 必有且为 project_title；原字段值非空并通过对应目标别名校验，否则不能生成本边 |

原文校验依赖：experts_project_experience.project_title 或 resume_project_experience.project_title，以及 Relationship_Graph_entity_alias.entity_id、alias_name、deleted_at。先用映射 entity_id 明确目标，再按 NFKC 和首尾空白清理核对该目标的有效别名；不按别名猜唯一实体。

样例：起点 p:expert:101，终点 e:701，类型 participated_in，Rank=7005；fact_id=slot:7005，kind=project，active=true，start_date=202001，end_date=202212，is_current=false，role_id=NULL；source_system=expert，source_table=experts_project_experience，source_field_id=9001，source_field=project_title，source_record_id=experts_project_experience:9001。

说明：项目目标采用明确确认结果，不按项目名称自行合并；不能仅凭项目边推断项目参与者实际认识。

## 13 项目公司边

格式：person → entity(kind=organization)；边类型 collaborated with；Rank=映射槽位 id。表示原项目经历中的公司关联。类型字面量含空格，nGQL 用反引号引用；不等于雇佣或任职。

原经历表：experts_project_experience（归属 expert_id）或 resume_project_experience（归属 resume_id）。槽位条件：source_table 为对应表名、source_field=company_name、edge_type=collaborated with；下列两张表分别给出本类边的四项图键和全部 12 个属性。

| 图字段及类型 | 用途 | MySQL 来源表 | MySQL 来源字段 | 转换与空值规则 |
| --- | --- | --- | --- | --- |
| 起点 VID 图键 | 经历所属人物 | Relationship_Graph_edge_mapping；experts_project_experience 或 resume_project_experience；experts 或 resume | source_system、source_person_id；expert_id／resume_id；人物 id | 必有；原经历归属与 source_person_id 一致且人物有效；生成 p:expert:<id> 或 p:resume:<id> |
| 终点 VID 图键 | 已确认标准实体 | Relationship_Graph_edge_mapping；Relationship_Graph_entity | entity_id；id、entity_type、deleted_at | 必有；生成 e:<entity_id>；有效目标 kind=organization。NULL、悬空、类型错误均阻断 |
| 边类型 图键 | 本类经历语义 | Relationship_Graph_edge_mapping | edge_type、source_table、source_field | 必有；本边为 collaborated with，且必须满足上文槽位条件；不能用任意文本关系名 |
| Rank INT 图键 | 稳定事实槽位标识 | Relationship_Graph_edge_mapping | id | 必有正整数 1 至 2^63−1；不使用原经历 id 或 item_no；端点纠正后旧完整键仍需清理 |

### 边属性及 MySQL 来源

| collaborated with 属性及类型 | 用途 | MySQL 来源表 | MySQL 来源字段 | 转换与空值规则 |
| --- | --- | --- | --- | --- |
| fact_id STRING | SQL 精确回查事实 | Relationship_Graph_edge_mapping | id | 必有；加 slot: 前缀，如 slot:7006；与本边 Rank 对应 |
| kind STRING | 事实类别 | Relationship_Graph_edge_mapping | source_table | 从合法表名派生，本边固定 project；非空，不直接读取任意原类型文本 |
| active BOOL | 有效事实标记 | Relationship_Graph_edge_mapping；experts_project_experience 或 resume_project_experience；experts 或 resume；Relationship_Graph_entity | 各表 deleted_at；另校验归属、目标和原文 | 通过校验且均有效时写 true；NULL 删除时间表示有效；矛盾引用阻断，不把失效边保留为 false |
| start_date INT | 本次经历开始月 | experts_project_experience 或 resume_project_experience | start_date | DATETIME→年×100＋月；允许 NULL，不补日期；合法月份 190001 至 210012 |
| end_date INT | 本次经历结束月 | experts_project_experience 或 resume_project_experience | end_date | DATETIME→YYYYMM；允许 NULL；开始晚于结束拒绝；空值不自动等于至今 |
| is_current BOOL | 是否当前任职 | 程序生成；本类原经历表无工作在职字段 | 无对应列 | 固定 false，不代表在读或项目是否进行中；不从主表 job_status 补取 |
| role_id INT | 同条工作经历的职位键 | 程序生成；本类不读取职位槽位 | 无对应列 | 固定 NULL；专业、学校、项目不当作标准职位 |
| source_system STRING | 来源库类别 | Relationship_Graph_edge_mapping | source_system | 必有 expert／resume，并核对原表前缀；不是主表 source_type |
| source_record_id STRING | 含表名的经历引用 | Relationship_Graph_edge_mapping；experts_project_experience 或 resume_project_experience | source_table；原经历 id | 必有；拼接 <source_table>:<原经历 id>；不要求 MySQL 新增同名列 |
| source_table STRING | 原经历表定位 | Relationship_Graph_edge_mapping | source_table | 必有，仅 experts_project_experience 或 resume_project_experience；与 source_system 相符 |
| source_field_id INT | 原经历行定位 | Relationship_Graph_edge_mapping；experts_project_experience 或 resume_project_experience | source_field_id；原经历 id | 必有，二者相等；不能填人物 id、映射主键或上游 UUID |
| source_field STRING | 原字段定位 | Relationship_Graph_edge_mapping；experts_project_experience 或 resume_project_experience | source_field；原行 company_name | 必有且为 company_name；原字段值非空并通过对应目标别名校验，否则不能生成本边 |

原文校验依赖：experts_project_experience.company_name 或 resume_project_experience.company_name，以及 Relationship_Graph_entity_alias.entity_id、alias_name、deleted_at。先用映射 entity_id 明确目标，再按 NFKC 和首尾空白清理核对该目标的有效别名；不按别名猜唯一实体。

样例：起点 p:expert:101，终点 e:501，类型 collaborated with，Rank=7006；fact_id=slot:7006，kind=project，active=true，start_date=202001，end_date=202212，is_current=false，role_id=NULL；source_system=expert，source_table=experts_project_experience，source_field_id=9001，source_field=company_name，source_record_id=experts_project_experience:9001。

说明：不把项目公司边改写成 worked_at；不借用其他工作经历任期，也不据此自动认定实际合作关系。

## 14 投影控制节点

格式：VID=meta|projection；标签 lab_projection；属性 status STRING、digest STRING。它是构建控制节点，不是人物或标准实体，不和六类经历边相连。

| 图字段及类型 | 用途 | MySQL 来源表 | MySQL 来源字段 | 转换与空值规则 |
| --- | --- | --- | --- | --- |
| VID 图键 | 定位投影标记 | 程序生成 | 无 | 固定 meta\|projection；不从业务主键生成，不允许空值 |
| lab_projection.status STRING | 构建状态 | 程序生成 | 无业务字段；不直接读取 graph_sync_batch.status | 先 building，写入完成后 ready；随后完整只读回读通过才发布清单，不能只凭 ready 发布 |
| lab_projection.digest STRING | 配对 SQL 快照 | 冻结八张原表和三张词典／映射表的内容 | 全部现有行列用于当前整行摘要；无独立摘要列 | source_digest 生成 SHA-256；非空。摘要使用不等于每个原字段都有业务图属性 |

reference_month、data_version、图空间引用和激活修订是清单／运行配置，不是上述图标签的新增属性。reference_month 为当前任职查询上界，end_date 仍可为 NULL；data_version 不是原主表 content_version。

当前单表 10000 行和每次完整摘要是小样本冻结保护，不是生产性能方案。当前仅支持停服切换成对不可变 SQL／图快照，不代表增量 Worker、在线清旧边或零停机发布已经实现。

## 15 空值与一致性规则

| 情形 | 当前处理 | 对能力的影响 |
| --- | --- | --- |
| SQL NULL 与空字符串 | 日期 NULL 保持未知；原名称 NULL／空白不生成对应边；有效映射指向空白原名时拒绝 | 不能以默认名字、默认日期或目标第一条补全 |
| 标准名称与姓名为空白 | 原列 NOT NULL 不等于禁止空字符串；投影函数不自动补名。API 对组织／学校／职位标准名称另有空白预检 | 交付前应核对；不能声称所有类别和所有层次均已统一拒绝空白名称 |
| 同期任期不完整 | 可靠区间才认定同期；工作当前且结束为空时取版本基准月 | 保留同公司，不凭未知日期推断完整同期 |
| 原记录和映射失效不同步 | 有效槽位指向失效人物／经历／实体时阻断；非空有效原字段缺有效槽位也阻断 | 先修正冻结副本，再重建新版本；不静默丢掉问题记录 |
| 多目标、别名歧义或身份不明 | 消费明确上游确认结果；同一槽位当前只允许一个目标 | 不猜人物，不复制同一任期／职位到拆分目标 |
| 位置和源键变动 | Slot ID 稳定不代表旧完整图键已删除；Rank 只是完整键的一部分 | 跨版本纠正和删除要对账；持久桥接和发布语义仍需上游确认 |

来源中人物身份统一、跨库去重、公司学校职位归一仍由数据库相关人员负责。六类边存储不等于六类人际关系上线；当前图内路径只使用任职／就读语义，普通筛选、相关列表、专题、完整对比和导出仍有 SQL／Domain 分工。前端展示是有数量上限的局部图。

## 16 图对象的构建与验收规则

节点和边应从同一冻结来源批次生成，写入新图空间。先构建有效人物及标准实体，再构建经历边；每种边按第 8 至 13 节单独核对完整键和全部属性。以下规则用于后续构建验收，不表示本次已重新执行数据库测试。

| 待验收图对象或字段 | 来源连接或检查规则 | 验收要求 |
| --- | --- | --- |
| 所有经历边的起点 VID | 映射 source_table 定位原经历表；source_field_id=原经历 id；source_person_id=expert_id 或 resume_id；再关联人物主表 id | 来源库类别、人物归属及人物有效性一致；不能用原经历 id 作为人物 id |
| 所有经历边的终点 VID | Relationship_Graph_edge_mapping.entity_id=Relationship_Graph_entity.id | 实体有效，entity_type 与边类型一致；同名不同 ID 保留独立节点 |
| 所有经历边的原字段 | source_field 精确定位原行字段；按映射 entity_id 与有效别名核对 | NFKC 与首尾空白清理后匹配指定实体别名；不通过别名重新猜目标 |
| 所有经历边的 Rank 与 fact_id | 槽位唯一键为 source_system、source_table、source_field_id、source_field；映射 id 派生 Rank 和 slot:<id> | 一个有效槽位只对应一个确认目标；重复槽位、多目标未决或非空原字段缺映射时阻断 |
| worked_at.role_id 与 held_role | 相同来源系统、原工作表、原工作行下的 position_title 槽位 | 公司与职位属于同条经历；不能从主表 job_name 或另一工作行补取 |
| start_date、end_date、is_current | 取本条原经历日期；工作状态取同工作行 is_employed | 月份有效，开始不晚于结束；当前任职结束必须为空；未知不补为至今 |
| 节点和边的完整属性 | 写入后回读 VID、完整边键和全部属性，与冻结输入推导值比较 | 数量和内容都一致；仅条数相等或抽查通过不能替代完整对账 |
| lab_projection.status 与 digest | 构建状态和同批次 SQL 内容摘要 | 完整回读通过后发布清单；失败批次不得接入查询服务 |
| 纠正后的边完整键 | 对比旧新起点、终点、边类型、Rank | Rank 保持不等于旧边已消失；当前通过新空间完整重建对账，旧图保留回退 |

原始日期、岗位、学历、项目说明等详情仍从 MySQL 回查。本规范只定义已列明的图字段；母子公司层级边、人物身份合并边、人物两两关系边及任意新增属性均需另行评审，不能从本次来源表说明自行推导。

## 17 图字段正式使用前的待确认项

| 受影响图字段 | 当前基线 | 正式接入所需确认 |
| --- | --- | --- |
| 人物 VID 与 person.id | p:expert:<id> 和 p:resume:<id> 分开 | 人物主键重导是否稳定、是否复用，以及跨库统一身份交付规则 |
| 简历节点及全部简历经历边 | resume 表及归属字段按模拟列出 | 正式简历 DDL、主外键、日期精度、状态与删除字段；不得直接将模拟列视为正式契约 |
| 实体 VID、entity.id 与边终点 | 本项目正有符号 BIGINT；UUID 经显式桥接 | 长期权威实体键、持久 UUID 到 BIGINT 桥接位置、合并拆分和旧键保留规则 |
| Rank、fact_id 与 source_* | 槽位 ID 作为稳定引用；一字段一个目标 | 经历键与槽位 ID 生命周期、字段迁移、多目标稳定子项键、纠正及删除通知 |
| role 节点、held_role 与 role_id | 当前来自明确虚构治理结果 | 正式职位词典与同条工作经历的归一映射；专业不可代替职位 |
| project 节点与两类项目经历边 | 当前项目目标来自明确模拟样例 | 项目权威键和归一责任，项目公司关联的业务含义 |
| 日期、is_current 与控制摘要 | 本地采用月份、1／2 在职状态、冻结批次 | 正式状态语义、时区、权威日期来源、完整批次完成标志及历史保留 |

这些缺项影响正式构建标准的确认，不改变当前已记录字段的含义。收到正式表结构或样本后，应在本文件逐项修订字段来源和决定依据，同步维护主方案及 Word 版本。详细问题见 stable-identifiers-and-publishing-questions.md。

## 18 规范依据与修订记录

字段来源依据：docs/examples/expert-source-tables.sql 和 docs/examples/projection3-schema.sql。上游归一到词典的关系参考 docs/examples/handoff-six-tables.sql。以上为当前已提供或候选 DDL，适用范围以第 1 节和第 17 节为准。

图字段与转换依据：backend/src/relationship_query/infrastructure/projection_source_trial.py 中的 projection_records；projection_source_graph.py 中的标签定义与 EDGE_SCHEMA；projection_source_schema.py 中的来源槽位和实体类型约束。图内查询与来源回查的职责以 docs/query-system-architecture.md v0.16 为准。

本文不要求照搬旧设计 Word 中的部署、同步或回源计算描述。图内关系与路径由图计算，SQL 用于人物、经历详情和来源完整性核对；六类边被存储不等于六类人际关系查询均已上线。

| 文档版本 | 日期 | 修订内容 |
| --- | --- | --- |
| v1.0 | 2026-11-06 | 按 MySQL 表展开来源字段 |
| v1.1 | 2026-11-06 | 改为图字段优先 |
| v1.2 | 2026-11-06 | 逐类展开节点和六类边，并附 MySQL 全字段反查 |
| v2.0 | 2026-11-06 | 全文改为图构建规范；移除按源表逐列反查附录，保留逐图字段来源；增加图模型、连接验收和正式确认条件 |

本次为文档修订，核对现有 DDL 和实现，未访问数据库、重建图、修改代码或运行服务；不新增生产验证结论。主架构版本保持 v0.16，Word 与本 Markdown 的字段定义同步。
