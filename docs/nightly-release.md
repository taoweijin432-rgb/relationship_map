# 夜间停服与版本化发布

版本 v1.4，2026-11-13，对应主架构v0.59.4。保留各阶段记录，当前部署状态见本节及主方案。

## v1.4 实际夜间发布验收

2026年11月13日04:30定时任务实际执行双源采集、输入准备、候选构建、核验、切换及恢复，04:34:45返回published，04:34:46成功退出，全流程约286秒。退出恢复检查返回idle。该日志窗口记录整次任务耗时，维护阶段时长需要从作业阶段记录读取。

实际公网已核对关系版本real-921e1ee2e6476b0925bb-202611、mysql-live、6711专家及27715事实。下次定时触发为2026年11月14日04:30 Asia/Shanghai。当前前端为dist-layout-v059-label-fix，入口index-B_uaB6X5.js。正常发布和指定真实样例已验证，服务器异常回退演练与长期容量验证按提测计划推进。

夜间配置为/etc/relationship-map/nightly.json，实际部署采用双源全量只读快照，采集准备发生在维护之前。主架构及当前代码基线见[主方案](query-system-architecture.md)和[项目README](../README.md)。

## 历史实施与验证记录

## v1.3 服务器已部署并恢复调度

用户反馈在线人物模式mysql-live、3位实际人物字段比对、自动输入prepare-input全部通过，输入6525人物／25241事实。timer已恢复，下次2026-11-13 04:30 CST；nginx／query／tunnel均active、timer与recover均enabled、API真实模式健康。首次完整夜间构建及版本切换待运行反馈，详情见docs/live-mysql-and-nightly-input.md。每日任务会重新采集双源，当前运行采用夜间全量只读快照。

## v1.2 自动回源输入

新版可配置source_config_file，从两个角色自动全量采集并准备输入，随后衔接既有夜间发布。prepare-input可单独验证采集和准备。nightly和query通过私有mysql.env读取凭据，人物展示在线回MySQL，最新运行语义及按步骤补丁部署见docs/live-mysql-and-nightly-input.md。当前服务器仍为下节v0.56部署状态，新补丁及在线切换待验收。

## 服务器部署进度

2026-11-12用户逐步反馈更新包校验、27文件安装、依赖同步、双源及夜间配置校验通过。两处MySQL只读连接与必需表可见性通过，沿用TLS加密及指纹记录，证书链校验待CA配置。本次采集capture-20261112T080313Z生成nightly-input，6525人物／25241事实，候选real-32c7c46af8287ce504df-202611，plan为update_available。

Nginx维护路由已加载，短时页面503／API503及MAINTENANCE码、移除标记后页面200／旧API健康均由用户反馈通过。三个systemd任务安装并解析成功，timer与开机recover均enabled，recover返回Result=success、ExecMainStatus=0，下次触发2026-11-13 04:30 CST。首次完整夜间构建、发布切换及业务验收待运行结果，持续MySQL输入生成及在线人物查询继续待接入。

## 时间与当前实现

用户确认北京时间每天04:30开始，允许最长90分钟维护。定时器使用Asia/Shanghai时区，Persistent=false。程序的scheduled入口校验04:30至06:00窗口，并按剩余时间预留服务停止、恢复及启动核验预算。构建预算默认80分钟，启动核验3分钟，systemd主任务额外设90分钟保护，异常退出后执行恢复入口。

程序读取一份已封存的real-graph-plan-v1输入，调用现有build_real_graph.py完成新空间构建、全图及独立SQL核验，再切换query.env并恢复查询。输入供给位置为prepared_directory，源MySQL／CDC自动生成此输入与在线人物查询仍待接入。当前真实发布格式及冻结SQL证据继续使用。

## 文件

| 文件 | 用途 |
| --- | --- |
| backend/src/relationship_query/update/nightly.py | 配置校验、夜间窗口、发布状态、原子配置切换、恢复与历史保留 |
| backend/src/relationship_query/update/nightly_host.py | systemd启停、构建子进程、本机HTTP验收和图资源清理 |
| docs/examples/nightly-release-config-v1.json | 当前双服务器部署的路径及90分钟配置示例 |
| infra/nginx/relationship-map-nightly.conf | 页面维护503和API JSON维护响应，沿用8088及修复版静态目录 |
| infra/nginx/maintenance.html | 维护页面 |
| infra/systemd/relationship-nightly.service／.timer | 每日04:30任务及退出恢复 |
| infra/systemd/relationship-nightly-recover.service | 重启后的未完成任务恢复 |

httpx已声明为运行依赖，uv.lock保留原0.28.1及其他包版本，服务器使用既有项目虚拟环境。图构建及清理沿用data/nebula-lab/credentials.json的私有管理员凭据，查询服务沿用目标发布的GUEST身份。

## 一次更新的顺序

