# 远程 MySQL 只读接入与模拟验证

2026-11-09 ｜架构 v0.26 ｜图模型 uuid-relations-v5 ｜虚构冻结数据

用户确认目前没有可用远程数据库，授权通过模拟修改代码并测试。本轮聚焦远程 MySQL 连接与现有 SQL／图成对发布链路，采用独立容器验证真实 MySQL TCP 和 TLS 协议。容器与 API 同处本机，地理远程网络、正式来源和生产容量继续待验证。

## 实现与决定依据

新增 UUID 清单 format_version=5，继承 v0.25 的 mutation-sequence-v1 发布标记。source_endpoint 绑定 MySQL 主机、端口、CA 文件 SHA-256，以及连接／读取超时。source_database 接受 1–64 位字母、数字、下划线名称。远程 URL 必须匹配清单中的地址、端口和库名，使用 mysql+pymysql，携带账号密码，仅允许 utf8mb4 字符集参数。

远程只读连接使用 Python SSLContext，要求可信 CA、主机身份校验及至少 TLS 1.2。PyMySQL 1.2.3 在显式 SSLContext 下要求服务端支持 TLS，原生专项验证了缺少 TLS 能力时在发送认证数据前失败。超时、数据库断连沿用存储错误响应，来源版本漂移返回 SOURCE_VERSION_MISMATCH 409。

查询连接复用既有池与会话规则，连接池 5、无溢出、等待 3 秒，事务只读、REPEATABLE READ、UTC 和严格 SQL 模式。连接超时默认 3 秒、可配置 1–30 秒，读取超时默认 5 秒、可配置 1–60 秒。SQL 语句执行上限与业务路径预算仍分别管理。

远程账号支持一般账号名称，启动仍检查 SHOW GRANTS，当前接受直接授予的 USAGE 加目标库 SELECT，拒绝额外权限和 GRANT OPTION。通过角色、按表授权及托管服务特殊授权格式，需要取得实际样例后另行适配。

本轮复用现有 API 来源环境变量与发布目录。open_source_engine 在 API 启动和发布完整验证时统一选择连接方式。api.env 保持 600 权限，保存两项 export；密码不进入清单或接口。format_version=5 的发布目录另需 mysql-ca.pem，其内容加入 bundle_digest。激活指针固定清单、凭据与 CA 的摘要，运行时配置变化触发 RELEASE_CHANGED 409。

format_version=2／3／4 继续使用原本机校验。lab_url 与实验写入工具继续限制本机 relationship_lab_ 库。v5 远程查询入口只开放读取；发布标记及触发器由数据提供方按约定预先准备，运行时不安装或更新它们。本轮只在新建模拟容器中安装辅助表与36个DML触发器。

## 未来远程配置形态

下面字段加入配套 UUID 发布清单，其余字段仍包括版本、图空间、完整来源摘要、图摘要、基准月和计数。

```json
{
  "format_version": 5,
  "model": "uuid-relations-v5",
  "data_mode": "mock",
  "sql_guard": "mutation-sequence-v1",
  "source_database": "published_people",
  "source_endpoint": {
    "host": "mysql.example.test",
    "port": 3306,
    "ca_sha256": "替换为mysql-ca.pem的64位十六进制SHA256",
    "connect_timeout": 3,
    "read_timeout": 5
  }
}
```

私有 api.env 引用同目录清单并保存匹配的 MySQL URL，特殊字符需按 URL 规则编码。启动可以使用直接清单配置，也可以使用现有发布工具完整核对、停服激活后通过 RELATIONSHIP_SOURCE_RELEASE_STORE 启动。外部账号与库需要满足当前12表查询适配和发布标记契约，已有图必须对应同一来源快照。

正式人物数据接入前还需扩展 data_mode、前端和导出标识，核对正式15表及发布契约。当前接口模式仍为 mock。

## 实际模拟环境

