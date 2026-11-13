# 六表来源与三表投影及原履历的独立验证

日期 2026-11-05，架构 v0.14。用户确认六张表继续作为上游归一来源，三张表属于本项目词典／投影层；同时提供 experts 及工作、项目、教育四张表的 DDL，简历侧按 expert→resume 模拟。

结论：已能从本地六表归一样例和真实形状的虚构原表，建立独立词典与稳定边槽位，投影规定的 VID／Rank，并在图内核对关系和回查原记录。本轮没有替换现有 API 的图格式，也没有建设生产词典治理或增量 Worker。数据均虚构，不访问 Supabase。

三表 Word SHA-256 为 `7e386037f0d463f2359adbd45db699676f538ac8992ad0090c927628ef085b26`。文档用于结构评审，其“自动择优／创建实体”和“回源计算关系”没有作为本轮执行指令；继续遵守上游归一、图计算关系／SQL 提供证据的已确认分工。

## 两套模型如何衔接

```mermaid
flowchart LR
    U[六表已确认归一结果] --> B[显式 UUID 到 BIGINT 桥接]
    B --> D[实体及别名词典]
    R[Expert 与 Resume 原经历] --> M[按来源表 主键 字段定位槽位]
    D --> M
    M --> G[独立实验图 新 VID 与稳定 Rank]
    G --> Q[图内共同经历及两段路径]
    Q --> E[按 Rank 回查映射与原经历证据]
```

公司、学校和专业的来源 UUID 通过 15 条本地 [桥接样例](examples/projection3-bridge.json) 对应 BIGINT。来源 UUID 不直接截断、哈希成 BIGINT，也不按名称合并。同名公司保留不同词典 ID，由上游已确认的 UUID 决定目标。

职位和项目暂缺上游归一交付，使用明确的虚构治理样例，不从专业生成职位、不自动处理歧义。匹配方式保存在本地 resolution-trace.json，因为文档三表中没有匹配方式字段。桥接文件与本轮初始 ID 分配不是正式生产持久映射方案；正式实施需有稳定的来源身份定位及词典维护入口，不能每次重跑列表后重新编号。

## 已实际建立的表与记录

| 对象 | 记录数 |
| --- | --- |
| Relationship_Graph_entity | 21 |
| Relationship_Graph_entity_alias | 34 |
| Relationship_Graph_edge_mapping | 252 |
| experts／resume | 18／46 |
| experts_work_experience／resume_work_experience | 19／43 |
| experts_education_experience／resume_education_experience | 18／42 |
| experts_project_experience／resume_project_experience | 2／2 |

原表实验保留用户给出的列、类型、默认值、索引、字符集及自增起点，仅精简注释；见 [专家原表 DDL](examples/expert-source-tables.sql)。八张表的实际数据均补造，联系方式为空。自增起点不是人数。

关系投影只消费必要的身份、归属、结构化经历、日期和软删除字段。experts.company／job_name 等主表展示字段不代替工作经历；edu_experience 文本 JSON 与结构化教育表的权威和去重规则尚未确认，未把两份相加。其他业务字段建表保留，不因此自动进入图谱或查询接口。

Resume 主表使用 `resume`，经历表使用 `resume_*_experience`，所属人物列为 resume_id，这是依据用户说明的本轮命名假设，待正式 DDL 核对。修正文档 work_expertience 拼写，采用用户直接提供的 experts_work_experience。

三表 [候选 DDL](examples/projection3-schema.sql) 严格保留列清单，并补充实验建议的外键、类型枚举、来源／字段／边类型组合检查和槽位唯一约束。别名不要求全局唯一，标准名也不唯一。三表 ID 使用显式正整数分配：MySQL 不允许 CHECK 引用 AUTO_INCREMENT 列，不能同时照搬这两种约束。正式 ID 分配器、并发治理和永不复用策略尚未实施。

边槽位唯一键是 `(source_system, source_table, source_field_id, source_field)`，不包含人物或目标实体。人物移归属、目标纠正时更新属性，保留槽位 id；槽位 id 直接用作 rank，保持有符号 64 位正整数范围。程序预检与严格 SQL 会话共同阻断非法范围，不能依赖非严格模式的数值转换。新实验连接按 UTC 使用时间戳，不修改 MySQL 全局配置。

## 图中实际保存与查询

最终实验 MySQL 库 `relationship_lab_handoff_aab83496cf21`，配置在 `data/projection-source-trial/run-v4/source.env`。图空间 `relationship_lab_three_6a9040da29b3`，84 个节点、246 条有效边；含软删除的 252 个槽位仍留在 SQL 中。所有原人物／实体顶点及有效边属性、rank 均通过实际回读对账。

- 人物 VID 为 `p:expert:<id>` 与 `p:resume:<id>`；同一个数字 13 分属两来源，不自动认定为同一人。上游需交付保留记录或身份关联的最终语义。
- 实体 VID 为 `e:<entity_id>`。
- 原始 datetime 转为图边 INT YYYYMM 的 start_date／end_date；未知保持 NULL。is_employed=1 且结束日期空才是当前任职；矛盾或未知状态会阻断。
- 六种边为 worked_at、held_role、participated_in、`collaborated with`、studied_at、studied_major。带空格的边类型使用反引号实际写入并读取；建议正式命名统一，但本轮未私自改成另一名称。
- 工作、学校关系的图内计算复用现有时间谓词；职位、项目和专业边只验收存储及来源，不推断同职位／同专业即人际关系，也没有给工作台增加这些查询能力。
- 图边记录源表、经历行、字段、来源及月份；证据 rank 能回查 SQL 映射和真实形状原经历，未将履历完整 JSON 复制进映射表。

