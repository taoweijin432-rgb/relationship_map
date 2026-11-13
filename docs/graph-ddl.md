# 图数据库节点、边与字段定义

字段版本 v2.0 ｜2026-11-06 ｜当前实施架构 v0.24 ｜模型 `uuid-relations-v5`

本版统一业务编号、工作信息、教育信息、人物关系预计算和姓名隐私要求。字段来源以最新精简版(3)、已确认专家 DDL 及简历 expert→resume 对应规则为依据；图属性名、类型转换、经历组键和控制节点是本项目设计，不冒称上游已有同名字段。v0.24 已按本文字段将本机虚构快照迁移到新图空间并接通 API／页面，见 [迁移报告](uuid-graph-migration.md)；正式15表及真实数据尚未接入。

完整 DDL：先在全新空间执行 [uuid-facts-v3.ngql](../infra/nebula/schema/uuid-facts-v3.ngql)，再执行 [person-relations-v3.ngql](../infra/nebula/schema/person-relations-v3.ngql)。后者的边结构复用 v3，完整模型名称仍为 uuid-relations-v5。历史文件及验收不覆盖；本机参数参考 [空间示例](../infra/nebula/schema/space-local-example.ngql)，空间名必须另取新值。

对应每个字段所需的MySQL输入、仅回查显示字段和全源表附录，见 [字段对应文档v5.0](mysql-to-graph-fields.md)。本文件继续定义物理图结构，不以映射文档新增SQL列。

## 1 对象总览

| 类别 | 对象 | 数量与职责 |
| --- | --- | --- |
| 业务节点 TAG | person、company、school、major | 4 类；身份、业务编号与标准实体名称 |
| 经历事实边 | worked_at、studied_at、studied_major | 3 类；每次任职／教育分别保留 |
| 预计算人物边 | same_company、company_overlap、same_school、same_major | 4 类；入图阶段图内计算并持久化 |
| 控制节点 TAG | projection_meta | 固定一条，管理整份投影版本与状态 |

全部属性默认不设置 DEFAULT。NULL 表示未知／未提供，不能擅自补齐。person 不含姓名、联系方式、别名、脱敏名或人物详情 JSON；姓名仅由 API 回 MySQL 后用于展示。业务编号允许入图，但不代表完全匿名。

## 2 图键：VID、端点与 Rank

空间 VID 类型为 FIXED_STRING(128)，构建时验证字节长度。图键不是下面 TAG／EDGE 表中的重复属性。

| 对象 | 图键定义 | 来源／约束 |
| --- | --- | --- |
| 人物 | p:expert:<id> 或 p:resume:<id> | experts.id／resume.id；来源隔离，不按姓名或编号自行跨库合并 |
| 公司 | e:<UUID>，company TAG | graph_company_entity.id |
| 学校 | e:<UUID>，school TAG | graph_school_entity.id |
| 专业 | e:<UUID>，major TAG | graph_major_entity.id |
| 控制节点 | meta:projection | 项目固定常量 |
| 事实边 Rank | graph_edge_mapping.id | 有符号 64 位正数，不能用原经历 ID 或重排序号替代 |
| 人物边 Rank | 同类型、src、dst 内按证据键排序的 1..N | 快照局部编号，不是 SQL 主键，不保证跨版本不变 |
| 完整边键 | src VID＋dst VID＋type＋Rank | 纠正端点时旧完整键必须消失 |

UUID 校验后采用一致的小写表示，三张实体表的跨类型 UUID 冲突必须阻断。实体 code 只作业务编号，身份由 UUID 决定；改编号不重建身份。事实起点来自边映射来源人物，必须与原经历 expert_id／resume_id 一致，目标须与有效归一映射及标准实体一致。

## 3 业务节点属性

### 3.1 person 人物

| 属性 | 图类型 | 可空 | MySQL 表／字段 | 用途与规则 |
| --- | --- | --- | --- | --- |
| source_system | STRING | 否 | 由 experts／resume 来源主表派生 | 仅 expert／resume，与 VID 前缀一致；用于来源过滤 |
| serial_number | STRING | 否 | experts.serial_number／resume.serial_number | 业务定位和编号展示；源 CHAR(19)，拒绝空白／超长；保留大小写，同源唯一，跨源不作为身份合并依据 |