1. 校对当前真实发布、候选冻结文件摘要、人物／事实数量及来源身份。相同内容、月份和来源身份返回up_to_date。
2. 复制六份冻结输入到data/nightly/jobs/<任务ID>/release，目录700、文件600。保存旧query.env及任务记录，使用发布锁排除其他夜间Worker。
3. 写入维护标记，直接探测Nginx页面和API均返回503且API维护码正确。维护响应通过后停止查询服务，等待服务退出。
4. 子进程执行build_real_graph.py --build-prepared，构建日志单独保存。冻结输入、图收据、完整核验标记及独立SQL证明一致后，原子替换query.env中的发布目录。
5. 启动查询服务，核对health、meta的real模式、版本、基准月、人物数和事实数。通过后移除维护标记，登记published。
6. 清理本程序管理范围内过期发布。默认保留最近两份成功发布，额外保护当前配置、回退目录、最新任务候选和prepared_directory引用。保留任务记录、配置备份和日志，回收过期release目录、对应图空间及读取账号。清理失败单独登记，可重试。

## 运行入口

安装后配置位于/etc/relationship-map/nightly.json，来源路径按实例实际目录填写。准备目录包含prepared.json及其声明的五份冻结文件，可由现有build_real_graph.py --prepare-only生成。新目录由上游接入程序完成后再交给发布器。

先执行只读计划及状态检查。

```bash
cd /srv/relationship-map
backend/.venv/bin/python -m relationship_query.update.nightly plan \
  --config /etc/relationship-map/nightly.json
backend/.venv/bin/python -m relationship_query.update.nightly status \
  --config /etc/relationship-map/nightly.json
```

手动run会进入维护并暂停当前查询服务。scheduled模式按上海时区检查夜间窗口，窗口外返回outside_window。

```bash
backend/.venv/bin/python -m relationship_query.update.nightly run \
  --scheduled --config /etc/relationship-map/nightly.json
```

恢复入口读取持久任务状态，未完成任务按原配置和上一完整图回退。恢复在任何时间均可执行，以便服务器重启后恢复查询。

```bash
backend/.venv/bin/python -m relationship_query.update.nightly recover \
  --config /etc/relationship-map/nightly.json
backend/.venv/bin/python -m relationship_query.update.nightly prune \
  --config /etc/relationship-map/nightly.json
```

部署由用户逐步反馈推进。先上传源文件及更新锁文件，uv sync --project backend --python 3.12 --locked --no-dev，安装私有nightly.json并指定准备目录。备份现有Nginx站点，配置维护入口后nginx -t及reload，执行plan，再进行维护演练。完成实际验收后安装并启用nightly-recover.service与nightly.timer。具体安装命令按当前服务器反馈给出。

## 故障及资源边界

- 构建失败、超时、候选核验失败、启动失败或HTTP版本不符时，恢复原query.env并启动上一完整发布。准备阶段发现输入错误、已有人工维护或查询服务原本未运行时，记录相应失败。
- 任务中断后维护标记及阶段记录持久保存，下一次run先恢复旧任务，ExecStopPost及开机recover也会执行恢复。恢复失败时保留维护状态及错误码，继续使用恢复入口处理。配置备份或query.env被外部修改时，保留外部内容供核对。
- 私有状态为data/nightly/operation.json、jobs/<ID>/operation.json、query.env.before及build.log。来源角色配置及数据版本跟随真实构建输入，CLI输出和状态记录包含引用与聚合信息。
- 夜间正常路径在06:00前预留恢复预算。源服务、磁盘或图服务故障可能使恢复继续失败，任务会保留维护状态并报告NIGHTLY_RECOVERY_FAILED。实际可用性由健康核对结果确认。
- 单API停止后构建、恢复串行执行，图新旧空间及构建Python中间结果仍占资源。历史保留控制长期积累，内存峰值和大实体成本需继续观察。

Persistent配置及日历语法依据systemd文档，维护路由使用Nginx error_page及命名location。[systemd.timer](https://www.freedesktop.org/software/systemd/man/250/systemd.timer.html)、[Nginx error_page](https://nginx.org/en/docs/http/ngx_http_core_module.html#error_page)

## 实际验证

新增50项专项通过，涵盖发布、无变更、维护入口错误、构建／启动／核验失败、进程中断恢复、恢复失败重试、超时预留、并发Worker、外部配置变更、来源迁移、历史保留、共享资源保护、构建子进程和HTTP适配。完整后端617通过／247跳过，1项既有Starlette依赖弃用提示。Ruff／Mypy及离线锁文件校验通过。

原生演练使用已封存6525专家／25239事实的真实输入，将基准月推进到202612模拟新版本。独立API、Nginx1.18及本机NebulaGraph完成维护503、新图构建切换、1至4跳、模拟构建失败后的实际回退，以及中断后的实际恢复。一次发布观察119.283秒。systemd操作由本机子进程生命周期适配模拟，Ubuntu22.04／systemd249另行完成三个unit的verify及04:30上海时区日历解析。

原生清理适配实际创建并回收一个独立空间／账号通过。两次测试创建的图资源及Nginx容器均已回收，原有真实图保留，native-v1发布材料已退役。材料位于data/nightly-release/native-v1，维护页桌面／手机截图已查看。

上述测试为本地独立演练，服务器实际systemd启停、重启恢复、90分钟边界及源CDC供给仍待部署验收。