实际图查询的人工控制结果：

| 查询 | 实际核对 |
| --- | --- |
| p:expert:1 与 p:resume:2 同公司同期 | 202101—202212，24 个月 |
| p:expert:1 与 p:resume:3 同期 | 无；曾任同公司保留两条非同期经历对 |
| p:expert:1 与 p:resume:4 同期 | 无，日期未知不补造同期 |
| p:expert:1 与 p:resume:2 同校 | 有，未知教育日期不认定同期 |
| p:expert:1 经中间人物连接 p:resume:8 | 中间人物 p:resume:7，两段分别为 24／71 个月 |

全部已返回控制证据按 rank 回查了源表行和所属人物。SQL 未重算图关系。记录见 [图查询控制结果](performance/projection3-business.json)。

事务演练修改一条工作经历的所属人物及公司，并同步修改该经历的所有槽位；修改词典名称后旧别名继续有效。rank、实体长期 ID 保持不变，预期图边起止点发生变化。事务随后回滚，源快照摘要保持不变。这验证的是槽位和新投影输入的语义，不是实际在线旧边删除、增量发布或故障恢复。

## 实测问题与边界

早期实验采用 `(entity_id, deleted_at)` 复合索引支持外键。在本机 MySQL 9.7.1、foreign_key_checks=1 下，deleted_at=NULL 时，不存在的 entity_id 被接受；在全新表、第一条反例、独立主键上均复现，因此不能归因于反例顺序。改为单列 entity_id 支持索引后，非法外键按预期报 1452，专项测试通过。

官方缺陷库存在可空非外键索引列导致漏检的相似报告 [MySQL Bug 121438](https://bugs.mysql.com/bug.php?id=121438)，报告版本为 26.7.0，与本机版本不同，不据此认定为同一内部缺陷或已在其他版本修复。本轮调整仅作用于新实验表的索引，没有修改全局优化器或外键设置；正式数据库版本仍需复测。应用侧引用与状态检查继续作为发布门槛。

仍待设计或上游确认：

1. 文档提及合并指向、地区／所属组织等消歧属性，但实体表未列这些字段；不能据相似度任意择优或创建新实体来满足“每条返回 ID”。
2. 文档提及匹配方式与投影发布状态，列清单没有对应字段，也没有图批次／已发布旧边定位／失败重试状态。三表字段不能单独实现可靠增量与旧边清理。
3. 已确认映射的上游 UUID 如何在独立词典长期定位，需要正式存储契约；桥接不能只依靠当前导出顺序。
4. 原表多态引用没有跨八表的物理外键，由来源白名单、人物归属、字段类型和完整槽位覆盖预检保证。原表不支持可靠硬删除通知时，仍需对账补偿。
5. 当前日期规则按月；当天边界、在职状态与日期纠正、原始时区需正式确认。主表 company／job_name 不代替经历表。
6. 人物 VID 按来源分开，与当前原型统一人物键的行为不同。真实人物去重仍由上游负责，本系统不根据姓名或 experts.resume_id 自行合并。
7. 当前 API 图格式仍为 format_version=1，使用 p|／e| 前缀和 experience 边；本实验使用不同 VID 和六类边，故清单刻意命名 lab-manifest.json，不能当作 API manifest 加载。未来迁移需明确版本、查询适配和现有保存条件的兼容，不通过重置演示库启用。

中间失败目录 run-v1（自增列 CHECK 定义试验）、run-v2／run-v3（索引调整前）保留，最终结果以 run-v4 为准。原有 API／演示库和已发布图投影未被覆盖。

## 重现与证据

```bash
backend/.venv/bin/python scripts/projection_source_lab.py \
  --six-source data/handoff-trial/run-v3 \
  --document /Users/yuka/Documents/图数据库投影三表设计与独立词典维护方案.docx \
  --output data/projection-source-trial/my-new-run
```

命令只接受新的输出目录，并通过本机 relationship_lab_ 管理边界新建实验资源。仅管理员构建新图；回读与业务控制查询使用该空间独立 GUEST 账号，凭据位于忽略目录且权限 600。实验清单在全部核对成功后才写出，不作为现有服务启动配置。

[完整实验报告](performance/projection3-validation.json) 保留输入文件摘要、源数据不变检查、表数量、槽位修正和图控制结果；[专项 JUnit](performance/projection3-schema-tests.xml) 记录六表／三表共 29 项实际 MySQL 和逻辑检查。全部为小样本功能与结构验证，没有新的生产性能或容量结论。

最新常规后端 365 项通过、160 项按配置跳过（15.53 秒），Ruff／mypy 55 源文件通过；前端格式、类型、构建与默认浏览器 18 项通过（45.2 秒）。数据库专项由前述 29 项单独执行，图实验由脚本实际构建和只读控制查询验收，不将跳过项当作通过。此前六表阶段的 482 项原生全回归与三模式接口 60 项、各 3 项浏览器继续单独保留，不能相加当作最新一次统一压测。

记录：[最新常规后端](performance/projection3-final-backend.xml)、[失败索引反例](performance/projection3-index-failure.xml)、[验证环境与源码摘要](performance/projection3-verification-context.json)。Python 均使用 backend/.venv；没有新增依赖、全局数据库配置变更、Supabase 调用或生产容量结论。开发服务已回收，实验数据库和图空间保留供核对。