没有 name、source_id、公司数组或学历数组。VID 已能回查来源主键；姓名、地区、工作年限、人物学历摘要等由 SQL 提供。

### 3.2 company 公司

| 属性 | 图类型 | 可空 | MySQL 表／字段 | 用途与规则 |
| --- | --- | --- | --- | --- |
| name | STRING | 否 | graph_company_entity.standard_name | 标准公司显示名，拒绝空白；允许同名，不据名称合并 |
| company_code | STRING | 否 | graph_company_entity.company_code | 标准公司业务编号，源 VARCHAR(64)；不是 UUID，不用作人物任职原文匹配 |

### 3.3 school 学校

| 属性 | 图类型 | 可空 | MySQL 表／字段 | 用途与规则 |
| --- | --- | --- | --- | --- |
| name | STRING | 否 | graph_school_entity.standard_name | 标准学校显示名，不据名称判断身份 |
| school_code | STRING | 否 | graph_school_entity.school_code | 标准学校业务编号，源 VARCHAR(64)；不等于官方代码 official_code |

### 3.4 major 专业

| 属性 | 图类型 | 可空 | MySQL 表／字段 | 用途与规则 |
| --- | --- | --- | --- | --- |
| name | STRING | 否 | graph_major_entity.standard_name | 标准专业显示名；不是职位或学历 |
| major_code | STRING | 否 | graph_major_entity.major_code | 标准专业业务编号，源 VARCHAR(64)；不替代专业 UUID |

former_names、学校官方代码与地区等暂留 SQL；专业表没有给出的学科门类、专业层次不虚构为已知来源。

## 4 worked_at 工作经历边

方向 person→company。每条对应同一条原工作经历的公司归一结果；事实 Rank 对应 graph_edge_mapping.id。

工作来源表为 experts_work_experience 或 resume_work_experience。边映射 source_table／source_field／edge_type 必须分别是相应工作表／company_name／worked_at。

| 属性 | 图类型 | 可空 | MySQL 来源 | 用途与转换 |
| --- | --- | --- | --- | --- |
| experience_key | STRING | 否 | graph_edge_mapping.source_system／source_table／source_field_id，核对原行 id | 派生 <来源>:<原表>:<原经历ID>，区分具体任职；不是上游新增列 |
| position_title | STRING | 是 | 同工作行 position_title | 该次任职的职位原文；源空字符串／纯空白转 NULL，不推断标准职位 ID |
| start_month | INT32 | 是 | 同工作行 start_date | 合法 DATETIME 转 YYYYMM；NULL 保留未知 |
| end_month | INT32 | 是 | 同工作行 end_date | 合法 DATETIME 转 YYYYMM；NULL 不单独代表在职 |
| is_current | BOOL | 否 | 同工作行 is_employed | 1→true、2→false，其他值预检失败；true 时原 end_date 必须为空 |

公司、职位和任期不能从不同经历拼接。职位原文可以用于本版经历展示及后续受控条件，不代表职位已经归一；旧标准职位 ID 控件不能直接套用。work_description 等长文本仍回 SQL，不能把姓名或个人详情伪装成职位写入。

## 5 studied_at 教育学校边

方向 person→school。来源为 experts_education_experience 或 resume_education_experience；映射槽位必须是相应教育表／school_name／studied_at。

| 属性 | 图类型 | 可空 | MySQL 来源 | 用途与转换 |
| --- | --- | --- | --- | --- |
| experience_key | STRING | 否 | 来源系统＋教育表＋原行 id，核对边映射来源定位 | 具体教育记录组键，用于与同条专业边配对 |
| education_level | STRING | 是 | 同教育行 education_level | 此次教育的学历原文；空白转 NULL，不从人物主表 education 猜填 |
| is_regular_enrollment | STRING | 是 | 同教育行 is_regular_enrollment | 原字段 VARCHAR(255)，保留原有效文本；空白转 NULL，不自行映射 BOOL |
| start_month | INT32 | 是 | 同教育行 start_date | YYYYMM；未知保留 NULL |
| end_month | INT32 | 是 | 同教育行 end_date | YYYYMM；未知不解释为在读／毕业 |

没有 is_current；同校不依赖教育时间，也不证明同届或实际认识。

## 6 studied_major 教育专业边

方向 person→major。来源仍为上述两张教育表；槽位为相应教育表／major／studied_major。

