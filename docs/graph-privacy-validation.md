# 无人物姓名图模型验证

2026-11-06 ｜模型 uuid-relations-v4 ｜本机 NebulaGraph 3.8.0／SDK 3.8.3／backend/.venv

执行：`backend/.venv/bin/python scripts/verify_person_relation_ddl.py --output docs/data-sources/person-relations-v4-privacy-native.json`。使用新增 uuid-facts-v2 基础 DDL，复用 person-relations-v3 的四类人物边；旧 DDL 和历史报告未覆盖。

原始记录：[person-relations-v4-privacy-native.json](data-sources/person-relations-v4-privacy-native.json)。人工关系基准继续使用 [v3 样例](examples/person-relations-v3-expected.json)，因为删除姓名不改变身份键、经历或关系语义；不是用程序输出更新期望。

每个新临时图空间分别完成以下检查：

| 检查 | 结果 |
| --- | --- |
| DESCRIBE TAG person 恰好只有 source_system | 通过 |
| 六个人物的属性完整回读均只有 source_system | 通过；报告不含人物姓名 |
| 用固定虚构探针尝试写 person.name | 被数据库拒绝；未传入真实姓名 |
| 四类人物关系完整人工预期及全部写入回读 | A 15 条／B 11 条，一致 |
| 重复任职、反向证据、人物直接查询、两段路径、同校、同专业 | 保持通过 |
| 预算不足在人物关系写入前阻断 | 通过 |
| 临时空间清理 | 两个均 dropped=true |

每个快照共 9 项记录检查通过，最终 status=passed；基础 DDL、人物边 DDL 和人工基准摘要在报告中保存。两个新图的事实与人物关系计算均不依赖人物姓名。基础验证脚本也已改为无姓名样例，并以来源字段非空替换原姓名非空检查；本轮只运行组合演练，没有单独执行其 CLI 全套检查。

没有访问 MySQL 或 Supabase，没有修改业务源码、现有空间、账号、清单或运行服务。尚未实际验证 SQL 姓名批量回查、权限过滤、API／前端展示、日志／导出全链路和生产增量；本轮不能称现有应用已符合新隐私契约。

旧模拟 writer 与旧演示图仍可能含虚构姓名，本轮没有读取或清理其存量，不声称历史副本已经无姓名。下一轮真实接入必须使用新模型，旧模型不能因为只更换来源连接就用于真实姓名数据。
