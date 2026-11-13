# NebulaGraph 本地环境与验收（v0.10）

本页保留环境建设时的记录；后续 v0.11 模拟业务接入见 [图查询验收](graph-query-validation.md)。

日期：2026-11-03。用户请求建立图数据库环境。已在本机 OrbStack／Docker 中建立独立 NebulaGraph，当前保持运行；没有使用暂不可用的 Linux 服务器。业务 API 仍使用 SQLite／MySQL，本轮没有接通业务图投影或图候选仓储。

## 版本与资源

采用 NebulaGraph 社区版 3.8.0，官方 Python SDK nebula3-python 3.8.3。版本选择与已有 nGQL 技术方案及 [官方 SDK 兼容矩阵](https://github.com/vesoft-inc/nebula-python#compatibility-matrix) 对应，不代表最新产品或最终生产选型。宿主机 ARM64、16 GiB 内存，Docker 引擎约 7.82 GiB 内存、10 CPU；未使用 x86 模拟。

`infra/nebula/compose.yaml` 固定以下 ARM64 平台镜像摘要，不使用 latest／nightly：

| 服务 | 镜像摘要（均为 vesoft 对应服务 v3.8.0） | 内存／CPU 上限 |
| --- | --- | --- |
| metad | `sha256:0b41b13965585d7c1a021c1ef4ede17135d5713191545701638bf626cda80a45` | 512 MiB／0.5 |
| storaged | `sha256:e7a506625eb4f45dbc7ccc66764c76a89426d5c31f90b6304de98cfa6c2f901c` | 2 GiB／2 |
| graphd | `sha256:043ba449f2e42e53a8ca94ce23608e0782dc5ffa747b706a215711fb8c2c6dba` | 1 GiB／1 |

Storage block cache 128 MiB；这些都是本机试验限额，无容量结论。采用单 Meta／Storage／Graph 和单副本、单分区样例空间，不提供高可用。SDK 安装在 backend/.venv，依赖与传递包锁定于 backend/uv.lock；仅环境工具使用，池上限 2、RPC 超时 15 秒，不改变业务路径预算。

Docker 项目名 `relationship-nebula-lab`，专用 bridge 网络；Meta／Storage 数据与各服务日志使用本项目命名卷。仅将 Graph 原生协议发布到 **127.0.0.1:19669 → 容器 9669**。HTTP 健康端口留在容器网络内；本轮没有安装 Studio。原有 MySQL 和 Canal 保留。

## 启动、停止和连接

在项目根目录执行：

```bash
bash scripts/nebula.sh up
bash scripts/nebula.sh status
bash scripts/nebula.sh stop
bash scripts/nebula.sh down
```

`up` 启动并注册 Storage，再等待健康；重复执行复用已有数据和密码。`stop` 保留容器和卷，`down` 移除本项目容器／网络并保留卷；之后再 up 即恢复。没有自动删除卷、重置图空间或清理其他服务的命令。容器设置为手动启动，不随失败无限重启。

启用 `enable_authorize=true`，首次由工具生成 24 位随机密码并改变本机新集群默认密码。凭据文件 `data/nebula-lab/credentials.json`，权限 600，位于忽略目录中，不输出到命令行或报告。工具启动时自动读取；初始化完成后认证失败不回退默认密码、不自动重置。保留数据卷时也须保留凭据文件。认证配置依据 [官方用户管理说明](https://docs.nebula-graph.io/3.8.0/7.data-security/1.authentication/2.management-user/)。

## 已实际完成的验收

初始样例为两位虚构人物、一家公司、三条任职边；一位人物有两条指向同一公司的不同经历。用 rank 1／2 区分重复任职，记录独立 fact_id、职位、月份、当前任职、有效状态及来源定位。这里的手工 rank 只用于样例，不是未来正式经历键映射方案。

- SDK 原生连接成功；实际 Storage／Graph 版本均为 3.8.0，ONLINE；三个容器 healthy，镜像均为原生 arm64。
- 中文人物和公司写入／读取通过，两条相同人物—公司边没有互相覆盖。
- 空日期、当前任职、来源键与职位属性读回正确；只验证存取，没有在图中重算业务同期。
- PROFILE 命令执行成功；记录其结果行，不把结果行当作完整执行计划或性能报告。
- 按指定 rank 删除一条经历后，另一条仍存在；重复写入后事实与初始值一致。
- 移除并重建全部三个容器、保留命名卷，再只读核对同一空间与记录，结果一致；没有重建样例来伪装持久化成功。
- 错误密码认证失败；凭据权限、目标／空间约束、会话清理及异步等待的明确错误范围有测试。

保留的样例空间为 `relationship_lab_smoke_82aab9585264`。只读核对与独立新样例命令：

```bash
backend/.venv/bin/python scripts/nebula_lab.py verify \
  --input data/nebula-lab/smoke.json

backend/.venv/bin/python scripts/nebula_lab.py smoke \
  --output data/nebula-lab/new-smoke.json

RELATIONSHIP_NEBULA_TEST=1 backend/.venv/bin/pytest backend/tests/test_nebula_lab.py -q
```

每次 smoke 使用新图空间，已有报告拒绝覆盖；专项测试只移除自己创建的空间。本次排查中三个未完成样例空间已清理，保留通过的持久化样例。CLI 没有任意查询入口。

原始无凭据记录：[环境状态及镜像](performance/nebula-environment.json)、[读写样例](performance/nebula-smoke.json)、[重建后的持久化核对](performance/nebula-persistence.json)。内存观察仅为记录时刻的驻留量，不能推算 1 万／10 万或百万级图容量。

## 初次部署发现的问题

1. 当前 OrbStack 下，internal 网络虽有 HostConfig 端口配置，实际没有发布端口；已换为本项目专用 bridge 并保留 loopback 绑定，实际核查可连接。
2. 新 Storage 在注册前不提供预期健康状态。若 Graph 依赖 Storage 先 healthy，会阻塞 ADD HOSTS；现在先启动 Graph，注册 Storage，再验证所有服务健康。
3. Graph 端口可连接不等于 SDK 握手已就绪；认证密码和 Schema 变更也异步可见。仅在有限期限内等待已确认的握手、认证缓存和空间／Schema 暂未可见状态，解析、权限及其他存储错误仍立即失败。失败 SDK 池和会话均回收。
4. 首轮按边删除出现 5 秒客户端超时；后续独立读取确认删除已在服务端完成。没有据此判断操作未发生或自动重放不确定写入。环境验收 SDK 超时设为有限 15 秒后，新样例及完整回归均通过；该现象不构成性能或业务 SLA 结论，未来图查询仍须设计独立执行预算和取消语义。

## 整体回归及下一阶段

显式启用 MySQL 与 NebulaGraph 后运行：

```bash
RELATIONSHIP_MYSQL_TEST=1 RELATIONSHIP_NEBULA_TEST=1 bash scripts/check.sh
```

实际结果：后端 **385 项通过（58.54 秒）**，包含环境专项的 23 项离线检查和 1 项实际 SDK 集成验收；Ruff、mypy（39 个源文件）、OpenAPI 类型生成、前端格式／类型／构建通过。常规浏览器 **18 项通过（44.8 秒）**，1 项规模观察按约定跳过。前后端测试进程退出，图环境保留运行。既有 G6 构建块与 Starlette/httpx 提示保留。

下一阶段才实现：同一模拟快照投影、稳定 VID／经历 rank 映射、SQL／图批次完成标记、有界候选仓储、逐段 SQL 事实复核、缺失／滞后／故障语义，以及 MySQL 单独查询与图辅助查询的同规模对照。本轮没有为业务 API 启用图，也没有图数据库规模、Linux、并发容量、高可用或生产恢复结论。
