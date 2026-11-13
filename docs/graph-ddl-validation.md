# uuid-facts-v1 DDL 专项验证

日期：2026-11-06。范围：最新 UUID 标准实体模型的物理图定义与小样例图查询；运行应用仍为 v0.16，未切换服务、未迁移 API 或上游 SQL。

本次在现有本机 NebulaGraph 3.8.0、nebula3-python 3.8.3、backend/.venv 下验证。没有调用 Supabase 或 MySQL，没有停止或启动业务服务，没有改变既有图空间、账号、配置或清单。仅新建随机前缀 `relationship_lab_ddl_` 空间，结束后清理各次自己新建的空间。

## 结果

最终原始报告：[graph-ddl-v1-native-final.json](data-sources/graph-ddl-v1-native-final.json)。执行文件：[DDL](../infra/nebula/schema/uuid-facts-v1.ngql)；验证入口：[verify_graph_ddl.py](../scripts/verify_graph_ddl.py)。定义说明见 [图 DDL 与投影契约](graph-ddl.md)。

实际成功创建并 DESCRIBE 回读 5 个 TAG（4 个业务、1 个控制）和 3 类边；包含类型、可空性和无默认值的结果。6 名虚构人物、2 家公司、1 所学校、1 个专业，共 10 个业务节点；8 条工作边、2 条学校边、2 条专业边，另有一个测试控制节点。图证据 Rank 使用人工指定值，不从查询输出生成期望。

| 检查 | 独立期望 | 结果 |
| --- | --- | --- |
| 共同公司 | 甲查到乙、丙、丁；非同期和未知时间仍保留 | 通过 |
| 来源过滤 | 限简历后只有乙、丙 | 通过 |
| 同期计算 | 仅乙，双方 Rank 为 7001／7003；当前结束按 202611 解释 | 通过 |
| 重复任职 | 甲在同公司两个 Rank 7001／7002 都保留 | 通过 |
| 同校 | 甲与戊没有教育日期，仍可查共同学校 | 通过 |
| 一位中间人物 | 甲经乙连接戊，两段公司不同 | 通过 |
| 姓名非空约束 | name=NULL 拒绝 | 通过 |
| 工作状态非空约束 | is_current=NULL 拒绝 | 通过 |
| DDL 约束边界 | 错把学校作为 worked_at 终点且写 202013／202001，数据库仍接受 | 已证实需应用预检；坏边仅写临时空间并删除 |
| 控制节点 | 回读模型标识、基准月、staging 状态 | 通过 |

最终报告 `status=passed`，10 项检查通过，`temporary_space_dropped=true`。控制节点测试摘要只是虚构样例标识，不是实际冻结 MySQL 摘要；没有发布 ready 清单。Rank 返回证明图可以输出明确的经历边引用，但本次没有执行 MySQL 按 Rank 回查，所以不称 SQL 证据链全流程已通过。

静态检查：按 backend/pyproject.toml 运行新增脚本的 Ruff 检查通过；在 backend 内运行 `.venv/bin/mypy src ../scripts/verify_graph_ddl.py`，62 个源文件检查通过。没有修改后端业务源码或前端源码。

## 失败与修正记录

不覆盖失败记录：

- [attempt1](data-sources/graph-ddl-v1-attempt1.json)：验证脚本按分号拆语句，遇到 COMMENT 内的分号而在连接前拒绝；已把本版固定 DDL 注释中的分号改为逗号。该脚本只支持固定 DDL 文件，不是通用 nGQL 解析器。
- [attempt2](data-sources/graph-ddl-v1-attempt2.json)：受沙箱限制不能连接本机 19669；未创建空间。随后取得本机连接执行权限。
- [native 首次](data-sources/graph-ddl-v1-native.json)：DDL、共同公司、来源过滤、同期均通过；验收脚本错误地对原生 GO 使用 MATCH 的 ORDER BY 写法，错误码 -1004。已改为管道排序，新建空间复验成功；首次空间也已清理。此问题在专项脚本，不涉及运行 API。

## 未覆盖的事项

没有实施新 MySQL 适配、真实归一数据接入、完整字段预检、SQL 按 Rank 回查、API／前端契约迁移、成对清单发布、权限验收、异常恢复全流程、索引性能或目标规模压力测试。本轮没有修改前后端应用，因此没有重跑浏览器回归；新增验证脚本的静态检查单独执行。该结果仅支持“DDL 在当前版本可建出，所选查询能表达既定规则”，不构成上线或生产容量证明。

下一轮按本模型实施隔离模拟接入，重点验证同批次 graph_edge_mapping 是否能覆盖全部图 Rank、SQL 来源回查是否无歧义、删除与纠正是否清理旧完整键，以及接口和 G6 能否展示精简边属性对应的证据。
