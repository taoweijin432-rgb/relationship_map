# 同专业关系补充验证

2026-11-06 ｜模型 uuid-relations-v3 ｜本机 NebulaGraph 3.8.0／SDK 3.8.3

用户提出补充同专业，本轮在原三类人物关系上增加 same_major。定义使用有效 studied_major 指向相同标准专业 UUID，不要求同校、同期、同届或教育时间，不解释为同职位或实际认识。

执行固定验证入口 scripts/verify_person_relation_ddl.py；在两个新临时图空间中先加载事实，再由 nGQL 计算并写入四类人物关系。完整人工基准为 [person-relations-v3-expected.json](examples/person-relations-v3-expected.json)，在旧人工基准上明确增加双方专业事实 9001／9002 的一条证据，不从查询输出生成；旧 v2 样例和报告保持不变。

原始结果：[person-relations-v3-native.json](data-sources/person-relations-v3-native.json)。报告含基础 DDL、v3 人物边 DDL 与人工样例 SHA-256、每个快照全部派生证据和 DESCRIBE 结果。

| 关系 | 原快照 A | 修正工作经历后的 B |
| --- | --- | --- |
| same_company | 12 | 9 |
| company_overlap | 1 | 0 |
| same_school | 1 | 1 |
| same_major | 1 | 1 |
| 合计证据边 | 15 | 11 |

两次各 7 项检查通过：完整人工预期及全部人物边回读、重复任职引用、反向同期证据、直接人物查询、两条人物边路径、未知日期同校，以及反向同专业。另分别验证预算不足在人物边写入前阻断。same_major 的共同目标为 e:44444444-4444-4444-8444-444444444444，left_fact_rank=9001、right_fact_rank=9002；双方教育时间未知且没有共同学校映射，仍能查同专业。反向读取不会交换证据原归属。

报告 status=passed，两个空间 dropped=true。没有访问 Supabase／MySQL，没有修改旧空间、账号、清单、API 或前端服务；无 ready 清单发布。新增脚本 Ruff 检查与包含业务源码的 Mypy 检查另行执行。

本轮仅验证限定图样例。新模型的真实 SQL 回查、专业映射失效与纠正全流程、组合筛选、API／前端迁移、发布流程和热门专业规模仍待后续验证。旧 v2 的三类人物边结果仍是历史有效证据，不作为 same_major 已上线的证明。