| 项目 | 本轮结果 |
| --- | --- |
| MySQL | 独立 Docker 容器，实际 8.4.13 |
| 镜像 | mysql:8.4@sha256:a81d043930e51745522bd5c430961cf8286f0a23f0a9a2a6e0108f7ea71b0902 |
| 网络 | 随机本机端口，只发布 127.0.0.1；清单主机 localhost |
| TLS | 测试 CA 签发 localhost SAN 服务证书，服务端 require_secure_transport=ON |
| SQL 库 | 最终复核 demo_remote_afce9765baab，验证普通库名 |
| 账号 | demo_reader，仅 SELECT、REQUIRE SSL，验证普通账号名 |
| 数据 | 冻结的63个来源人物、15个标准实体、178条事实 |
| 图 | 复用已完整核对的 relationship_lab_uuid_b19a220c6635，只读访问 |
| 验证目录 | data/remote-mysql-trial/run-v3-final；run-v2保留首次通过记录 |
| 生命周期 | 专项结束停止本次容器；--rm 回收容器及其匿名测试卷 |

测试证书有效期两天，仅用于重复新建实验。脚本输出目录权限700，凭据文件权限600。实验输出的连接地址随容器回收失效，重跑使用新输出目录。

## 验证结果

原生专项51项通过，包含原 UUID 图专项25项、远程新增离线17项和远程原生9项。复用了原始行与映射构造的独立关系基准，核对完整2576条人物证据边、反向证据、五类关系选择分页、同条经历、时间窗口、两段路径、对比和当前页导出。测试通过正常 create_app 入口装配远程 SQL，图仍负责关系及路径。

新增远程检查覆盖以下行为。

- 地址、端口、库名、驱动及附加 URL 参数必须匹配；特殊字符密码可正确解析。
- CA 文件摘要绑定、SSLContext 主机名和 CA 校验、最低 TLS 版本、配置超时生效。
- 实际连接 Ssl_cipher 非空，会话 transaction_read_only=1。
- 即使绕开会话只读，数据库拒绝 UPDATE、TRUNCATE、DROP TRIGGER；高权限账号启动被拒绝。
- localhost 证书经 127.0.0.1 访问时身份校验失败，不可信 CA 连接失败。
- 有效 MySQL 握手但缺少 TLS 能力时拒绝连接；服务端不发握手时按读取超时失败。
- 模拟数据库断连返回 STORAGE_UNAVAILABLE 503；错误来源摘要启动失败。
- 独立激活目录可查询；运行时 CA 文件变化触发409。
- 仅在本轮模拟库提交一条虚构姓名纠正，后续请求返回来源版本冲突。容器随后回收。

最终原始结果为 data/remote-mysql-trial/run-v3-final/tests.xml、tests.log、report.json，51项通过。第一次 run-v1 在建号 SQL 的百分号参数转义处失败，已修正为参数绑定，容器已回收，随后新建 run-v2 完成全部专项。补充清单结构异常检查及失败资源回收逻辑后，再新建 run-v3-final 复核通过。失败实验将清单移为failed-manifest.json，正式清单路径仅供验证成功的实验记录。

默认后端回归428项通过、240项按显式环境跳过，最终结果为data/remote-mysql-trial/default-backend.xml；Ruff 与 mypy 通过。OpenAPI／前端类型重新生成，前端格式检查、类型与构建通过。按check.sh的检查阶段分别执行，默认浏览器在隔离端口8194／5294运行，18项通过、15项其他模式跳过，结果为data/remote-mysql-trial/browser-default/results.json。隔离前后端进程已回收。既有 TestClient 弃用及 G6 构建体积提示仍存在。

## 复现

需要 Docker、本机图环境、已发布 v4 虚构来源及 backend/.venv，命令仅新建本轮独立容器。

```bash
backend/.venv/bin/python scripts/remote_mysql_lab.py \
  --source-bundle data/uuid-query-performance/guarded-v1 \
  --output data/remote-mysql-trial/my-new-run
```

脚本复制冻结源，验证完整来源摘要，复用只读图账号并完整对账，然后执行 test_uuid_graph.py 和 test_remote_mysql.py。拒绝覆盖输出目录；结束回收本次容器。失败目录保留诊断材料。

## 后续验证范围

真实远程环境仍需核对 DNS、网络准入、服务端证书与轮换、账号授权格式、目标 MySQL 版本及真实表结构。当前模拟没有引入广域网时延、丢包、地理故障或代表性并发，未产生远程性能容量结论。单表10000行启动预检、10000条人物边构建预算、正式15表接入、持续增量及生产权限继续按主方案重评。
