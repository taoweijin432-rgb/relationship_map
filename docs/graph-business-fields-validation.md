# 业务编号与经历附属字段验证

2026-11-06 ｜目标模型 uuid-relations-v5 ｜本机 NebulaGraph 3.8.0／SDK 3.8.3

本轮按用户要求重整节点与边：person 增加 serial_number，标准实体增加各自 code；工作边增加 experience_key／position_title，学校和专业边各增加 experience_key／education_level／is_regular_enrollment。姓名不入图，人物关系边结构保持不变。

实际执行固定演练 `backend/.venv/bin/python scripts/verify_person_relation_ddl.py --output docs/data-sources/person-relations-v5-business-native.json`，原始记录见 [报告](data-sources/person-relations-v5-business-native.json)。基础 DDL 为 [uuid-facts-v3](../infra/nebula/schema/uuid-facts-v3.ngql)，人物边仍复用 person-relations-v3.ngql。原人物关系人工基准 v3 不变，不从查询结果更新期望。

在两个本次新建的随机图空间中，分别完成 12 项检查：人物属性白名单／六节点回读、禁止旧姓名写入、3 项新增业务字段检查、原 7 项关系完整性与查询检查。A 15 条／B 11 条人物证据仍与完整人工基准一致；预算不足在人物边写入前阻断，两次空间均 dropped=true。

新增检查的人工预期：

- p:expert:101 的 source_system=expert，业务编号为 19 位虚构编号 E000000000000000101；不含人物姓名。
- 同公司两次任职 Rank 7001／7002，职位分别为“工程师”／“分析师”，experience_key 分别为 expert:experts_work_experience:1／:2，未被混成一段。
- 同一人物的学校 Rank 8001 与专业 Rank 9001，通过 experience_key=expert:experts_education_experience:11 在图内配对；学历“硕士”、统招原文“是”一致，教育日期保持未知。

业务字段检查在构建快照样例、执行 B 的工作事实失效指令之前运行；之后的完整人物关系回读验证 B 只剩仍有效证据。学校与专业配对仅验证该固定样例，不宣称新增“同校同专业”组合 API 已实现。

实际成功建出新 DDL，写入节点、事实和人物边；报告含人物属性与人物边描述、全部派生证据和 DDL／人工基准摘要。标准实体 code 本轮完成样例写入，未额外单测其生产唯一性或别名查询。源字段格式、来源行关联、隐私值检查等应用预检仍需在完整接入实现，DDL 本身不会替代这些约束。

没有访问 MySQL／Supabase，没有改变旧空间、账号、清单、API／前端或运行服务。没有发布 ready 清单。姓名回查、原表实际转换、真实数据权限、生产更新和容量均未验证；旧模拟图和 writer 未迁移／清理。