| 属性 | 图类型 | 可空 | MySQL 来源 | 用途与转换 |
| --- | --- | --- | --- | --- |
| experience_key | STRING | 否 | 来源系统＋教育表＋原行 id，核对边映射来源定位 | 与同原教育行的 studied_at 相同；不是人物 ID 或边 Rank |
| education_level | STRING | 是 | 同教育行 education_level | 保留此次学历，不是专业实体的属性 |
| is_regular_enrollment | STRING | 是 | 同教育行 is_regular_enrollment | 保留原有效文本；不推断真假枚举 |
| start_month | INT32 | 是 | 同教育行 start_date | YYYYMM；NULL 保留 |
| end_month | INT32 | 是 | 同教育行 end_date | YYYYMM；NULL 保留 |

两类教育边分别保留相同教育附属信息，使只有学校或只有专业被归一的记录仍能表达学历信息。同一 experience_key 的归属、学历、统招和日期必须一致；不因复制就认为是两次教育。一个学校／专业缺映射不自动撤销另一项确认结果。

## 7 四类人物关系边

四类边均 person→person，业务无向，按 ASCII VID 从小到大只存一个方向，查询双向读取。每条边保存一对具体事实依据；相同人物对有多次经历或共同实体时保留多个证据边，列表再去重人物。左／右固定对应存储 src／dst，不随查询中心改变。

### 7.1 same_company 曾任职同一公司

两人的有效 worked_at 指向同一公司 UUID，不要求日期完整或同期。

| 属性 | 图类型 | 可空 | 生成依据与用途 |
| --- | --- | --- | --- |
| entity_vid | STRING | 否 | 两条 worked_at 的共同公司 VID；可回查 graph_company_entity.id |
| left_fact_rank | INT64 | 否 | src 的 worked_at Rank，回查 graph_edge_mapping.id |
| right_fact_rank | INT64 | 否 | dst 的 worked_at Rank，回查 graph_edge_mapping.id |

### 7.2 company_overlap 同公司同期

同公司的一对有效工作经历有已知且有效的月份交集；是 same_company 的子集，两类可同时存在。

| 属性 | 图类型 | 可空 | 生成依据与用途 |
| --- | --- | --- | --- |
| entity_vid | STRING | 否 | 共同公司 VID |
| left_fact_rank | INT64 | 否 | src 的 worked_at Rank |
| right_fact_rank | INT64 | 否 | dst 的 worked_at Rank |
| overlap_start_month | INT32 | 否 | nGQL 取双方开始月份的较大值 |
| overlap_end_month | INT32 | 否 | nGQL 取双方有效结束月份的较小值 |

### 7.3 same_school 同校

两条有效 studied_at 指向同一学校 UUID，不要求教育时间。

| 属性 | 图类型 | 可空 | 生成依据与用途 |
| --- | --- | --- | --- |
| entity_vid | STRING | 否 | 共同学校 VID，可回查 graph_school_entity.id |
| left_fact_rank | INT64 | 否 | src 的 studied_at Rank |
| right_fact_rank | INT64 | 否 | dst 的 studied_at Rank |

### 7.4 same_major 同专业

两条有效 studied_major 指向同一专业 UUID，不要求同校或同期；不按专业名相似、岗位或大类推断。

| 属性 | 图类型 | 可空 | 生成依据与用途 |
| --- | --- | --- | --- |
| entity_vid | STRING | 否 | 共同专业 VID，可回查 graph_major_entity.id |
| left_fact_rank | INT64 | 否 | src 的 studied_major Rank |
| right_fact_rank | INT64 | 否 | dst 的 studied_major Rank |

三类非同期边不存交集属性。人物边的本身 Rank 只作本快照证据序号，不能直接回查 MySQL；真正来源引用为左右事实 Rank。图内预计算完整生成后才发布，一位中间人物沿两条人物边查询，不预计算所有间接人物对，不增加实际认识或推荐评分。

## 8 projection_meta 控制节点

固定 VID=meta:projection，不参与业务关系遍历。

| 属性 | 图类型 | 可空 | 来源与用途 |
| --- | --- | --- | --- |
| schema_version | STRING | 否 | 当前固定 uuid-relations-v5，不能把旧空间只改标记当迁移 |
| projection_id | STRING | 否 | 不可变投影唯一标识，不等于 sync_batch_id |
| snapshot_sha256 | FIXED_STRING(64) | 否 | 完整来源冻结范围与内容摘要；预检64位小写十六进制 |
| reference_month | INT32 | 否 | 显式查询基准月，如202611 |
| state | STRING | 否 | staging／ready；事实和人物边均完整对账才可ready |

