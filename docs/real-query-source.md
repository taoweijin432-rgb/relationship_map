# 真实图查询与展示接入

2026-11-12，当前查询规则对应主架构v0.44，后续读取与更新评估见v0.51，计算字段位置补充至v0.52，真实来源接入记录始于v0.42。

## v0.52 已入图的计算属性

现有worked_at边已经保存任职起止月份、在职标记、职位及经历键，studied_at／studied_major保存教育起止月份、学历、统招原值及经历键。事实Rank沿用graph_edge_mapping.id。具体日期按YYYYMM月份精度入图，原精确值留在源MySQL及封存输入。人物来源id、source_system及serial_number用于SQL回查，姓名仍由SQL提供。

本轮只读核对真实封存graph-plan，12272条任职、7606条学校、5361条专业事实具有上述属性，未重新访问远程图。图中company_overlap还保存计算后的交集月份和左右事实Rank。后续字段更新按联动CDC读取对应经历并后台更新候选图，人物在线MySQL展示和自动发布待接入。以下v0.48保留前轮按需缓存提案，最新低频更新建议见主架构v0.51。

## v0.48 后续按需关系缓存目标

用户明确首次关系查询读取必要MySQL数据、计算后写图，有效缓存命中后复用，人物展示在线回MySQL。源实体／映射库单源CDC推进关系版本使旧缓存失效，后续访问再算。缓存需记录版本与完整覆盖，多跳逐层补齐。方案见主架构v0.48，在线MySQL及缓存读写尚待实现。以下冻结SQL／预计算图仍为当前部署的实际读取方式。

## 2026-11-12 在线人物展示要求

用户明确关系查询时人物展示应在线读取来源MySQL。当前测试部署仍使用/srv/relationship-map/data/releases/test-20261111-v1/source.sqlite提供人物、经历及证据装配，Nebula空间relationship_lab_sync_7bb2f3daef15提供关系候选及路径。来源采集按有效权威映射引用选取人物与经历必要列，发布6525专家／25239事实，配套规范化输入保存于source-snapshot.json。

graph_edge_mapping由同事维护人物原经历字段与标准实体的映射。项目据此构建经历事实边，再预计算同公司／同期／同校／同专业人物关系。前期冻结SQL用于真实图验证和成对版本核对。后续人物展示按来源身份和原主键批量回MySQL，并核对背景筛选、分页、事实依据、导出与删除状态的时点处理。当前为读取链路核对与要求记录，在线回源改造及测试待执行。以下保留本机接入验收历史。

同专业查询现提供“要求同校”可选前提，前端新查询默认勾选，按现有同校人物关系逐段筛选，学校及专业可来自不同教育行。API默认false。数据及图发布继续使用下面的真实版本，规则验收位于data/school-prerequisite/run-v1。

## 当前页面与数据

当前页面为 <http://127.0.0.1:5173>，API文档为 <http://127.0.0.1:8000/docs>。当前服务实际返回data_mode=real、版本real-2a106af85a3330dba3c2-202611、基准月202611，支持最多4跳的单人物关联查询。

| 数据 | 当前数量 |
| --- | --- |
| 专家人物 | 6525 |
| 标准实体 | 12801 |
| 经历事实 | 25239 |
| 图中人物关系证据 | 331783 |

图空间为 `relationship_lab_sync_2d1b24919065`，人物与履历读取 `data/real-graph/run-v1/build-v1/source.sqlite`。图查询通过该发布的GUEST账号执行。姓名从SQL装配到页面，人物图节点保持source_system与serial_number。

默认源配置 `data/frontend-source.json` 的store为 `real-graph/run-v1/build-v1`，正常执行 `bash scripts/dev.sh` 会按此配置启动。显式指定来源环境变量时按该来源启动，真实源也可通过 `RELATIONSHIP_NUMERIC_RELEASE_STORE` 指定本次构建目录。切换前配置保存于 `data/real-query/run-v1/previous-frontend-source.json`。

## 读取与版本核对

RealGraphRepository识别real-graph-build-v1，启动核对准备清单、源文件摘要、规范化数据摘要、图收据、独立SQL证据校验结果、SQL读模型标记及行数。随后以只读账号完整回读图摘要，核对该图与配套SQL的版本。实际HTTP验收的启动观察为19.476秒。

启动完整核对使用独立120秒预算。普通查询沿用原请求预算。开发启动为完整核对保留150秒等待，浏览器测试服务器保留180秒启动等待。

请求前后检查固定文件的设备、inode、大小、mtime和ctime。文件修改、替换或移除触发SOURCE_VERSION_MISMATCH，重新载入时再次执行完整校验。源SQL通过只读URI连接。

Metadata、健康和错误响应支持真实模式。页面环境与经历页脚按实际模式显示，JSON携带real，CSV与PNG标记真实数据，下载文件名使用relationship-real前缀。图节点长机构名称最多三行换行，详情数据保留完整名称。

## 实际验证

| 项目 | 结果 |
| --- | --- |
| 正常HTTP入口 | 人物筛选、1至4跳、四跳逐段证据、对比、两人路径、展开、导出及错误标识通过 |
| 当前5173真实浏览器 | 3项通过，覆盖真实模式、四跳画布、JSON／CSV／PNG、公司筛选分页及手机详情 |
| 桌面、手机、导出截图 | 已查看 |
| 完整旧演示浏览器 | 37通过、25跳过 |
| 完整后端 | 531通过、247跳过，含新增发布读取保护8项 |
| 旧数字来源HTTP | 只读核对通过，仍返回mock及262人 |
| 旧UUID真实MySQL／图专项 | 6通过、3跳过 |
| 静态及构建 | Ruff、Mypy、前端格式、类型与构建通过 |

运行材料位于 `data/real-query/run-v1`。

- `api-validation.json` 保存真实HTTP验收与启动观察。
- `live-meta.json` 保存切换后当前8000服务元数据。
- `live-browser-v2` 保存最终当前5173桌面、手机和PNG导出截图。
- `legacy-browser-v2-final` 保存最后一次旧演示回归材料。
- `legacy-numeric-validation.json` 保存旧数字源HTTP核对。

临时测试服务18014／15184及18015／15185已回收。正常8000／5173开发服务持续运行。GraphCanvas构建分块仍约1418kB，保留既有体积提示。

真实HTTP复核入口如下，report使用新的输出路径。

```bash
backend/.venv/bin/python scripts/validate_real_query_api.py \
  --source data/real-graph/run-v1/build-v1 \
  --report data/real-query/<新目录>/api-validation.json
```

浏览器复核通过当前页面运行。

```bash
cd frontend
RELATIONSHIP_REAL_BROWSER=1 npm run test:e2e -- real-data.spec.ts
```

## 数据范围与日期观察

本次图的权威映射全部来自专家库。简历关系需要上游交付对应映射。既有240条隔离、304个零日期规范化、源采集证书状态及配对快照依据见 [真实图构建记录](real-graph-build.md)。

页面核对发现源数据包含1905年日期。本次有效图中，涉及该年日期的任职事实3405条、学校1258条、专业1061条，统计在source-date-observations.json。页面按源值展示，日期准确性需要上游核对。

当前查询绑定已冻结的图和SQL版本。源库后续变更需要通过下一轮构建与发布进入查询，持续CDC调度、完整简历覆盖及生产并发容量继续待验收。
