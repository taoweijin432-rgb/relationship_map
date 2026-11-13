# 图模型执行顺序

当前目标：**uuid-relations-v5**，4 个业务 TAG、1 个控制 TAG、3 类经历边和 4 类人物关系边。

1. 选新的空间名，参考 space-local-example.ngql 的本机参数创建空间；等待可见后 USE。
2. 执行 uuid-facts-v3.ngql：无人物姓名的基础节点、经历边和控制节点定义。
3. 执行 person-relations-v3.ngql：人物关系边定义。
4. 加载并对账有效事实，再由图内查询计算和写入人物关系；模型标记使用 uuid-relations-v5。
5. 全部事实、关系与冻结 SQL 对账通过才能发布 ready 清单；不得应用到旧 source-slots-v2 或已发布空间。

基础 uuid-facts-v3.ngql 单独执行不代表人物关系层已建立。person 保存 source_system 与 serial_number，姓名回 MySQL 展示；旧 uuid-facts-v1.ngql 含人物姓名，只作为历史定义保留。人物关系边的 Rank 是局部证据序号，SQL 回查必须用 left_fact_rank／right_fact_rank。

隐私边界见 [人物姓名不入图](../../../docs/graph-privacy.md)。字段和规则见 [图 DDL](../../../docs/graph-ddl.md)、[预计算规范](../../../docs/person-relation-materialization.md)。v0.24 已将本机模拟服务切换至此模型；构建、查询及回退见 [迁移记录](../../../docs/uuid-graph-migration.md)。原 v0.16 空间保留，真实数据与生产增量未接入。

历史 person-relations-v2.ngql 保留，不包含 same_major；不能仅修改控制模型标记就当作 v3。

当前工作／教育边含经历组键和业务附属字段。uuid-facts-v2 仅来源属性的定义属于历史v4，不能据此拒绝新模型的业务编号。