## 9 来源、时间、状态与隐私规则

experience_key 示例：expert:experts_work_experience:1 或 resume:resume_education_experience:21。由已经核对的原经历 id 生成，source_field_id 是经历键而不是人物键；字符串归一映射键需先按命名空间验证能无损回连，不能盲目强转或取第一条。它补充事实 Rank，用于图内同条教育配对；不恢复归一映射表已删除的旧列，也不要求上游新增同名字段。

原日期须先检查日级合法性和区间顺序，再转月份。非当前缺结束月保持未知；当前任职且结束为空时仅在计算中用 reference_month 替代，不回写。开始或有效结束未知不能认定同期，仍可同公司；自身区间和双方交集都必须有效。跨年月份数用月份序号计算，不直接相减 YYYYMM。多证据不累加重叠月数凑阈值，基准月改变需重算并发布新版本。

有效事实需原人物／经历／边槽位未删除，目标未删除，名称映射已匹配且 is_deleted=0，并符合明确发布范围／核验状态。源缺行不当删除。图不重复存 active／is_deleted，失效不进新快照，其派生人物边也必须消失；保留其他有效证据。完整版本由新空间构建并停服成对切换，不原位更新已发布空间。

姓名只在 API 按人物 ID 批量回 SQL 后展示，不向图发送姓名查询，不回写显示 DTO；业务编号仍可回连个人，不等同匿名。新增职位与教育属性也按字段和值范围消费，不把姓名、联系信息或长文本作为旁路。SQL姓名回查、字段权限和真实值检查仍未在新应用实现。

## 10 暂不入图的信息

| 信息 | 保留位置与原因 |
| --- | --- |
| 人物姓名、昵称、电话、邮箱 | MySQL 授权查询后展示，不入人物／实体／边的旁路属性 |
| 个人简介、工作内容、评价、费率、附件 | SQL 按需读取，不为局部图复制个人长文本和业务详情 |
| 人物地区、工作年限、学历摘要 | 默认 SQL，未将可选建议自动纳入图 |
| 实体别名、学校官方代码和地区 | SQL 搜索／详情，后续按查询计划评估 |
| 单行更新时间 | SQL回查；整图版本／基准月由控制节点提供，两者不混用 |
| 项目、证书、技能、组织上下级边 | 不在本版关系范围，不能从字段存在推断业务已支持 |

## 11 验证与实施状态

本轮仅新定义业务属性 DDL 并用固定虚构样例在新图空间验证，入口 scripts/verify_person_relation_ddl.py；人工人物关系预期仍用 v3，因为身份／任期／实体未变。新增检查业务编号、重复工作职位和经历键、学校与专业同教育行配对，同时回归姓名拒绝与四类关系。结果见 [业务字段验证](graph-business-fields-validation.md)。不覆盖旧报告或默认演示数据。

以上描述 v0.22 的独立 DDL 轮次。后续 v0.24 已完成独立 UUID SQL 模拟库、新图构建、姓名与经历 SQL 回查、接口／前端／导出和停服激活迁移；旧图只保留历史回退，不清理全部副本。真实15表接入及生产验证仍未完成。DDL本身只强制类型与非空，引用、枚举、格式、同条经历、隐私和发布范围仍需应用预检及回读。

无属性索引或 TTL 的基线保持，SQL定位人物／实体后以已知 VID 有界遍历；热门实体的平方级人物边需代表性分布验证，预算耗尽不能截断后标完整。nGQL语法依据为官方 [CREATE TAG](https://docs.nebula-graph.io/3.8.0/3.ngql-guide/10.tag-statements/1.create-tag/) 与 [CREATE EDGE](https://docs.nebula-graph.io/3.8.0/3.ngql-guide/11.edge-type-statements/1.create-edge/)。

## 12 修订记录

v2.0，2026-11-06：按用户确认的业务编号、工作／教育附属需求重整全部节点和边；保留姓名禁入，新增标准实体code、职位、学历／统招原文及经历组键；人物关系边与控制属性不变。上一版见 [v1.3历史归档](archive/graph-ddl-v1.3-superseded.md)。
