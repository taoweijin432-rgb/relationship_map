# 人物在线回源与夜间自动输入

版本 v1.2，2026-11-13，对应主架构v0.59.4。当前部署状态见本节及主方案。

## v1.2 当前实际运行

应用服务器121.43.176.65已部署人物在线MySQL读取和夜间双源自动输入。实际API的person_display为mysql-live，关系版本为real-921e1ee2e6476b0925bb-202611，当前发布6711专家／27715事实。2026年11月13日首次04:30定时任务成功发布，全流程约286秒，服务及定时器正常。

人物候选按姓名或业务编号前缀搜索，查询选择值和后续详情按系统人物ID定位。最终公网验证覆盖真实人物选择、四跳、中间人物证据、分层聚焦、PNG导出及手机触摸。当前前端目录为dist-layout-v059-label-fix。在线展示与版本化事实的读取职责沿用下文“当前实现”，时间与结果以[主方案](query-system-architecture.md)最新记录为准。

私有配置为/etc/relationship-map/mysql-sources.json和mysql.env，当前分别绑定实体／映射及人物／经历来源。配置支持两个逻辑角色引用同一物理连接。正式端点迁移按新的配套发布基线管理。

## 历史部署与开发验证记录

## 服务器逐步验收反馈

用户反馈26文件已安装，私有配置脚本连接核验及配置保存成功，query drop-in和新版nightly unit解析、daemon-reload通过，mysql.env权限600 root。短时维护重启后实际8088/meta返回person_display=mysql-live，旧完整图版本real-2a106af85a3330dba3c2-202611健康。p:expert:100／1000／1002的姓名、城市、职位及业务编号与MySQL原表逐字段核对通过。

实际systemd瞬态任务prepare-input返回input_prepared并以success／0退出。新输入data/nightly/inputs/66d5547aff0d4123bb75c39d77e9c54f/prepared，候选real-24561d7e35cc7e059005-202611，6525人物／25241事实，运行观察66.465秒、CPU9.916秒。用户随后恢复timer，下次2026-11-13 04:30 CST；nginx／query／tunnel均active，timer与recover均enabled，真实API健康。部署、在线人物及输入验收完成，首次完整定时构建及发布待夜间反馈。定时任务届时重新采集数据库，最终版本取决于当时来源内容。

## 当前实现

人物展示使用LiveRealGraphRepository及MySQLPeople，从配置的person_source按来源和原主键批量读取。姓名、城市、职位、业务编号来自当前MySQL，覆盖人物选择、相关人物、详情、对比、证据、图标签、1至4跳中间人物、两人路径、展开和导出。MySQL连接池为5个连接、最大溢出0，单批最多200个人物ID，启用只读会话、TLS、连接／读取／SQL执行超时。人物关键词沿用既有ASCII大小写与Unicode匹配规则，选择范围限定当前已发布人物。空关键词直接使用发布成员分页，已发布人数为0的来源跳过关键词扫描。

关系、筛选及证据经历继续绑定同一发布的图和SQL事实，人物展示独立在线更新。统计数量表示已发布成员和事实数量。原表人物删除／失效立即退出选择和列表，详情返回404，过期图链包含该人物时返回PERSON_SOURCE_CHANGED，等待夜间图更新。源库故障返回PERSON_SOURCE_UNAVAILABLE。API的meta新增person_display，在线配置时为mysql-live，storage继续描述已发布事实的SQL读模型。

发布的人物来源host、port、database和server_uuid均在启动时校对。当前实体和人物分别引用两个连接，合源时两个逻辑角色可以引用同一物理连接。正式端点迁移需要配套建立新发布基线，再切换在线来源。

## 夜间自动更新

当前采用每日04:30双源全量只读采集和版本化发布，适配已确认的低频更新及当前映射范围。该实现完成自动获取新数据和重算发布。此前单源CDC提案作为增长后的增量优化路线，容量扩大时继续评估采集时长、内存峰值和热点关系成本。

NightlyConfig新增source_config_file、input_timeout_seconds和insecure_source_tls。启用后，每次run先采集实体／映射及其引用的人物／经历，准备新的real-graph-plan-v1，再执行原有维护、停止API、建图、核验、切换和恢复。采集与准备发生在维护标记写入之前，采集失败保留当前查询服务。整次自动任务共用04:30至06:00窗口和恢复预算，输入阶段默认最多30分钟，构建阶段按剩余时间收缩。

两个来源各使用独立RR只读一致性快照，记录来源身份、采集时间及TLS指纹，运行条件沿用上游数据准备就绪。跨库配套状态通过既有引用、归属和日期规则校验，两次快照的业务时点仍需上游发布协调。当前合源配置也保留两个逻辑读取会话。

自动采集使用--relation-only，跳过人物name、city和job_name原列。沿用既有投影的非空name契约，封存文件中姓名为固定占位“人物”，城市和个人职位字段为空。任职／教育关系计算字段及业务身份编号继续封存。新发布标记person_display=mysql-live，缺少在线配置时API启动明确失败。历史采集、旧SQLite发布及备份中的展示字段需要按后续数据保留安排处理。

输入保存在data/nightly/inputs/<ID>，私有目录700、文件600，input.log保存聚合进度及错误。保留最近两次输入，并额外保护当前选中输入。已复制到发布任务的输入受既有版本回退和保留机制管理。来源内容、基准月、来源身份及展示模式一致时跳过图构建，姓名等展示字段变化通过在线读取生效。

## 服务器部署顺序

服务器现有v0.56定时器已启用，当前业务人物展示为SQLite来源。新补丁需要完成以下步骤，按用户终端反馈逐步执行。

1. 校验补丁并暂存，暂停relationship-nightly.timer，检查夜间任务当前处于空闲状态。
2. 私有备份本次覆盖的程序文件、mysql-sources.json、nightly.json、query.env、现有unit及drop-in，安装源码。
3. 执行配置脚本，通过隐藏输入填写两处数据库密码。脚本只读核对来源及字段后，备份并原子写入三份600配置。

```bash
cd /srv/relationship-map
backend/.venv/bin/python scripts/configure_server_mysql.py --insecure-tls
```

当前测试源沿用已核对的TLS加密及证书指纹，--insecure-tls关闭证书链校验。匹配CA配置后可使用默认校验模式。mysql-sources.json引用密码环境变量，实际凭据保存/etc/relationship-map/mysql.env。

4. 安装infra/systemd/relationship-query.service.d/20-mysql-source.conf到对应/etc/systemd/system目录，安装更新后的relationship-nightly.service。两项通过EnvironmentFile读取mysql.env。daemon-reload后校验unit。
5. 短时维护窗口中重启relationship-query.service，核对API完整启动、meta.person_display=mysql-live及当前图版本。读取少量实际人物原表字段，与API人物详情逐字段比较。失败时恢复drop-in和配置备份，重启并核对原服务后清除本次维护标记。
6. 通过独立瞬态任务实际执行自动输入准备并核对聚合结果。

```bash
systemd-run --unit=relationship-nightly-input-check --collect --wait --pipe \
  --property=WorkingDirectory=/srv/relationship-map \
  --property=EnvironmentFile=/etc/relationship-map/mysql.env \
  /srv/relationship-map/backend/.venv/bin/python \
  -m relationship_query.update.nightly prepare-input \
  --config /etc/relationship-map/nightly.json
```

prepare-input持有同一发布锁，返回input_prepared和发布计划，查询API继续服务。图发布由run入口执行。

7. 恢复并核对定时器，04:30首次完整发布后核对phase=published、meta的新版本与统计，以及真实单跳／多跳、证据、路径和导出。开机恢复及ExecStopPost继续使用原有recover入口。

## 验证记录及待验范围

新增29项回归，后端646通过／247跳过，1项既有Starlette弃用提示。Ruff和Mypy通过。回归涵盖在线字段刷新、分页、未发布人物、删除、原表失联、图中间人物回调、API装配、双源及合源配置、源采集失败、输入保留与凭据文件转义／回退。

本机隔离MySQL8.4 TLS、Nebula3.8、Nginx1.18与独立API使用5人物4跳模拟链实测，人物更名立即展示，人物展示变更时关系构建跳过。选择、搜索、详情、对比、证据、路径、展开和导出均取到在线人物，多跳中间人物通过。原经历更新后自动采集、准备、新图核验、发布及API恢复通过，一次观察29.434秒。人物删除后详情404、旧链明确失效，源库停机后人物请求503、采集失败保持API运行，通过。配置脚本实际完成TLS来源核验及600凭据文件写入。测试资源已回收，材料data/live-mysql/native-v4已退役。

以上原生演练的服务启停由本机子进程适配模拟。隔离Ubuntu22.04中三个夜间unit及API的EnvironmentFile drop-in解析、04:30上海时区日历解析通过。服务器在线模式激活、人物字段比对、实际自动输入和定时器恢复已取得用户终端反馈，首次定时完整发布继续待验。大规模原表、热点查询、并发及全量采集容量继续待验证。本轮直接SSH返回Permission denied (publickey,password)，服务器步骤沿用用户当前终端执行。
