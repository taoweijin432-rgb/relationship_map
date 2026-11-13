# 项目上下文与架构维护

本项目负责消费同事交付的归一数据，实现人物关系查询与展示。人物身份、跨库重复及关联问题由数据库相关人员处理；公司、学校、职位归一由上游负责。

## 持续维护的方案

- 主方案为 `docs/query-system-architecture.md`，后续工作先阅读其中的已确认条件和维护约定。
- 用户要求保存并持续维护此方案。收到新数据表、样本或相关运行条件后，重新评估并在同一文件更新，保留版本、日期、决定依据和修订记录。
- 原始两份 Word 文档只用于理解设计思路，其表结构和部署描述不能作为当前系统的权威依据。
- 当前已知来源规模是专家不足 10 万、简历超过 200 万且增长中；这不等于去重后人物数量。
- 两个查询入口均需要：从人物查相关人物，从公司、学校、职位筛选人物。
- 后端当前按 Python 方向设计，技术组合、索引和性能目标均为待验证建议。
- 新数据到位后，按主方案的重评步骤核对数据契约、统计分布、业务负载与现有基础设施，再修订选型和代码架构。
- 不把模拟数据、小样本测试或未执行的检查描述成实际生产验证结果。

## v0.59.4 提测源码基线与文档整理

- 用户确认执行提测准备前4项，范围为Git忽略规则及文件审核、Git源码提交与标签、部署一致性核对、README及运行入口文档校正。main仓库已初始化，采用已有Git身份，提测标签qa-20261113-01，实际提交标识由Git读取并关联私有验证记录。
- 补充frontend/dist-*/、.env.*及私有凭据／密钥文件忽略规则，保留环境示例。待提交文件模式扫描命中项经核对为远程MySQL单测占位连接及摘要／实验标识片段，依赖锁文件保留。真实快照、运行凭据、验证材料和构建输出按既有data及产物规则管理。
- 根据初始源码包、HTTP保存修正、v056／v057／v058／v059补丁及最终GraphCanvas修正重建149个运行文件摘要，本地逐项一致。直接SSH认证失败后向用户提供只读校验清单，用户已反馈服务器149个运行文件全部通过。随源码清单docs/releases/qa-20261113-01.sha256，私有材料data/qa-baseline/20261113。
- README首页更新为真实测试入口、现行查询与展示、私有运行配置、夜间全量发布及本地模拟启动，既有作者内容保留为折叠历史记录。夜间、在线输入及部署文档补充当前状态，主方案v0.59.4维护决定。代码变更范围为忽略规则与文档准备，业务行为沿用已部署版本。

## v0.59.3 标签修正版已部署并完成公网复验

- 用户反馈Nginx切换至dist-layout-v059-label-fix，入口index-B_uaB6X5.js及实际新夜间版本／mysql-live校验通过；nginx／query／tunnel均active，nightly timer下次2026-11-14 04:30 CST。
- 助手直接访问实际公网修复版，未替换静态资源或候选列表，验证姓名／业务编号搜索、完整ID无候选、人物1000全部共同经历四跳20人／62节点／64边及无截断、分层画布、真实Canvas点击聚焦与恢复、标签开关、PNG下载文件头、390窄屏触摸详情均通过，页面错误为空。实际桌面聚焦与手机截图已查看，人物姓名单行侧置及关系文字按需显示已在线生效，材料data/graph-layout-v059/public-label-final-20261113。
- 本次姓名／业务编号搜索、分层图及聚焦标签修正的服务器部署与指定真实样例公网验收完成；验证范围为当前6711专家／27715事实发布和指定四跳样例，既有大规模容量边界继续按主方案后续验证。单文件修正验证记录server_deployed=true，原包摘要保持原交付记录。

## v0.59.2 前端上线与聚焦标签补充修正

- 用户反馈Nginx切至dist-layout-v059、入口index-wEBlF0mC.js校验成功，meta为新夜间版本real-921e1ee2e6476b0925bb-202611／mysql-live。nightly timer恢复，下次2026-11-14 04:30 CST，nginx／query／tunnel均active。
- 助手直接公网浏览器实际验证通过，覆盖姓名／业务编号选择、完整ID无候选、人物1000全部共同经历四跳20人／62节点／64边、分层属性、真实Canvas点选聚焦及恢复、标签开关、PNG文件头与下载、390窄屏触摸详情，页面错误为空。材料data/graph-layout-v059/public-20261113。
- 实际聚焦截图发现四跳时自动显示的全部经历文字及实体名拥挤，继续修正GraphCanvas.vue，聚焦默认显示单行人物姓名并侧置，实体名悬停显示，关系文字由悬停／单条边选中／全部开关控制。8项相关浏览器回归、类型／构建通过，修复版以本机静态资源调用实际公网API的相同交互再次通过，截图已查看，材料label-preview-20261113，此预览使用本机修复产物，服务器修正待部署。
- 单文件补丁data/test-server-deployment/20261113/GraphCanvas-label-fix-v059.vue，原SHA256为7d5c39566cc871221c5521e1c9b1fa99c3e4633b5eda126d068b71f7140ecc30，新SHA256为9a3d513d55c8bceca637ca884b634e704b983857ad8af20e75e9c4b33f680a05。后续上传／校验、备份该源码、服务器构建独立候选并切Nginx，再复核实际公网；当前服务可用，尚有此项视觉修正待完成。
- 用户反馈/tmp/GraphCanvas-label-fix-v059.vue的SHA256校验OK。下一步核对现有源码为7d5c3956、备份至before-layout-v059-wc43kvnc/GraphCanvas.before-label-fix-v059.vue，原子替换单文件并在服务器构建frontend/dist-layout-v059-label-fix候选目录，再按反馈切换和公网复验。
- 用户反馈旧源码与修正文件校验均OK、源码备份替换完成，服务器vue-tsc／Vite候选构建通过，耗时12.26秒，目录dist-layout-v059-label-fix，入口index-B_uaB6X5.js、图组件GraphCanvas-6K1ga1Xw.js，与本机修复产物一致。下一步合并dist-layout-v059旧assets至候选、备份Nginx当前配置、切换静态根并核对资源及实际API版本，最后公网视觉复验。

## v0.59.1 首次夜间自动发布成功

- 用户提供2026-11-13服务器journal，nightly于04:30:00开始，04:34:45返回published，04:34:46成功退出，全流程约286秒；版本real-921e1ee2e6476b0925bb-202611，发布data/nightly/jobs/db0c33dfb59a46539da5d00a29ff617e/release，退出恢复检查idle、cleanup cleaned／removed 0。该时间为全流程日志窗口，具体维护阶段时长未据此推断。
- 助手实际只读公网health及meta均成功，状态ok／real、同一新版本、person_display=mysql-live、6711专家／0简历、14355实体／27715事实、最多4跳及nebula-materialized。首次实际定时发布和新版本在线可见已确认，业务查询专项与容量仍按具体用例验证。分层布局v0.59源码安装及服务器构建输出尚待用户反馈，激活程序应读取届时实际新版本，保留已发布夜间数据配置。

## v0.59 分层布局与证据链聚焦

- 用户已反馈relationship-map-layout-v059.tgz上传至应用服务器/tmp并SHA256校验OK，摘要64b977fb464099717a3960a45712ece52d0656724de22e19ebab5f7650c55a45。包含15个源码／测试／文档文件与layout-v059.sha256清单。下一步暂存校验并备份现有文件及Nginx站点，安装、服务器构建与激活继续待反馈。
- 用户已反馈暂存/tmp/relationship-map-layout-v059.3inhsk6x、备份/srv/relationship-map/data/deployment-backups/before-layout-v059-wc43kvnc，15文件校验及备份完成。下一步暂停nightly timer并确认任务未运行，安装15文件，在服务器构建frontend/dist-layout-v059候选目录，常驻API重启及Nginx切换随后按反馈执行。
- 用户2026-11-13反馈15文件安装完成、nightly timer已暂停，服务器vue-tsc／Vite构建成功，frontend/dist-layout-v059入口index-wEBlF0mC.js、样式index-1B7wbL_X.css，GraphCanvas-T-mJisnl.js，与本机验证产物一致，耗时11.89秒，既有体积提示。下一步短时维护重启query、按当前实际夜间版本验收在线展示及姓名／业务编号搜索，再切换Nginx候选静态目录，恢复timer。
- 用户反馈后端维护重启和搜索验收通过，name返回50、serial_number返回1，backend_activated=true；实际版本real-921e1ee2e6476b0925bb-202611、mysql-live、6711人物／27715事实，维护入口已解除。下一步将Nginx根由dist-http-save-v1切换至dist-layout-v059，合并旧assets兼容已打开页面，验证新入口／样式／图组件及代理meta，再恢复timer。前端激活及公网浏览器验收待反馈。
- 用户确认按跳数分层＋选中路径高亮＋关系文字按需显示。新增graphPresentation.ts，人物层级优先采用已返回连接摘要，实体分支按邻接层安排，扩展节点按当前画布最短距离补充，断开分量分开排列。环半径按人数及标签间距扩展；两人路径固定间距横排。
- App将已取得证据的逐段事实ID传入GraphCanvas，点击人物时仅高亮画布内对应证据边，其余淡化，可查看全部关系。初次打开保留全图。关系文字默认悬停／选中可见，保留显示全部开关。缩小时收起普通姓名并提示放大，选中／悬停姓名保持可见；节点、边和文字具备最小屏幕显示尺寸。此改动在前端使用已有响应装配。
- 完整浏览器42通过／26跳过，新增4项覆盖四跳层级、重复边／环／孤立节点、100节点间距与桌面／手机、真实Canvas点选聚焦及恢复、PNG导出，既有触摸取证及路径回归通过。前端类型／构建／格式检查完成后与前轮v0.58.3共同打包，服务器尚待部署。既有大图组件体积提示保留。
- 本机新前端实际调用测试服专家1000全部共同经历四跳，返回20人、62节点、64边、graph_truncated=false，页面错误为空，桌面／手机截图已查看。该专项目标选择框固定为人物1000测试入口，关系及证据由实际API读取，未作为人物候选搜索验收。材料data/graph-layout-v059，实际服务器前端激活仍待执行。主方案v0.59维护。

## v0.58.3 人物搜索保留姓名和业务编号

- 用户要求去掉需要完整系统ID的人物搜索方式。在线MySQL和共享SQL仓储的候选检索均移除人物ID匹配，仅按姓名或业务编号前缀搜索，前端参考人物提示统一为“搜索姓名或业务编号”。人物选择值继续使用系统ID，详情、关系、路径及已保存条件通过ID定位人物。
- 已有在线仓储与HTTP回归覆盖姓名／业务编号命中、系统ID无候选、空词候选及按ID详情读取，真实浏览器用例改为通过业务编号或姓名选择人物。后端651通过／247跳过，Ruff／Mypy与前端类型／生产构建／改动文件格式检查通过，既有Starlette弃用及图组件体积提示各一项。当前为本机源码改动，服务器上传与激活待执行。主方案v0.58.3维护。

## v0.58.2 人物选择候选范围核对

- 用户反馈找关联的人中人物选择数量少，要求解释。源码及公网核对frontend api.people固定limit=50，后端suggest最大50，当前选择框无游标／滚动加载下一批。空关键词公网返回50，已发布图6525专家／0简历，person_display=mysql-live。
- 名称、业务编号、完整人物ID采用前缀匹配，当前Root限定已发布有效人物。公网q=p:expert:2返回50，q=p:expert:1000返回1，q=1000返回0，确认纯数字ID匹配缺口。本轮为原因核对，选择范围、分页和匹配功能改造待用户后续要求。主方案v0.58.2记录，服务器查询优化仍为v0.58已部署状态。

## v0.58.1 查询预算修复已部署并公网验收

- 用户反馈短时维护重启完成，常驻HTTP人物1000／全部共同经历／20人分页，3／4跳1116.07／3210.66ms、200、20人、graph_truncated=false，维护标记解除。timer恢复，下次2026-11-13 04:30 CST。
- 助手独立公网读取页面及meta通过，person_display=mysql-live、关系版本real-2a106af85a3330dba3c2-202611。3／4跳同条件1201.16／3310.77ms、200、20人、画布完整，连接跳数符合请求。材料data/graph-budget/public-after.json，均为单次顺序观察。主方案v0.58.1及预算报告v1.1维护。
- 当前指定条件预算问题已部署验收。首个完整夜间自动建图及切换、大规模并发和其他热点组合继续待验。在线人物和夜间双源输入沿用v0.57实现，现有SSH密钥认证失败，服务器操作由用户终端逐步执行。

## v0.58 查询预算优化实现记录

- 用户报告人物1000、全部共同经历、3／4跳预算错误。公网20人分页1至4跳692.2／845.4／4702.0／2129.1ms观察，前三项200，四跳503 GRAPH_UNAVAILABLE。本机同图复现四跳-1005及80%内存水位拒绝，服务器原生详情待新日志核对。
- 多跳普通召回改原生GO 1 TO N和终点去重，游标只筛最终候选；同专业带同校前提走逐层终点折叠。最短链每终点保留最小前缀，维持最短／字典序／简单链语义。在线分页同时消费探针，候选充足时一次召回。预算提示区分时间／图读取／SQL，增加原生错误及指纹、图和MySQL分段计时。
- 线上多跳预算5秒、图返回20000行／256RPC。冻结真实图人物1000的20人四跳2059.49ms、50人2395.90ms单次观察通过，1至4跳20／50人结果和最短链与SQL BFS一致。完整5696人物及全部最短链在独立30秒离线预算核对通过，19.316秒、7RPC／11394行。真实同校前提1至4跳另测通过，后端651通过／247跳过，原生8人链21通过／1跳过，Ruff／Mypy通过，测试图／账号已回收。
- 当前服务器v0.57.1仍为原查询执行，本轮补丁待上传、安装及服务器在线MySQL同条件验收。新增scripts/profile_relation_queries.py供systemd瞬态诊断，输出聚合计数和阶段耗时。主方案v0.58、docs/graph-query-budget-fix.md及data/graph-budget记录，大规模并发待验。
- 用户已反馈12文件安装完成，备份data/deployment-backups/before-query-v058-frxouqbj，timer按步骤暂停。服务器独立诊断进程在mysql-live及原real-2a106af85a3330dba3c2-202611图版本下1至4跳均通过，20人分页467.01／579.57／1102.88／3238.41ms，MySQL各3次约295ms，图RPC19／31／39／41次。初始化36444.04ms，瞬态任务success／0，总42.366秒。下一步短时维护重启常驻query，并用实际HTTP入口核验后恢复timer。

## v0.57.1 在线回源和自动输入已部署

- 用户反馈v0.57在线人物、双源自动采集和输入准备验收通过后，timer已恢复，下次2026-11-13 04:30 CST。nginx／relationship-query／relationship-graph-tunnel均active，nightly timer与recover均enabled，API status=ok／real、当前关系版本real-2a106af85a3330dba3c2-202611。
- 实际API的person_display=mysql-live，3位人物已与MySQL原表字段匹配。实际自动输入为6525人物／25241事实，单次准备66.465秒。每天04:30重新全量读取两库、准备并衔接停服发布，总窗口90分钟，首个完整新流程夜间构建／切换待反馈。候选版本按届时来源确定。
- 历史快照与备份继续按已确认保留策略保留，关系事实和筛选读模型绑定图版本。实际服务器结果为用户终端反馈，现有SSH密钥认证失败。主方案v0.57.1、在线接入说明v1.1、部署说明v1.9维护当前状态。

## v0.57 在线人物与夜间自动输入实现记录

- 用户要求把在线人物回MySQL和自动输入落实服务器。新增live_people.py，批量在线读取姓名／城市／职位／业务编号，覆盖所有人物展示及MaterializedReader中间人物；限定已发布身份、删除立即隐藏，失效图链503、人物源故障503，meta新增person_display。事实／背景筛选及统计仍按冻结发布。
- 夜间新增source_config_file、input_timeout_seconds及insecure_source_tls，每日04:30先全量只读采集、prepare-only，再衔接停服发布，全部阶段共用90分钟预算。当前低频来源采用夜间全量，CDC作为后续增量优化路线。双源各自RR快照，业务配套沿用上游就绪条件，跨库时点仍需协调。
- --relation-only跳过人物姓名／城市／个人职位原列，固定姓名占位“人物”满足旧契约，关系计算经历和业务编号保留。自动输入默认保留最近两份并保护当前引用，新图标记mysql-live且要求API配置在线源。历史冻结文件及备份中的展示字段保留待后续数据保留安排处理。
- scripts/configure_server_mysql.py通过隐藏输入配置私有mysql.env、来源引用和夜间参数，先只读核验端点／UUID／列，再备份及原子写配置。新增query的EnvironmentFile drop-in及更新nightly unit。新增prepare-input供部署时实际自动采集验收。
- 后端646通过／247跳过，新增29项，Ruff／Mypy通过。本机隔离MySQL8.4 TLS／Nebula3.8／Nginx1.18及5人物4跳链原生联调通过，在线刷新、删除、8类展示入口、自动新图发布、源故障及真实凭据配置均通过，一次自动发布29.434秒；systemd启停用本机子进程适配。临时图／账号／容器已回收，data/live-mysql/native-v4退役，大规模容量待验。
- 服务器仍为v0.56状态，timer已启用但人物展示仍SQLite，当前补丁待上传、配置和重启。直接SSH使用现有密钥返回Permission denied (publickey,password)，继续用户终端逐步部署，首次实际新功能及定时发布待反馈。主方案v0.57、docs/live-mysql-and-nightly-input.md维护。
- 用户后续反馈nightly任务inactive／dead，timer已按步骤暂停，v0.57补丁已上传校验并备份。暂存/tmp/relationship-map-live-v057.QnsOLS，备份/srv/relationship-map/data/deployment-backups/before-live-v057-xrlrxwz6，下一步安装26个源码／模板文件并运行私有凭据配置脚本，再激活query drop-in与新版nightly unit。服务器在线模式仍待实际重启验收。
- 用户反馈26文件安装完成，configure_server_mysql.py --insecure-tls返回configured=true、person_display=mysql-live、automatic_nightly_input=true、certificate_verified=false，配置备份data/deployment-backups/before-live-mysql-gyp1cew5，凭据/etc/relationship-map/mysql.env。这是连接核验和配置保存结果，API仍待安装EnvironmentFile drop-in并重启激活，timer继续按部署步骤暂停。
- 用户反馈query drop-in与新版nightly unit已安装、verify及daemon-reload完成，query的EnvironmentFiles为query.env及mysql.env，DropInPaths指向20-mysql-source.conf，nightly引用mysql.env，私有文件600 root。下一步短时维护重启query并强制核验person_display=mysql-live，自动输入与定时器恢复继续待验收。
- 用户反馈短时维护激活脚本成功，维护入口解除，实际8088/meta返回person_display=mysql-live、real-2a106af85a3330dba3c2-202611、6525专家／25239事实、4跳及nebula-materialized。人物在线模式已由服务器API确认，关系仍按原完整发布。下一步实际人物原表字段比对、prepare-input自动输入验收及恢复timer，首次完整v0.57夜间发布待运行反馈。
- 用户反馈p:expert:100／1000／1002三位人物姓名、城市、职位及业务编号与原MySQL逐字段核对通过。实际systemd瞬态任务prepare-input成功，输入data/nightly/inputs/66d5547aff0d4123bb75c39d77e9c54f/prepared，候选real-24561d7e35cc7e059005-202611，6525人物、10289公司／1821学校／693专业、25241事实（任职12274／学校7606／专业5361），聚合准备66.465秒、CPU9.916秒观察。下一步恢复timer并核验健康，04:30运行将重新采集源库，最终候选版本按当时输入确定，首次完整v0.57定时发布待反馈。

## v0.56.2 夜间定时器已启用

- 用户反馈relationship-nightly.timer与relationship-nightly-recover.service均enabled，恢复任务Result=success、ExecMainStatus=0，下次触发2026-11-13 04:30 CST。源码、双源／夜间配置、输入准备及Nginx维护入口已按逐步终端反馈完成，维护503与恢复200通过。
- 当前发布仍为real-2a106af85a3330dba3c2-202611。首次定时运行将处理手动准备的nightly-input，新候选real-32c7c46af8287ce504df-202611，6525人物／25241事实。完整图构建、切换和业务验收待用户夜间运行后反馈。持续MySQL／CDC自动输入供给与在线人物查询仍待接入，同输入后续将跳过构建。主方案v0.56.2记录实际进度。

## v0.56.1 夜间更新包安装反馈

- 用户反馈应用服务器/tmp/relationship-map-nightly-v056.tgz校验OK，SHA256为772cd56fd005c64f9e54b6cceb1a03b682269023e64c779034693756e5d925f1。暂存/tmp/relationship-map-nightly-v056.pAWslW，备份/srv/relationship-map/data/deployment-backups/before-nightly-v056-q7zy430n。
- 用户反馈27文件已安装，uv sync --locked --no-dev通过，35包兼容，nightly命令五入口帮助正常。下一步创建服务器私有双源及夜间配置并验证，维护路由、定时器、实际发布和回退继续待验收。业务仍使用原冻结发布，真实CDC输入和在线人物MySQL待接入。主方案v0.56.1记录本次用户反馈。
- 用户后续反馈双源与夜间配置校验通过，04:30／Asia/Shanghai／90分钟／保留2份，status为idle。应用服务器到两源只读会话均成功，实体角色所需6表、人物角色所需6表全部可见，server_uuid与此前一致，TLS分别1.2／1.3、证书指纹与此前记录一致，certificate_verified=false。下一步采集当前来源并准备冻结输入，持续输入供给及实际发布验收待完成。
- 用户反馈当前采集目录data/nightly-captures/capture-20261112T080313Z，已准备data/nightly-input。有效6525人物、10289公司／1821学校／693专业，12274任职／7606学校／5361专业事实，共25241事实，隔离233缺人物／3倒置／4超范围及304零日期。plan为update_available，旧real-2a106af85a3330dba3c2-202611，新候选real-32c7c46af8287ce504df-202611。新图尚待构建，下一步读取现有Nginx站点后接维护入口；当前输入为本次手动采集，自动供给仍待接入。
- 用户反馈Nginx维护配置已安装，nginx -t及reload通过，正常页面200、API旧真实版本健康。短时维护演练页面503、API503及MAINTENANCE码全部通过，标记移除后页面恢复200、API版本一致。下一步安装三个systemd模板并核验日历与超时参数，定时启用和完整发布继续待验收。
- 用户反馈三个systemd文件已安装并daemon-reload，verify后日历解析成功，下次2026-11-13 04:30 CST，TimeoutStartUSec=1h30min、TimeoutStopUSec=6min、LoadState=loaded，nginx／query／tunnel均active。输出另有服务器既有snapd／cloudmonitor兼容提示。下一步启用recover及timer，首次完整发布待夜间执行并验收；nightly-input当前为一次手动采集，持续MySQL输入供给仍待接入。

## v0.56 夜间停服版本发布已实现待部署

- 用户要求实现并指定北京时间每日04:30、最多90分钟。新增nightly.py／nightly_host.py及plan/run/recover/status/prune，消费既有真实冻结输入、调用build_real_graph.py、Nginx维护503后停查询API、核验候选并原子切query.env、启动健康检查后开放入口，失败恢复上一完整发布。来源身份变化触发发布，同输入跳过。
- 持久任务／维护标记／原配置摘要支持中断恢复、外部修改保护、并发锁和时间预算。窗口外跳过，Persistent=false；三个systemd模板包括ExecStopPost和开机恢复。历史默认保留最近2份成功发布，额外保护当前／回退／最新候选／输入引用，清理限定本程序有记录的旧jobs资源，失败单独pending。
- 新增50专项，后端617通过／247跳过及1项既有弃用提示，Ruff／Mypy通过。httpx声明为运行依赖，包版本保留，离线锁校验通过。Ubuntu22.04/systemd249解析三个unit及上海04:30日历通过，未实际运行systemd。
- 原生Nginx1.18／Nebula3.8／独立API使用封存真实数据模拟202612跨月，维护、新版本、1至4跳、构建失败回退和中断恢复通过，单次发布119.283秒观察。systemd启停由本机子进程适配模拟。原生清理适配另测通过，本次图／账号／容器已回收，原图保留，data/nightly-release/native-v1退役，维护页截图已查看。
- 手册docs/nightly-release.md、主方案v0.56、更新设计v1.15、部署v1.7。当前服务器仍旧冻结发布，夜间功能待上传部署。真实CDC输入生成、在线人物MySQL及正式合源待接入，实际服务器启停／恢复及维护边界待验。

## v0.55 双源读取与正式合源配置

- 用户确认夜间停服版本化发布，说明当前两库读取以后正式合为一来源。实体／映射、人物／经历两个逻辑角色绑定物理连接，当前CDC继续按已确认联动只订阅实体／映射库。主方案v0.55、更新设计v1.14、交接v3.5维护。
- 已新增update/source_config.py及采集--source-config入口，connections＋entity_source／person_source支持分别连接及共用一个配置，支持端口、CA路径、密码环境引用或交互输入。旧--person-database继续可用，续采核对双角色host／port／database。示例docs/examples/real-mysql-source-config-v1.json。
- 当前采集按角色分别只读一致性快照，同配置仍为两会话，输出暂无配对binlog基线。在线人物API和实际CDC／夜间自动发布尚未接入此配置。正式迁移新服务器需建立新来源世代及全量／CDC基线，核对主键／映射并成对切换图与人物来源配置。
- 新增23项离线回归，相关112通过，完整后端567通过／247跳过，1项既有依赖弃用提示。Ruff通过，Mypy backend/src＋采集脚本88文件通过，CLI help通过。数据库为替身，本轮未连远程源或改线上／当前源指针。

## v0.54 夜间停服版本化发布已确认

- 用户最新明确继续版本化发布，夜间可暂停查询。当前主链路为实体／映射库单源CDC持续采集、夜间有变更时固定范围停服构建核验新图、原子切换配置后单API启动检查并恢复，失败回退上一完整发布。主架构v0.54、更新设计v1.13、部署手册v1.5维护决定。
- v0.53原地更新和v0.51双API连续切换保留历史，前轮30分钟发布参数由夜间窗口替换。具体时刻、频率和维护时限尚未指定，用户未要求当前立即停服或创建定时任务。
- 夜间暂停API减少进程内存和查询争用，构建与恢复串行，候选／旧图空间及全量Python列表仍有资源占用，峰值待测。发布成功后按保留策略清理历史空间及失败资源，保留可用回退引用和审计。
- 本轮只核对现有UpdateProgram的固定范围、发布锁、候选核验与激活入口并维护方案。真实CDC自动接入、夜间调度、在线人物MySQL和真实发布衔接待实现，未改应用／线上或新增运行测试。

## v0.53 单图原地更新候选

- 用户关注版本发布内存并询问直接更新。主方案v0.53、更新设计v1.12评估单运行图、低频原地差分更新，配合持久updating／ready及查询维护窗口。窗口暂停为候选取舍，用户尚未明确接受，时长需实测。
- 内存关注现有calculate_relations全量列表排序、真实读取器完整JSON解析与图回读、额外图空间及双API。拟按影响范围分批计算、磁盘差分和恢复数据控制峰值。当前无新的实测内存数据。
- 改图前关闭所有图接口准入并排空已进入请求，故障updating持久保留，完整核验及恢复后ready。单源CDC捕获和已应用位点各自推进，批次完成序号绑定分页。Nebula3.8事务隔离限制已查官方说明。
- 当前派生关系Rank为快照局部计数，局部原地更新需稳定证据键／Rank映射或重建受影响人物对全部证据，避免跨实体证据覆盖。事实Rank继续上游映射id。不可变发布仓储／图摘要保护及只读SQL证据模型需适配，在线人物MySQL待接入。
- 本轮只读核对及维护方案，未改应用／线上或新增运行测试，当前仍冻结发布。

## v0.52 计算字段存放与现有事实图核对

- 用户询问人物源任职时间等计算字段能否入图及位置。当前已存具体经历边，worked_at为experience_key／start_month／end_month／is_current／position_title，教育两类边带月份及学历／统招原值，Rank沿用映射id。人物VID／source_system／serial_number用于来源定位，姓名展示由SQL提供。
- 本轮核对现有DDL、NumericProjectionAdapter._experience_fact及真实封存graph-plan，12272任职、7606学校、5361专业共25239事实对应字段齐备。当前月份精度YYYYMM，未知NULL，明确在职才is_current=true，同公司多段经历按不同Rank保留。
- 后续联动CDC读取对应原经历并更新候选事实及派生关系，低频后台发布建议与在线人物MySQL仍待实现。本轮只读封存计划与源码及文档维护，未访问远程图或改运行数据，主架构v0.52记录。

## v0.51 低频更新与查询性能平衡建议

- 用户最新要求人物关系低频更新并保持查询性能。主架构v0.51、更新设计v1.11推荐保存预计算人物关系，单源CDC持续接收、后台定时合并构建及发布，前台读取完整图并批量在线查MySQL人物基本信息。每30分钟检查变更为初始建议参数，时效未量化。
- 第一阶段可复用当前6525人／331783关系证据的整图后台构建核心，实测资源与时效后再核定局部范围更新。构建串行、变更合并、固定事务范围和失败重试，采集及发布各自推进。局部增量图发布仍待实现。
- 当前API固定目录且启动全图核验，历史版本切换包含停服重启。连续查询需新增双实例候选启动核验、Nginx切换及旧请求排空，尚未实现及验证。页面区分人物基本信息当前值、图关系截至时间和同步状态。
- 本轮仅代码入口核对和文档维护，未改应用／线上或新增测试。真实CDC调度、在线MySQL、后台发布及双实例入口待实现，现有冻结服务继续为运行事实。

## v0.50 仅事实图直接计算候选

- 用户询问每次直接计算人物关系。本轮评估仅保存人物到标准公司／学校／专业事实，查询时按人物→实体←人物模式及时间属性推导关系，展示人物批量回MySQL。此为候选，最终采用待明确，主架构v0.50及更新设计v1.10记录。
- 当前worked_at／studied_at／studied_major已保存必要事实，uuid_projection.relation_query提供构建时计算参照。查询层uuid_graph仍依赖物化人物边，迁移需覆盖直接／多跳／路径／证据／分页／展开／导出及新清单核验。
- CDC后续在此候选下更新实体、映射及经历时间等事实属性，继续采用上游联动保证。人物业务1跳对应2事实边，4跳主链8事实边。热门实体和逐段去重、同期／同校前提需实测，现有预计算查询耗时不可外推。
- 本轮只有代码与官方模式查询说明核对、文档维护，未改应用／线上或新增运行测试。现有真实发布25239事实、331783人物关系证据保留，v0.48／v0.49候选历史继续保留。

## v0.49 查询延迟重评

- 用户关注v0.48首次查询和失效重算延迟，询问其他方式。主方案v0.49补充推荐实体／映射库单源CDC触发后台预计算和发布、前台读取图及在线批量查MySQL人物，尚待用户选择。v0.48需求保留为前轮明确目标。
- 当前NebulaTarget为新空间整图重建及完整核对，可先核验后台自动发布。局部受影响公司／学校／专业更新需实现跨范围完整性与版本可见性，尚未具备。首次冷计算与统一版本失效会扩大请求工作，低频条件下建议主动后台维护。
- 推荐更新就绪前查询使用上一完整关系版本，显示关系截至时间及同步进度，人物展示当前MySQL值。关系即时追平需等待后台，时效与删除撤回显示待核定。当前6525人样本不证明目标规模容量。
- 本轮仅源码及官方模式核对、文档维护，未改应用／服务器或新增运行测试。更新设计v1.9维护候选，实际仍冻结发布。

## v0.48 首次查询计算写图与版本失效

- 用户最新澄清首次查询在线读取必要MySQL数据、计算关系写图，后续有效缓存命中复用，人物展示持续在线回源；数据变更使旧关系失效并按需重算。此前每次同期查询重算的解释更正，主架构v0.48及更新设计v1.8维护完整目标。
- 单源CDC联动保证继续采用。第一版建议完整事务持久接收与全局关系版本推进同一控制事务，旧缓存逻辑失效、访问时重算。规则版本、基准月及来源世代进入缓存键。统一版本覆盖共享实体新增人物及旧新关系影响，精细实体依赖为后续优化候选。
- 基础关系按中心人物／关系种类完整邻接缓存，图存关系及双事实依据，READY记录覆盖范围含零结果。页面分页与反向边存在不能证明另一中心全部邻接已算。图按尝试隔离、租约和版本条件登记READY，查询前后核对版本，游标绑定版本。
- 多跳／两人路径逐层确保所需邻接已计算且版本一致，缺少缓存有显式状态，达到预算返回处理中／受限。CDC延迟需展示状态，严格覆盖请求开始时源已提交变化需水位追平处理。
- 当前应用仍为冻结SQL＋预计算图，在线MySQL及按需缓存读写待实现。本轮只核对源码并维护方案，未执行新运行测试。62项通过属v0.47已有离线回归。

## v0.47 单源CDC与同期查询时计算

- 用户确认上游具备原经历变更联动更新graph_edge_mapping的保证，后续采用47.113.185.127/test_derui_expert三实体＋映射的单源CDC，人物库39.96.40.93/...仅在线查询和构建按需读取。v0.46双源CDC建议退役，主架构v0.47、更新设计v1.7维护此决定。
- 用户先提出同事补同公司同期类型，随后补充应由本项目在查询时计算。按后者设计，当前worked_at提供人物→标准公司的事实。现程序uuid_projection在构建时预计算company_overlap、uuid_graph读取物化结果。在线展示、单源实际CDC及同期查询时计算均待实现，覆盖直接／多跳／路径／展开／导出并复用既有时间规则。
- 单源位点绑定实体／映射事务，构建记录实际读取的配套人物／经历内容与时间，封存输入用于核对和重试。上游联动保证已确认，后续直接采用。若后续另行交付新edge_type，按实际语义和字段版本适配。
- 本轮只核对代码及维护方案，既有test_update_program.py和test_real_query.py离线62项通过、1项依赖弃用提示。实际部署仍为冻结真实发布，生产容量待验。

## v0.46.1 人物展示应在线回MySQL

- 用户明确关系查询时人物展示应在线查询人物来源MySQL。当前真实部署仍由RealGraphRepository／NumericRepository以只读SQLite URI读取发布source.sqlite，姓名／背景／经历／证据均来自冻结读模型，在线回源待改造。本轮只核对源码并维护主方案v0.46.1。
- 当前采集按有效graph_edge_mapping引用选择人物／经历必要列，发布6525专家／25239事实，保存source-snapshot.json及source.sqlite。应用发布/srv/relationship-map/data/releases/test-20261111-v1，图空间relationship_lab_sync_7bb2f3daef15。同事映射表描述人物经历字段到标准实体的对应，入图后由项目预计算人物间关系。
- 后续展示按来源身份＋原主键批量回MySQL，覆盖人物选择／详情／图标签／导出及删除语义。姓名城市等展示属性与关系事实、背景筛选和分页的时点需逐项核对。冻结SQL为前期验证和版本配对的实现选择，用户本轮澄清在线展示要求后按此推进。

## v0.46 修复版已部署与双源更新待接入

- 用户反馈Nginx已切换/srv/relationship-map/frontend/dist-http-save-v1，入口index-jdcDm5My.js及资源HTTP200。助手随后实际公网浏览器4项全部通过，覆盖保存恢复、真实关系与导出、筛选／分页／手机及同校前提路径。材料data/test-server-deployment/20261111/browser-20261112-final，桌面四跳及手机路径截图已查看，后者记录请求加载中界面。业务HTTP14次通过。
- 用户要求考虑数据来源MySQL更新接入。主架构v0.46、更新设计v1.6记录差距。当前测试API固定读取冻结真实发布，持续更新待部署。MySQLSource当前单库，UpdateStore单checkpoint，CLI capture为文件回放，SourceSnapshot仅mock，更新发布与real-graph-build-v1读取器需要衔接。
- 实体／映射源47.113.185.127/test_derui_expert，人物／经历源39.96.40.93/expert_recommend_real_staging_run_20260713_145630_15247。按已确认全量＋CDC＋微批推进两路位点、持久采集及固定输入，保留权威映射人物范围、日期规范及隔离审计。现有真实快照缺少配套binlog位点，需建立可衔接新基线。真实权限／TLS／日志就绪先只读核验，双源配套、自动发布、恢复与生产容量待验。

## v0.45.4 公网验收与保存条件修复待上线

本节保留当时进度，最终激活和公网验收见v0.46。

- 2026-11-12用户反馈公网已可访问，助手随后直接GET公网meta成功，并通过14次业务HTTP检查，覆盖1至4跳、同校前提正反例及跨教育行正例、两人路径、展开与导出。现有公网浏览器用例3项通过，第4项在保存常用条件时发现crypto.randomUUID is not a function。实际HTTP来源window.isSecureContext=false，randomUUID不可用。
- 已将useSavedQueries.ts的新记录ID生成为getRandomValues提供的16字节随机值的32位十六进制字符串，保存记录继续使用schemaVersion1及字符串ID。新增缺少randomUUID情况下保存与刷新恢复回归。本机构建、类型及格式检查通过，默认浏览器38通过／26跳过。以本机修复构建拦截公网HTTP页面的静态资源、调用真实已部署API，保存、刷新恢复、导出和路径验证通过，secureContext=false、randomUUID=undefined、控制台错误为空，桌面及手机截图已查看。该预览使用本机修复产物，服务器前端补丁待更新。
- 补丁交付data/test-server-deployment/20261111/http-save-fix/useSavedQueries.ts，4690字节。原源码SHA256为cf75d1e0e39caf73b92b0088021f77aecb74d0fe310ae7c50f8732495f3b8f0d，新源码SHA256为c8a5b82fd574178bfe78a1ab145e937973160113261897b5a1072144641281e9。后续按用户逐步反馈上传至应用服务器/tmp/relationship-map-useSavedQueries.ts，核对摘要并备份源码，在服务器构建候选目录frontend/dist-http-save-v1，候选保留旧assets后切换Nginx静态根并校验重载，最后重跑公网浏览器验收。用户反馈HTTP保存兼容修复源码已上传成功。下一步在应用服务器核对原源码与/tmp/relationship-map-useSavedQueries.ts的SHA256，将原源码备份到/tmp/relationship-map-useSavedQueries.before-http-save.ts，替换源码并npm run build -- --outDir dist-http-save-v1，生成候选前端目录。用户已反馈原源码和修复文件两份SHA256均OK，源码已备份并替换，服务器修复版候选构建通过vue-tsc／Vite7.3.7，耗时观察12.32秒，目录frontend/dist-http-save-v1，入口assets/index-jdcDm5My.js。下一步合并原dist/assets到候选并设置读权限，备份Nginx站点配置后切换静态根，nginx -t及reload失败时恢复备份并重载，最后读取本机入口及新bundle。激活及最终公网浏览器验收待反馈。

## v0.45.3 公网访问故障

- 2026-11-12用户反馈应用内浏览器访问http://121.43.176.65:8088/出现ERR_HTTP_RESPONSE_CODE_FAILURE。此前服务器本机页面及API代理均已通过，助手公网curl探测返回错误52，当前故障原因待核对。下一步先由用户在电脑Chrome或Safari地址栏访问同一HTTP地址，再在应用服务器读取三项服务状态、监听端口、使用公网Host头的本机HTTP响应、UFW状态及最近Nginx访问／错误日志。当前仅安排只读诊断，结果及公网和业务验收待反馈。

- 用户于2026-11-12反馈nginx、relationship-query和relationship-graph-tunnel均active，监听为0.0.0.0:8088(Nginx)、127.0.0.1:8000(Python)、127.0.0.1:19669(SSH)，本机带Host:121.43.176.65:8088的HEAD返回200／468字节，UFW inactive。最近访问日志含公网扫描与本机10:02:30的HEAD 200；现有日志格式未区分端口。用户补充的错误日志为11月11日启动／重载notice两行。下一步优先核对应用实例121.43.176.65所关联安全组的TCP8088入方向允许规则和授权来源，若缺少则按测试访问范围添加；安全组配置尚未取得，原因保持待确认。随后再次用电脑浏览器访问，公网及业务验收待反馈。

## v0.45.2 图服务器条件与远程构建

- 用户反馈图服务器为Ubuntu22.04.5 LTS／x86_64、root会话，内网地址172.16.0.154（另有Docker网桥172.18.0.1和172.17.0.1），内存总30GiB／available27GiB、根盘492G／可用456G、无swap。Docker29.5.3、Compose5.1.4已就绪，现有milvus-standalone、milvus-etcd及milvus-minio均healthy，存活端口检查9669／19669为空。系统Python3.10.12，command -v未找到uv。以上为用户反馈，跨机SSH随后已反馈通过，图安装及业务验收待执行。
- 按已反馈环境，NebulaGraph服务在Milvus服务器Docker独立部署，初始化、冻结输入构建及SQL对账由应用服务器既有Python3.12.14虚拟环境通过SSH转发执行。此流程替换v0.45初版在图服务器安装Python依赖并构建后回传整套发布的安排，应用服务器生成配套发布目录。用户已从应用服务器SSH到root@172.16.0.154，返回主机名iZbp1eoksk549i98rt6mawZ、nproc为8，ED25519指纹SHA256:9OPPpTzS/FfMr5aD+Gg9JyqjgQwUp/PCf8gfrWi2j+0已由用户确认并写入known_hosts。用户反馈compose.yaml已通过scp完整传到图服务器/tmp/relationship-nebula-compose-source.yaml，2612字节。用户反馈图服务器已生成/srv/relationship-nebula/compose.yaml，独立项目relationship-nebula-test，平台linux/amd64、restart=unless-stopped，移除原ARM64摘要并保留127.0.0.1:19669映射，Compose校验通过，metad／storaged／graphd的v3.8.0镜像均已拉取完成。用户反馈up -d已创建独立网络、五个卷及三个容器，metad为Healthy，storaged和graphd为Started。首次状态检查因容器curl不支持--retry-connrefused中断，参数已修正为现有healthcheck的curl -sf。用户随后反馈HTTP返回git_info_sha=7458486、status=running，Compose ps中graphd和metad均healthy，storaged为health: starting，宿主绑定127.0.0.1:19669。用户反馈应用服务器排除SSH_AUTH_SOCK、BatchMode=yes及StrictHostKeyChecking=yes的SSH验证通过，返回图服务器主机名，本机19669无监听。用户反馈relationship-graph-tunnel.service已enabled并active(running)，主进程ssh的PID为1925434，本机127.0.0.1:19669由同一SSH进程监听，转发目标为图服务器127.0.0.1:19669。用户已在应用服务器执行scripts/nebula_lab.py bootstrap和check，两次均返回storaged:9779为ONLINE、graphd:9669为ONLINE、Version=3.8.0、authentication=true。初始化期间SDK输出Closing a connection that is in use，随后两次查询均成功；凭据由程序在应用服务器data/nebula-lab/credentials.json私有保存。用户反馈服务器新图relationship_lab_sync_7bb2f3daef15已构建为verified，版本real-2a106af85a3330dba3c2-202611，19326节点、25239事实、331783关系证据、357022总边，validation.passed=true且all_graph_rows_verified=true，构建观察161.423秒。四类独立SQL逐证据计数和摘要与本机原发布一致，图摘要8e45c2f75957c2be30b00cd3eed0e4c305af8142328281745a199d46d270d43e。用户反馈verify_real_graph_queries.py的GUEST核对passed=true，中心p:expert:1076的1至4跳候选数1／2／3／4，逐段连接和SQL事实回查通过，单次小邻域顺序观察44.224／35.433／55.586／66.309毫秒。用户反馈应用服务器80／443／8000／8088无监听，curl为/usr/bin/curl，PATH未找到nginx，nginx服务inactive。下一步按当前root环境创建relationship-query.service，单worker监听127.0.0.1:8000，EnvironmentFile指向已验证真实发布目录，依赖SSH转发，开机启动并失败重启。用户反馈已写入query.env与relationship-query.service并enable --now，服务active(running)，主进程Python PID1925910，开始时间为2026-11-11 20:46:28 CST。用户随后提供journal日志，20:46:29 Waiting for application startup，20:47:03 Application startup complete并监听127.0.0.1:8000，该启动日志窗口约34秒。下一步直接读取health与meta，核对真实模式、版本、6525人物／25239事实及4跳能力。用户反馈HTTP health为status=ok、data_mode=real、版本real-2a106af85a3330dba3c2-202611，meta为6525专家、0简历、12801实体、25239事实、max_relation_hops=4、graph_model=numeric-relations-v1、relation_backend=nebula-materialized。用户提供的安装附件显示Nginx1.18.0(Ubuntu)、包1.18.0-6ubuntu14.22安装完成，9个新包、0升级，needrestart列出的服务重启被延后，最终nginx -v成功。下一步配置/etc/nginx/conf.d/relationship-map.conf，监听8088，静态根为/srv/relationship-map/frontend/dist，/api/转发至127.0.0.1:8000，规范前端产物读权限后nginx -t并启用／重载，再本机检查页面和代理meta。用户反馈nginx -t通过，nginx已enable并reload，本机http://127.0.0.1:8088/的HEAD返回200、Content-Type=text/html、Content-Length=468，代理/api/v1/meta返回预期真实版本、6525专家、25239事实及4跳能力。助手从本机执行公网HEAD及排除代理的GET /api/v1/meta，两次均收到curl错误52 Empty reply from server。公网可达性原因尚待核对，下一步由用户在本机浏览器访问http://121.43.176.65:8088并反馈页面或报错，再完成业务查询验收。网页、业务查询和完整验收待反馈；上述构建和查询耗时均属于当前冻结样本观察。

## v0.45.1 服务器构建与逐步部署

- 用户要求前端在应用测试服务器构建，按照其每次反馈逐步提供下一步命令。手册docs/test-server-deployment.md v1.1改为完整frontend源码／配置／package-lock／tsconfig测试引用打包，服务器npm ci --include=dev并构建。
- 用户终端反馈应用服务器Ubuntu22.04.5 LTS、x86_64、root会话，内存7.1GiB／available4.1GiB、无swap，根盘40G／可用22G。Node v22.23.4，npm缺失，系统Python3.10.12，uv为/root/.local/bin/uv，command -v未找到nginx。图服务器条件待核对。
- 用户进一步反馈/usr/local/bin/node指向/opt/node-v22.23.4-linux-x64/bin/node，dpkg未登记nodejs或npm。该Node目录的bin/npm和bin/npx链接存在，npm-cli.js文件存在。用户已在/usr/local/bin补齐npm和npx软链接并执行hash -r，两者版本均回查为10.9.9。用户回查uv为0.12.7，uv python install 3.12报告该版本已存在，经uv python find定位后执行版本查询为Python3.12.14。用户已回查默认python3为/usr/bin/python3、版本3.10.12。用户已反馈源码包上传到应用服务器121.43.176.65，已反馈服务器SHA256为OK、解压、backend/.venv依赖安装与前端构建完成，图服务器环境已获用户反馈，下一步验证应用到图服务器SSH。服务器安装／构建／部署及验收待用户执行反馈。初版deploy服务账号及本机前端构建方案以本节更新为准，旧静态包127项核对属于历史v1.0。

- 实际交付源码包data/test-server-deployment/20261111/relationship-map-test-20261111.tgz已准备，7970799字节，179个归档项。包包含完整构建所需前端源码、锁文件、tsconfig及其测试引用、后端源码和锁文件、图构建程序及六份冻结输入。5份prepared文件摘要和SQL完整性通过，机器记录为同目录package-validation.json。用户反馈源码包已上传至121.43.176.65，sha256sum -c返回OK，已解压到/srv/relationship-map，data为700权限。服务器uv sync --project backend --python 3.12 --locked --no-dev已在backend/.venv创建Python3.12.14环境并安装35个包，uv pip check反馈All installed packages are compatible。用户反馈应用服务器npm ci安装199个包、vite7.3.7及vue-tsc构建成功，frontend/dist包含index.html与assets，构建观察12.50秒。GraphCanvas为1418.01kB／gzip411.80kB，带既有chunk体积提示。用户反馈图服务器为Ubuntu22.04.5 LTS／x86_64、root会话，内网地址172.16.0.154（另有Docker网桥172.18.0.1和172.17.0.1），内存总30GiB／available27GiB、根盘492G／可用456G、无swap。Docker29.5.3、Compose5.1.4已就绪，现有milvus-standalone、milvus-etcd及milvus-minio均healthy，存活端口检查9669／19669为空。系统Python3.10.12，command -v未找到uv。以上为用户反馈，跨机SSH随后已反馈通过，图安装及业务验收待执行。按已反馈环境，NebulaGraph服务在Milvus服务器Docker独立部署，初始化、冻结输入构建及SQL对账由应用服务器既有Python3.12.14虚拟环境通过SSH转发执行。此流程替换v0.45初版在图服务器安装Python依赖并构建后回传整套发布的安排，应用服务器生成配套发布目录。用户已从应用服务器SSH到root@172.16.0.154，返回主机名iZbp1eoksk549i98rt6mawZ、nproc为8，ED25519指纹SHA256:9OPPpTzS/FfMr5aD+Gg9JyqjgQwUp/PCf8gfrWi2j+0已由用户确认并写入known_hosts。用户反馈compose.yaml已通过scp完整传到图服务器/tmp/relationship-nebula-compose-source.yaml，2612字节。用户反馈图服务器已生成/srv/relationship-nebula/compose.yaml，独立项目relationship-nebula-test，平台linux/amd64、restart=unless-stopped，移除原ARM64摘要并保留127.0.0.1:19669映射，Compose校验通过，metad／storaged／graphd的v3.8.0镜像均已拉取完成。用户反馈up -d已创建独立网络、五个卷及三个容器，metad为Healthy，storaged和graphd为Started。首次状态检查因容器curl不支持--retry-connrefused中断，参数已修正为现有healthcheck的curl -sf。用户随后反馈HTTP返回git_info_sha=7458486、status=running，Compose ps中graphd和metad均healthy，storaged为health: starting，宿主绑定127.0.0.1:19669。用户反馈应用服务器排除SSH_AUTH_SOCK、BatchMode=yes及StrictHostKeyChecking=yes的SSH验证通过，返回图服务器主机名，本机19669无监听。用户反馈relationship-graph-tunnel.service已enabled并active(running)，主进程ssh的PID为1925434，本机127.0.0.1:19669由同一SSH进程监听，转发目标为图服务器127.0.0.1:19669。用户已在应用服务器执行scripts/nebula_lab.py bootstrap和check，两次均返回storaged:9779为ONLINE、graphd:9669为ONLINE、Version=3.8.0、authentication=true。初始化期间SDK输出Closing a connection that is in use，随后两次查询均成功；凭据由程序在应用服务器data/nebula-lab/credentials.json私有保存。用户反馈服务器新图relationship_lab_sync_7bb2f3daef15已构建为verified，版本real-2a106af85a3330dba3c2-202611，19326节点、25239事实、331783关系证据、357022总边，validation.passed=true且all_graph_rows_verified=true，构建观察161.423秒。四类独立SQL逐证据计数和摘要与本机原发布一致，图摘要8e45c2f75957c2be30b00cd3eed0e4c305af8142328281745a199d46d270d43e。用户反馈verify_real_graph_queries.py的GUEST核对passed=true，中心p:expert:1076的1至4跳候选数1／2／3／4，逐段连接和SQL事实回查通过，单次小邻域顺序观察44.224／35.433／55.586／66.309毫秒。用户反馈应用服务器80／443／8000／8088无监听，curl为/usr/bin/curl，PATH未找到nginx，nginx服务inactive。下一步按当前root环境创建relationship-query.service，单worker监听127.0.0.1:8000，EnvironmentFile指向已验证真实发布目录，依赖SSH转发，开机启动并失败重启。用户反馈已写入query.env与relationship-query.service并enable --now，服务active(running)，主进程Python PID1925910，开始时间为2026-11-11 20:46:28 CST。用户随后提供journal日志，20:46:29 Waiting for application startup，20:47:03 Application startup complete并监听127.0.0.1:8000，该启动日志窗口约34秒。下一步直接读取health与meta，核对真实模式、版本、6525人物／25239事实及4跳能力。用户反馈HTTP health为status=ok、data_mode=real、版本real-2a106af85a3330dba3c2-202611，meta为6525专家、0简历、12801实体、25239事实、max_relation_hops=4、graph_model=numeric-relations-v1、relation_backend=nebula-materialized。用户提供的安装附件显示Nginx1.18.0(Ubuntu)、包1.18.0-6ubuntu14.22安装完成，9个新包、0升级，needrestart列出的服务重启被延后，最终nginx -v成功。下一步配置/etc/nginx/conf.d/relationship-map.conf，监听8088，静态根为/srv/relationship-map/frontend/dist，/api/转发至127.0.0.1:8000，规范前端产物读权限后nginx -t并启用／重载，再本机检查页面和代理meta。用户反馈nginx -t通过，nginx已enable并reload，本机http://127.0.0.1:8088/的HEAD返回200、Content-Type=text/html、Content-Length=468，代理/api/v1/meta返回预期真实版本、6525专家、25239事实及4跳能力。助手从本机执行公网HEAD及排除代理的GET /api/v1/meta，两次均收到curl错误52 Empty reply from server。公网可达性原因尚待核对，下一步由用户在本机浏览器访问http://121.43.176.65:8088并反馈页面或报错，再完成业务查询验收。网页、业务查询和完整验收待反馈；上述构建和查询耗时均属于当前冻结样本观察。

## v0.45 双服务器测试部署手册

- 用户要求整理步骤与命令，手册docs/test-server-deployment.md。默认Ubuntu22.04／24.04、systemd、deploy账号，Milvus服务器已有Docker／Compose及相应操作权限。服务器实际地址和条件待核对，部署待执行。
- 图凭据类型固定127.0.0.1:19669，本轮采用systemd托管SSH转发。生成独立NebulaGraph测试Compose，移除本机ARM64摘要和平台限定，使用v3.8.0本机架构镜像及持久卷。
- 打包六份已核对冻结输入，在图服务器build-prepared重建新图、独立SQL及四跳核对，再传整个发布目录给应用服务器。API单worker、GUEST图账号、只读SQL快照，Nginx静态前端与8088测试入口。业务规则沿用v0.44。
- 本机21段Bash／3段Python语法、Compose解析、127项实际归档、5份摘要及SQL完整性和6525人物／25239事实通过。Linux依赖、远端拉镜像、SSH／systemd／Nginx运行和业务验收待执行。Milvus共存容量、持续CDC及自动发布待验。

## v0.44 同专业查询的可选同校前提

- 用户最新澄清直接增加可选同校前提，v0.43严格同教育行、same_school_major和四事实新模型提案退役。按现有人物same_school关系筛same_major，允许学校和专业来自不同教育行。
- require_same_school严格布尔，仅same_major允许true。前端新查询默认勾选，API默认false，旧保存条件缺字段恢复false。true隔离游标，false兼容旧指纹。
- 列表／逐段1至4跳／两人路径／取证／展开／导出贯穿前提，同校多证据DISTINCT折叠。两人对比继续全部共同经历视图。现有真实图及data_version继续使用。
- 只读真实SQL交集2901证据／2409人物对，HTTP25次核对通过，跨教育行正例、跨校反例及SQL BFS1至4跳1／5／6／14完整一致。材料data/school-prerequisite/run-v1，后端544通过／247跳过，真实浏览器4通过，旧演示最终37通过／26跳过，静态／构建通过，截图已查看。既有GraphCanvas体积提示保留，生产并发及热点容量待验证。

## v0.42 真实查询与展示源已切换

- 用户授权使用v0.41真实图。当前data/frontend-source.json指向real-graph/run-v1/build-v1，8000／5173实际data_mode=real、6525专家／25239事实、max_relation_hops=4。SQL详情来自配套只读快照，图关系来自relationship_lab_sync_2d1b24919065。
- RealGraphRepository核对封存文件摘要、契约、SQL标记及计数，启动GUEST全图回读，独立120秒预算。请求前后固定文件stat签名检查，变更409。业务预算沿用既有值。正常dev启动等待150秒适配完整启动核对，实际19.476秒观察。
- Metadata／Health／Error支持real，页面、CSV、PNG及文件名改按来源模式。长图节点标签换行最多三行。新增8项离线发布保护回归，后端531通过／247跳过，真实浏览器3通过，旧演示37通过／25跳过，旧UUID真实6通过／3跳过，旧数字HTTP通过，静态／构建通过。截图已查看，材料data/real-query/run-v1，源切换前配置保留于previous-frontend-source.json。
- 原表1905年日期按源值展示，当前图涉及3405任职／1258学校／1061专业事实，见source-date-observations.json，需要上游核对。既有240隔离、304零日期及简历映射覆盖边界遵循v0.41。
- 主方案v0.42、docs/real-query-source.md记录实际接入。当前按冻结版本查询，自动持续更新／源库新数据发布、完整简历映射及生产容量继续待验收。私有运行材料置于data目录，源库密码未加入运行查询配置。

## v0.41 真实跨库关系图

- 用户指定实体及映射47.113.185.127/test_derui_expert，人物39.96.40.93/expert_recommend_real_staging_run_20260713_145630_15247。两个只读一致性快照保存在data/real-graph/run-v1，人物／经历读取完整权威映射引用范围，当前映射全部expert，简历事实等待上游映射。
- 真实图relationship_lab_sync_2d1b24919065，版本real-2a106af85a3330dba3c2-202611，6525专家，10287公司／1821学校／693专业，19326节点、25239事实、331783人物证据。图及GUEST账号保留。构建产物data/real-graph/run-v1/build-v1/manifest.json，私有SQL及源文件600、目录700。
- 233条缺失人物引用（70人）、3条倒置日期、4条超范围日期显式隔离，304个零日期本机规范为未知NULL，原始输入保留。2570条已删除人物对应映射按有效性退出。任职0保留原值，is_current只在1确认；0缺截止日不生成同期推断。实体已合并作非活跃。
- 新numeric-authoritative-v2按原字段＋目标判重，允许不同目标各用上游Rank，同目标重复阻断。最终60个多目标字段保留121事实。已有v1单目标行为保持兼容。构建／回读上限显式配置，本次使用事实保守上界357515，默认10000兼容旧调用。
- 全图回读摘要与四类独立SQL证据逐条核对通过，GUEST真实小邻域1至4跳与SQL事实BFS及段落回查通过。本次构建及核对95.867秒。后端523通过／247跳过，新增9项，Ruff／Mypy通过，旧UUID真实专项6通过／3跳过。源TLS采集关闭证书链校验并记录指纹，正式证书配置待匹配。
- 主方案v0.41、docs/real-graph-build.md维护结果。本轮独立格式real-graph-build-v1，真实HTTP模式与前端切换待接入，双源业务版本边界、CDC调度、简历覆盖及生产容量继续待验证。真实小邻域耗时不能外推生产性能。

## v0.40.3 真实MySQL来源已连通

- 公司测试源47.113.185.127:3306，实际账号及库为test_derui_expert。通过本机DBX非敏感连接配置核对账号，使用用户提供密码后PyMySQL只读登录成功，MySQL8.0.24、TLSv1.2。此前root1045属于历史尝试。密码仅交互输入。
- 三实体表真实一致性快照为data/remote-mysql-inspection/entities-20261111T084435579366.json，公司10287／学校1843／专业701，ID／UUID唯一及格式、标准名基本检查通过。已合并学校22／专业8，实际契约按已核验／已合并状态核定。本轮自签名TLS探测关闭证书链校验，正式连接证书配置待匹配。
- graph_edge_mapping28049条均为expert，工作13001／学校8740／专业6308。专家39299、简历6476，原经历表已读DDL及计数。重复槽位／多目标、引用、热门实体预算及简历映射覆盖继续核对，真实人物图未发布。
- log_bin ON、ROW、FULL、保留600000秒为实际变量，复制权限未验收。graph_sync_batch维持上游责任，新增outbox／release／slot职责需按实际契约核对。主方案v0.40.3保存数据来源及运行条件，当前前端模拟发布按v0.40记录。

## v0.40 单人物1至4跳

- 用户确认单人物多跳计划，已在找关联的人入口实现max_hops严格整数1至4、默认1。数字及UUID图支持4，其他模式支持1，MetaResponse新增max_relation_hops。设置N包含1至N跳，逐段筛关系和同期，背景／来源只筛最终候选。
- 图内固定深度模板逐层WITH DISTINCT折叠平行证据，选取最短且按有序人物ID序列最小的一条链。Python装配证据，姓名回SQL。列表connection摘要、取证connection详情及导出connection_detail可选新增，旧直接items语义保留，CSV末尾追加5列。
- 多跳搜索／摘要共用5秒请求预算，达到预算明确失败。游标升materialized-cursor-v3-hops；旧保存条件缺max_hops取1。保存、中心、展开、分页与导出带生效深度，画布仍100节点／200边。该参数作用于单人物流程，原两人路径入口按原实现范围解释。
- 主架构v0.40、接口台账v1.5，材料data/multihop-v040。后端514通过／247跳过，原生专项18通过，默认浏览器37通过／22跳过，数字7通过、UUID3通过。独立8人图覆盖3／4／5跳边界和重复证据，临时空间／账号已回收。当前8000／5173已核对陈亦舟1跳排除周景行、2至4跳召回。小图顺序耗时不是生产容量证明。

## v0.38 前端均衡数字来源

- 用户要求将v0.35均衡模拟数据作为前端来源。采用已验证MySQL初始baseline的262人，当前默认data/frontend-source.json指向data/balanced-frontend/run-v2/state，8000／5173服务已切换。SQL为配套只读source.sqlite查询快照，图为新建并保留的原生Nebula空间及只读账号，旧实验源库已回收。
- NumericRepository及查询SQL读模型接入既有物化查询服务，实体API ID为company／school／major:<整数>字符串，姓名只回SQL，Rank继续消费上游graph_edge_mapping.id。学校＋专业必须同一experience_key，公司＋职位同条任职。前端物化能力同时支持UUID和数字来源，同专业服务校验已适配。
- 新数字浏览器3通过，旧演示37通过／18跳过，旧UUID真实专项6通过／3跳过，桌面／手机／路径截图已查看。完整结果见docs/balanced-frontend-source.md及data/balanced-frontend。run-v1首次被沙箱本机网络限制，未创建图或激活；run-v2为成功持久来源。临时测试端口18013／15183已回收，正常开发服务保留。
- 主方案v0.38保留v0.36／v0.37的N跳需求与阈值建议。当前路径程序最多一位中间人物，N跳及生产容量继续待实现／压测。模拟数据验证不代表生产数据验收。

## v0.35 最新表与均衡履历真实MySQL验证

- 用户授权本地建最新版测试表，要求模拟履历合理、关系均衡且覆盖多跳。主架构v0.35，报告docs/mysql-latest-native-validation.md，机器记录docs/data-sources/mysql-latest-native-v1-validation.json。最终data/mysql-update-latest/run-v3-final，run-v1／run-v2-final保留先前通过记录。
- 新增infra/mysql/schema/file-mapping-v1.sql，按文件映射版说明具体化必填／可空和约束，5表58列＋既有8原表为13表228列。独立MySQL 8.4.13容器／本机Nebula3.8实测，正式DDL及状态仍需核定。
- scripts/mysql_update_dataset.py含262虚构人物（专家／简历各131）、101公司、78学校、54专业及1055事实，六行业背景＋22手工人物，单家公司最多7人。基线同公司1178／同期916／同校605／同专业1300证据。11人工场景正反向及过滤通过，全图27607两跳三元组、4681端点对，其中2809无直接关系完整一致。范围仍一位中间人物，三边链作范围外反例。
- 新增numeric-authoritative-v1直接消费同事维护graph_edge_mapping，id为Rank，无名称映射表依赖。原numeric-v1保留，已删除旧槽位与活跃替代可并存，多个活跃目标仍拒绝，独立契约／基线迁移。新增18项回归，更新专项72通过，完整后端500通过／240跳过，Ruff／Mypy通过。
- update/mysql_source.py用mysql-replication1.0.16（uv.lock锁定）实现RR一致性初始化与binlog完整事务读取，采集持久后确认。源账号仅SELECT＋复制，快照协调用独立容器管理员短读锁。当前ROW／FULL镜像及列元数据、无事务压缩／局部JSON，文件位点恢复；DDL及不支持事件阻断，其他版本／HA待验。
- scripts/mysql_update_lab.py实测初始化并发提交、构建期间捕获后两事务而基线仍固定0、跨表纠正、映射DELETE／恢复、孤立人物软删、跨月、逐表SQL对账、回滚、重放及读取器恢复，旧图保持原结果。三次运行15图空间／账号和3MySQL容器均回收，指针退役，SQL导出和履历／用例保留。
- 数字模式HTTP／前端、无人值守周期调度、续租、长期保留、主从故障切换及生产容量仍待完成。本轮真实CDC为独立协议适配器和实验入口，不描述为部署好的生产同步服务。下文v0.34“真实CDC待实现”等为当时状态。

## v0.34 同事维护映射与CDC边界澄清

- 用户明确graph_edge_mapping由同事维护，“图边生成程序”指生成映射表内容。该表是上游已准备好的权威输入，本项目只读消费其id作为事实Rank，复制到发布SQL保留来源值。维护方已确认，不再重复询问。本项目私有Rank分配／rq_fact_identity账本提案退役，上游ID纠正／恢复及多目标粒度由实际契约核定。
- 主架构v0.34，交接v3.2、稳定标识v2.8、更新设计v1.4及现有实现说明同步更正。名称映射JSON的UUID解析／原文校对属于同事生成表过程，下游可选审计。直接CDC映射表即可接收审核／撤回／改关联，不再将下游文件接收或独立触发作为必备主链路。映射审核的图可见结果应写入权威表。
- 首次来源一致性快照建立已有数据并衔接日志，后续微批用本地基线与CDC历史。UpdateStore.claim已固定from_seq／to_seq，UpdateProgram._build用rows_at(to_seq)并生成source.sqlite，截止点由程序选定的完整已提交事务构成，采集可继续推进后续范围。发布SQL是本地查询产物，不能混同每轮从源库全量导出。
- 关联更新尽量由上游同一MySQL事务提交，跨多个事务的业务就绪边界仍需约定，CDC完整事务不自动证明整次业务发布就绪。graph_sync_batch继续上游血缘，不承担本项目任务。当前numeric-v1名称表强依赖和单槽位检查仍需适配，真实MySQL／CDC与数字API待完成，现输入为文件事务回放。
- 本轮代码路径核对与文档检查，未改应用源码或新增运行测试。下文v0.33及v0.32中下游分配Rank、直接消费文件等提案属历史，当前责任及链路以v0.34为准。

## v0.33 文件映射具体规则建议

- 用户询问多目标Rank、事实表归属和版本配对如何处理。主架构v0.33补充具体建议，交接v3.1、稳定标识清单v2.7同步引用。文件映射版采用已确认，下面规则仍是建议，尚未获确认或实现。
- 建议slot_key含稳定来源数据集／expert或resume／逻辑表／原行／字段，fact_key再含实体类型及目标UUID，持久分配正有符号64位Rank。属性纠正保留，A→B令A退出、B用自身Rank，恢复A复用原Rank，账本不重排或回收编号。此规则调整旧单槽位目标纠正沿用Rank候选，需要独立新基线及旧版本解释。
- 建议本项目更新程序唯一维护私有身份账本并生成发布SQL的graph_edge_mapping，源读取只读，需协调Word事实表产物／部署归属。现有UpdateStore事务和租约可复用，账本及唯一约束扩展尚待实现，构建分配不提前改变活跃事实集合。
- 首版建议自动处理明确单目标，多个UUID的时间／职位归属不明时阻断候选并保留旧发布，真实拆分或稳定子项由上游提供。同教育行规则继续，不能用数组位置配对。
- 候选固定完整映射版本／摘要、SQL快照或完整事务截止点、契约及基准月，组合输入去重，文件单改可触发。原文／引用／完整性不符阻断，相同映射版本不同摘要视冲突。新增能力未实现，本轮仅代码边界核对和文档检查，未新增运行验证。

## v0.32.1 文件映射版采用确认

- 用户2026-11-10说明上游发布频率预计较低，明确“可以使用这一版”，文件映射版eafd2c32已采用为后续来源方案，无需再次询问是否采用。主架构v0.32.1，交接v3.0.1，评估报告顶部记录确认依据。
- 发布频率、可见时效仍为定性条件，具体轮询／调度参数尚未确定。保留首次全量＋CDC＋微批方向并增加文件版本接收，低频清单轮询作为接入建议。多目标事实与Rank、graph_edge_mapping维护方、完整范围及SQL／原文配对仍需定稿，当前文件适配及数字查询API待实现。本轮仅维护采用记录，测试证据沿用v0.32。

## v0.32 文件映射来源评估

- 用户2026-11-10指定《副本人物关系图谱MySQL表结构设计说明_文件映射版.docx》为最新版，摘要eafd2c32。主架构v0.32，报告docs/mysql-file-mapping-assessment.md，原文／差分及探测docs/data-sources/mysql-file-mapping-review-eafd2c32.json。
- 最新为5张MySQL表58列，移除graph_expert_name_mapping及graph_company_relation。三实体id改为MySQL自增BIGINT并新增唯一uuid，按uuid同步且保留整数id。文件按来源表／字段组织，键为原经历ID字符串，值为完整原文及标准UUID数组。按类型＋uuid查本库整数id，沿用e:company／school／major:<id>类型VID。原8张人物／经历表仍需交付，不能按名称重建对应。
- 多UUID与单槽位事实表粒度、稳定Rank及任期职位归属，graph_edge_mapping的单一维护方，manifest完整范围及SQL／原文配对为接入前待定项。本项目私有投影库维护事实账本为建议，尚未确认。Word查询时计算人物关系残留不覆盖既有入图nGQL预计算规则，姓名只回SQL。
- 在既定首次全量＋CDC＋微批方向上，建议增加映射清单通知／轮询及接收。文件独立变化即使SQL位点与月份相同也应生成新候选，组合输入版本进入幂等／发布核对，数据版本与SourceContract指纹分开。graph_sync_batch继续仅属于上游同步。完整同范围文件缺键才能撤回旧事实，缺片／坏哈希／引用不一致应阻断候选。
- 当前numeric-v1仍强制名称映射逻辑表和单目标槽位，文件UUID解析及数据版本触发未实现，查询API仍历史UUID。6项实际程序探测与10项独立机制示例使用临时SQLite和图替身，更新专项54通过。本轮未改应用源码、Word、运行发布或访问MySQL／Supabase／原生图，不代表新版端到端通过。

## v0.31.2 经历边标签、摘要与精确定位

- 用户确认执行现有经历边标签、悬停摘要、点击证据和显示文字开关。主架构v0.31.2，前端记录docs/frontend-redesign-impact.md v1.3，源码复用现有GraphEdge.label／fact_id及facts／evidence接口。
- GraphCanvas默认显示任职／就读／所学专业，可关闭文字；重复边通过平行曲线区分，选中边高亮。useGraphEdgePreview停留150ms后读取facts，当前图内按人物缓存，离开／换图／卸载取消请求；按版本和基准月核对。路径图共享画布，边标签按事实类型表达。
- 工作台点击边按fact_id显示具体经历与来源、过滤对应左右事实证据、在完整履历中标记该事实；详情失败重试保留定位。触摸事件在兼容鼠标事件后分发，避免抽屉立即关闭，组件卸载清理待分发动作。
- graph-edges新增4项专项。最终默认演示浏览器37通过／15跳过，类型／格式／构建通过，桌面和手机截图已查看。材料data/frontend-graph-edges-v0312/full-run-v3-final，测试服务18012／15182已回收；原生UUID专项本轮未重跑。GraphCanvas分块约1417.94kB，gzip411.80kB，保留既有体积提示。

## v0.31.1 人物与证据内部滚动

- 用户反馈长详情撑高页面，主架构v0.31.1，前端记录docs/frontend-redesign-impact.md v1.2。EvidencePanel桌面高度clamp(400px, 100dvh - 300px, 760px)，标题／页脚保留，正文内部滚动；窄屏抽屉使用可用高度，正文可键盘聚焦。
- HTTP调用与参数沿用v0.31。新增四尺寸32条证据／32条履历专项4通过，默认演示浏览器33通过／15跳过，类型／格式／构建通过，截图已查看。独立端口18010／15180的测试服务结束回收，记录data/frontend-evidence-scroll-v0311；原生UUID专项本轮未重跑。

## v0.30.1 更新程序审计与本机真实图验证

- 用户要求审计并尽可能本地真实运行。主架构v0.30.1，报告docs/update-program-audit.md、汇总docs/data-sources/update-program-audit-v1-validation.json。修复未知表静默遗漏、迭代解析未暂停、GUEST就绪核对、bootstrap预检、重试微批预算及失败图资源追踪六项。
- 更新专项54项、完整后端482通过／240跳过，Ruff lint与Mypy通过。新增scripts/update_program_lab.py，固定虚构文件输入，真实NebulaGraph 3.8.0执行全量／三次事务微批／跨月五轮，人物关系证据4／2／1／3／3，GUEST可读且写入被拒，旧图不变、重放去重。
- 初次CLI与连续验证共6个空间／6个账号已回收，data/update-program-audit/native-v1及native-v2-final的active.json均退役为retired-active.json。这些目录保留报告，不可作为可用发布源，重跑使用新目录。
- NebulaTarget创建空间前写build-resource.json，成功清单纳入摘要，旧清单继续兼容；实际新只读账号完成标记核对最多等待60秒。源适配器先筛白名单，核心对未知事件表整事务回滚并暂停。已有候选超出本次调小预算会返回BATCH_RANGE_LIMIT。
- 此次真实范围为文件事务→SQLite控制／快照→原生图，未连接MySQL，实时CDC、一致性快照、数字查询API、自动调度及生产容量仍待完成。下面v0.30仅离线图替身的边界为历史状态。

## v0.30 无测试库条件下的独立更新程序

- 用户明确当前没有测试库，先单独实现更新程序，并强调后续MySQL结构可能调整。主架构v0.30，手册docs/update-program.md，设计v1.2及交接v2.1。沿用全量＋CDC＋本项目微批发布方向。
- backend/src/relationship_query/update分离版本化SourceContract、数字ProjectionAdapter、ChangeSource、UpdateStore、GraphTarget和发布目录。当前具体来源为文件快照／JSONL完整事务回放，实际MySQL一致性读取、实时Canal／Debezium适配、周期调度、数字查询API适配待完成。回放材料由本项目维护，上游无需制作JSON。
- 本轮自选私有SQLite控制状态update-state-v1，事件、行历史及位点同事务提交后确认，完整事务幂等与固定截止点微批。独立standalone-update-v1规范化SQL快照需要后续查询适配。既有MySQL三表DDL继续保留部署设计，尚未安装到运行库。
- 数字实体VID e:company:1／e:school:1／e:major:1，保留事实Rank、同条经历与姓名只回SQL规则。表列、整数／日期、命名空间与状态集中配置；未知状态、缺列、DDL、指纹变化显式阻断，结构迁移在核对后建立新基线。
- NebulaTarget复用既有事实写入、nGQL四类人物边计算和完整回读，每次新空间／尝试目录；租约令牌及原子active.json支持发布中断补记。此次未连接MySQL／Nebula，图适配调用采用测试替身。
- 默认快照10000行、单事务10000事件／8MiB、全量文件64MiB、微批100事务及图关系证据10000条；超限失败。事件与行历史暂未清理，租约默认300秒，生产容量与长期保留待验证。
- backend/tests/test_update_program.py共40项离线专项通过，完整后端468通过／240跳过，Ruff／Mypy通过。data/update-program-trial保存离线运行材料；所有Python使用backend/.venv。

## v0.29 更新链路与测试接入已确认

- 用户明确上游将在测试环境创建新版测试表和模拟数据，本项目负责接收并更新图，已确认采用首次一致性全量＋CDC采集＋本项目微批发布。主架构v0.29，更新设计docs/mysql-change-sync-design.md v1.1，当前交接docs/data-handoff.md v2.0。
- 实施顺序为新版BIGINT来源／独立图版本→全量提交位点基线→可靠CDC及本项目控制库→完整事务微批构建与对账→停服成对发布与恢复。具体采集器按实际测试MySQL版本和兼容性核定，方案模式已确定。
- 测试接入需实际DDL及测试表对应、网络／TLS和私有账号材料、ROW与完整行镜像及日志保留、最小复制／快照权限、核验状态样例。实体类型隔离、大BIGINT、增删改、映射DELETE、跨表事务、回滚、重放与故障用例见更新设计，当前均为待执行清单。
- 当前运行仍为历史UUID模式，数字适配、CDC／Worker与发布协调器待实现；本轮为采用确认与接入准备，无新增数据库／图运行验证。上游graph_sync_batch不承担本项目任务或发布控制。

## v0.28.1 新字段结构已确认采用

- 用户明确回复“这些结构变更也按新版采用”。说明补充版(2)摘要822c28a5为当前目标来源依据，graph_expert_name_mapping、11处UUID→BIGINT和5处is_deleted移除均已确认，不能再重复询问是否采用。主架构v0.28.1，当前运行代码仍为历史UUID模式，数字模式待适配。
- 后续实体内部键／图VID应区分company／school／major类型，建议company:1及e:company:1等，避免独立数值ID碰撞；该命名属于适配设计建议。实体使用实际deleted_at及核验状态，名称映射按同步程序清理结果消费DELETE或权威完整快照差分，不补造is_deleted。
- 不按名称创建UUID到数字ID对应，不因graph_expert_name_mapping表名而排除resume来源。姓名只回SQL、事实Rank、同条经历与入图预计算规则继续有效。新Word中查询时计算和拼写残留不替代这些已确认规则。
- 本轮确认更新主方案、字段说明顶部标记及核对报告；旧v5.0正文／Word作为历史已实现UUID映射。数字来源代码、新图版本、CDC基线及完整回归仍待实现。

## v0.28 新字段文件影响核对

- 用户提供《副本人物关系图谱MySQL表结构设计说明_说明补充版(2).docx》，摘要822c28a5；报告docs/mysql-supplement-v2-impact.md，原文及差分docs/data-sources/mysql-supplement-v2-field-review-822c28a5.json。主架构v0.28，本轮仅文档与离线兼容性探测。
- 新文档graph_name_mapping→graph_expert_name_mapping、11处CHAR(36)UUID→BIGINT、5处is_deleted移除；实际字段行合计76，旧基线81。管理字段正文仍称6个实际5个，另有graph_conpany／work_expertience与人物关系查询时计算等残留。
- 本节为初次核对记录，采用范围已由v0.28.1用户确认。UUID适配目前直接读取is_deleted并解析UUID，独立内存输入探测证明数字ID／缺列会阻断。当前12表模式不直接读取名称映射表，单独表名变更直接影响有限。
- 确认新契约后再设计实体类型命名空间、SQL有效性及新版本投影／CDC基线，避免三张数字ID表的e:1碰撞；原姓名禁入、事实Rank和同条经历规则继续。此次未操作数据库／图／服务，完整新模式待适配。

## v0.27 已准备MySQL的下游更新设计

- 用户明确graph_sync_batch属于同事Supabase→MySQL同步，本项目需自行设计更新控制；选型按上游MySQL数据已准备好评估，不继续等待或轮询上游归一完成表。此为评估前提，实际远程实例仍未交付。
- 主架构v0.27，设计docs/mysql-change-sync-design.md，DDL infra/mysql/schema/query-update-control-v1.sql。推荐一致性全量基线＋CDC持久采集＋本项目微批发布；自建rq_cdc_checkpoint／rq_cdc_event／rq_projection_batch于独立控制库。
- 事件与消费位点同本项目SQL事务提交后再确认CDC。tx_seq由checkpoint行锁内分配，范围按完整事务封批；captured位点与published批次分开推进。稳定事件键去重，租约令牌防旧Worker提交，每次构建尝试独立SQL／图资源。
- 现有原子激活文件为发布事实依据，未来实施需增加基线版本／租约核对与指针替换后的控制表补记。图仍以nGQL重算，已发布空间不可变。独立无外部网络MySQL 8.4.13容器20项DDL／控制事务例通过并回收，报告docs/data-sources/mysql-update-control-v1-validation.json。合成游标与发布字段只用于表约束例；三表尚未安装到当前运行库，CDC／Worker待实现。

## v0.26 远程 MySQL 只读接入

- v0.26.2历史建议曾首选轮询上游完成批次，已由v0.27用户澄清替换。正式以已准备MySQL和本项目自建控制表评估，历史讨论保留供追溯。
- v0.26.1补充更新采集候选，当前请求检查mutation_seq并在源提交变更后返回409，自动同步仍待实现。可轮询完成批次或采用CDC持久采集，发布须等原经历／归一／映射完整配齐，图继续nGQL计算。相关方案仅评估，未接入或改动现有Canal；初始快照与位点衔接、幂等／重放、删除与旧证据清理、基准月推进和成对版本发布须验证。
- 用户2026-11-09确认没有现成远程库，授权通过模拟修改代码与测试。主架构v0.26，报告docs/remote-mysql-validation.md；当前激活数据源仍为下文v0.25本机配置。
- UUIDManifest清单format_version=5，沿用mutation-sequence-v1，source_endpoint绑定host／port／CA摘要及连接读取超时。普通远程库名和只读账号名可用，URL须与清单匹配；mysql-ca.pem加入bundle_digest。显式SSLContext校验CA和主机名，最低TLS1.2。
- open_source_engine统一API及发布完整核对的连接选择。旧v2／v3／v4、本机lab_url和实验写入限制继续有效。远程运行连接只读，账号启动检查当前只接受直接USAGE加目标库SELECT；正式角色授权与真实15表契约待适配，data_mode仍mock。
- scripts/remote_mysql_lab.py仅创建本次独立本机容器，镜像mysql:8.4固定摘要，随机loopback端口、测试CA／证书，复制已冻结虚构源并复用只读图。51项专项通过；结束回收本次容器和匿名卷，输出地址失效。run-v3-final为最终记录，run-v2保留；重跑须新目录，不激活已回收模拟源。失败清单移为failed-manifest.json。
- 新增backend/tests/test_remote_mysql.py。原生入口RELATIONSHIP_REMOTE_MYSQL_TEST_DIR仅用于脚本新建的demo_remote_模拟库；末项提交虚构纠正后返回409，容器随即回收。真实远程网络、证书轮换、生产并发、热点容量和正式发布仍待验证。所有Python使用backend/.venv。

## 当前运行查询 v0.25

- 2026-11-09 用户授权推进查询性能改造，主架构v0.25，报告docs/performance/uuid-query-v025.md。图DDL及字段映射继续为uuid-relations-v5／v5.0。下面v0.24及更早为各轮历史边界。
- 新清单format_version=4、sql_guard=mutation-sequence-v1。sql_release_guard.py在新实验SQL库的项目辅助表记录源摘要／版本／基准月／状态及变更序号；12来源表36个DML触发器与源修改同事务提交／回滚。新账号仅SELECT，启动核对SHOW GRANTS，发布和启动完整对账，请求以固定行与激活指针检查漂移。管理员DDL须停服重对账后发布，触发器检测范围为DML。
- format_version=3兼容并继续完整快照校验，已发布旧库保持原结构。新激活目录data/uuid-query-performance/guarded-v1，修订7，SQL relationship_lab_handoff_146435a232a0，复用原图relationship_lab_uuid_b19a220c6635。回退数据源后仍用当前查询代码。
- 取证按8人物对、按类型合并UNION ALL，每对独立ORDER／LIMIT／探测项，预算和逐RPC剩余超时保持。候选图分页128＋1，SQL筛背景补足当前页＋1，单对资格直接查询图。旧1000候选总量门槛已替换，单对证据1000与画布上限仍保留；时间／图读取预算不足明确失败。
- 查询游标指纹加入materialized-cursor-v2，旧规则游标拒绝，条件保存恢复重查第一页。图负责关系和路径，SQL提供背景／显示及来源，Python不重算关系。
- scripts/uuid_query_lab.py仅新建本机虚构SQL／图，克隆冻结源或构造1001–4000候选星形样例，旧资源只读。scale-1100-v1已完整回读核对4400条边并完整分页1100候选。mutation-v1仅供破坏性演练，末尾已提交虚构纠正，保留409状态，重跑应新建目录。
- 新回归backend/tests/test_uuid_query_performance.py。原生环境分别为RELATIONSHIP_UUID_QUERY_TEST_DIR、RELATIONSHIP_UUID_MUTATION_TEST_DIR、RELATIONSHIP_UUID_SCALE_TEST_DIR，破坏操作只针对mutation命名的新独立库。34项组合专项已通过，既有演示回归继续执行。
- scripts/benchmark_uuid_query.py顺序7次ASGI观察，startup另行完整核对，相同63人冻结响应对照通过。观测数据在data/uuid-query-performance。SQL计数为SQLAlchemy事件，图计数为GraphClient.execute，代表性生产并发／热门实体平方级构建待验证。所有Python仍使用backend/.venv。

## v0.24 运行模型迁移

- 用户已授权将当前服务迁移到 uuid-relations-v5。完整定义仍为 uuid-facts-v3.ngql＋person-relations-v3.ngql；字段映射 v5.0 不变。当前实施见 docs/uuid-graph-migration.md，架构 v0.24；以下 v0.23 及更早“应用仍v0.16”属于历史状态。
- 新代码 uuid_source.py／uuid_projection.py／uuid_graph.py／uuid_api.py 处理 UUID 来源、图构建、物化人物边与 SQL 回查。新模式列表、摘要、证据、对比、展开和关系导出均消费图人物边；路径至多一位中间人物，SQL 不召回关系候选，Python 不重算关系。
- person 只存来源与业务编号，姓名批量从 SQL 展示。事实 Rank=graph_edge_mapping.id；人物边 Rank 只是局部序号，左右事实引用和 experience_key 保持可追溯。学校与专业同教育行可同组，不把事实数当独立经历数。
- scripts/migrate_uuid_graph.py 仅消费已冻结虚构旧源及明确历史 UUID 对照，新建本机实验 SQL／图，不恢复废弃字典，不访问 Supabase，不覆盖旧库空间。新库是八原表＋三标准表最小字段子集＋边映射，共12表；没有把名称映射、完整批次和组织关系的正式契约接通，不可用于真实处理中来源。新模拟模式暂只有标准名检索。
- format_version=3／model=uuid-relations-v5，沿用 RELATIONSHIP_SOURCE_RELEASE_STORE 停服切换；当前激活 data/uuid-graph-trial/run-v1，旧 data/source-api-trial/run-v2 保留回退。新图 relationship_lab_uuid_b19a220c6635，SQL relationship_lab_handoff_e7d11a446004。旧 writer／图含虚构姓名，仅用于历史，不给生产数据使用。
- 构建先 staging、nGQL 计算并写四类人物边、完整回读后 ready；保守关系对上界10000，预算不足不能截断发布。新模式列表图候选1000、证据每人物对／类型1000，超限明确失败；路径保留原预算，不把 LIMIT 当服务端扫描界限。
- backend/tests/test_uuid_graph.py 离线预检与独立原表基准；原生专项显式 RELATIONSHIP_UUID_TEST_DIR；frontend/tests/uuid-graph.spec.ts 显式 RELATIONSHIP_UUID_BROWSER=1，须用匹配的新服务。默认 check.sh 仍验证原 SQLite 演示，运行时不得复用占用5173的新模型服务来跑默认数据用例。
- 所有履历仍虚构；正式15表预检／发布、身份权限、生产增量清边、备份和容量尚未验收。保持虚拟环境和不可变快照约定。

## 字段对应文档 v0.23（历史）

- 用户要求按当前DDL及SQL回查字段重整文档。docs/mysql-to-graph-fields.md与Word交付版现为v5.0，对应uuid-relations-v5，覆盖12个图对象42个属性及15表251列反查；物理DDL未改。
- 人物姓名只批量回查配套SQL，人物边自身Rank不作源表主键，左右事实Rank才回查graph_edge_mapping；experience_key从明确来源原行派生，不是上游新增列。默认与可选详情分开，不把phone弃用列当有效联系方式或原表全字段默认开放。
- 本轮仅文档与独立覆盖／排版核对，无数据库或服务操作。旧v3.3候选及Word归档，当前映射以v5.0为准；源码／API仍v0.16历史模型。

## 目标图 DDL v0.22：业务编号与经历附属信息

- 用户要求重新整理字段，当前 uuid-relations-v5 = uuid-facts-v3.ngql + person-relations-v3.ngql。完整字段与来源以 docs/graph-ddl.md v2.0 为准；旧文件／报告保留。
- person(source_system,serial_number) 无姓名；company／school／major 各 name＋对应code。工作边增加 position_title 和 experience_key；学校／专业边各含 experience_key、education_level、is_regular_enrollment、start_month、end_month。统招保留STRING原文，不强转BOOL；职位原文不代表职位已归一。
- experience_key=source_system:source_table:raw_row_id，用于具体经历归组；同条教育的学校／专业共用键与属性，不根据Rank序号或人物两段不同履历拼接。事实Rank仍=graph_edge_mapping.id，四类人物边结构不变。
- scripts/verify_person_relation_ddl.py 当前验证v5，报告 docs/data-sources/person-relations-v5-business-native.json；每空间12项通过，15／11条关系不变，空间已清理，无MySQL／Supabase或服务变更。应用仍v0.16，旧图／writer与API未迁移。

## 历史 v0.21 业务附属信息需求

- 用户明确需要业务编号、工作信息、教育信息；姓名不入图不能扩大解释为禁止一切业务属性。建议见 docs/person-business-information.md；来源、证据、有效状态、日期与版本基础信息继续复用。
- 业务编号可作为 person 候选属性，工作／教育按具体经历绑定；职位、学校、专业、学历、任期不能从不同经历拼接或用人物单值替代。地区、工作年限等按业务查询决定，不默认补全或整行入图。
- 本轮只做需求与位置澄清，未改 DDL 或验证模型；当前 uuid-relations-v4 仍只有人物 source_system 属性。不能将附属字段建议说成已写入或已验证，姓名禁入、SQL展示规则继续有效。

## 目标图 DDL v0.20：人物姓名不得入图

- 用户明确 person 不能存姓名，只能回 MySQL 查询后展示。当前模型 uuid-relations-v4 = 新 uuid-facts-v2.ngql + 保留 person-relations-v3.ngql；person 仅 source_system STRING NOT NULL，VID 保持来源型键。撤销 person.name 展示冗余，其他个人附属属性不加入，不用姓名缩写／脱敏名／散列或自由文本绕过。
- 图返回人物标识与关系，API 按来源批量回查 MySQL 姓名后装配展示 DTO，不反写图；姓名搜索在 SQL，不以图存姓名兜底。生产权限／API／日志导出链路尚未验证，不能称不存姓名就完全匿名。
- scripts/verify_graph_ddl.py 当前使用无姓名 uuid-facts-v2；scripts/verify_person_relation_ddl.py 当前验证 uuid-relations-v4，复用 v3 人工关系基准。报告 docs/data-sources/person-relations-v4-privacy-native.json，各空间9项通过，A 15／B 11 条关系不变，空间清理；未访问 SQL／Supabase 或切换服务。
- 旧 v0.16 writer 和已发布模拟图仍可能含虚构姓名，本轮未清理，不得用于按新隐私要求接入真实人物。规则及后续边界见 docs/graph-privacy.md；当前 DDL 见 docs/graph-ddl.md。

## 历史目标图 DDL v0.19

- 用户提出补充同专业，当前模型 uuid-relations-v3 = 基础 uuid-facts-v1.ngql + person-relations-v3.ngql，四类人物边含 same_major。旧 v2 定义与报告保留，后文“不以专业生成关系”仅为历史范围。
- same_major 根据两个有效 studied_major 指向同一标准专业 UUID 生成，不要求同校／同期／教育日期，不按专业名或岗位猜测；三属性 entity_vid、left_fact_rank、right_fact_rank，复用局部关系 Rank 和双向读取规则。独立同校＋同专业不能直接证明属于同一原教育经历。
- scripts/verify_person_relation_ddl.py 当前验证 v3；人工基准 docs/examples/person-relations-v3-expected.json，报告 docs/data-sources/person-relations-v3-native.json，A 15／B 11 条证据及每空间7项检查通过，空间清理；无 MySQL／Supabase、API／前端或服务迁移。规则及字段以 docs/graph-ddl.md 为准。

## 历史目标图 DDL v0.18

- 用户补充：人物之间的关系必须在入图阶段计算并保存，替代仅事实入图、查询时生成直接关系的目标。当前模型 uuid-relations-v2 = uuid-facts-v1.ngql 基础定义 + person-relations-v2.ngql；当前规则见 docs/graph-ddl.md 与 docs/person-relation-materialization.md。
- 新增 same_company／company_overlap／same_school，均 person→person，只按 VID 小到大存一次，双向查询；每条保存 entity_vid 和左右事实 Rank，同期边再存非空交集月份。人物边 Rank 是同人物对／类型内的快照局部证据序号，不是源表 id；SQL 用 left_fact_rank／right_fact_rank 回查 graph_edge_mapping。
- 入图后从事实边用 nGQL 计算，再写人物边；Python 编排不重算关系。多经历保留多证据，人物去重；同公司同期是同公司的子集，不累加评分，不推断实际认识，不以专业生成关系。最多一位中间人物沿两条人物边查询。
- 事实／派生边都完整核对才 ready；失效、目标／归属／日期纠正与基准月变化须重算。先估算热门实体平方级人物对，预算不足不能截断后标完整。生产构建器／增量与容量待验证。
- scripts/verify_person_relation_ddl.py 仅管理本次新建临时空间，小样例 A 14／B 10 条证据边符合 docs/examples/person-relations-expected.json 的人工完整预期，全部回读一致，空间已清理。无 MySQL／Supabase 调用或服务变更；运行应用仍 v0.16，新 API／清单未迁移。

## 历史目标图 DDL v0.17（基础事实定义保留）

- 2026-11-06 用户要求确定节点与边的物理定义。目标模型 uuid-facts-v1 以 infra/nebula/schema/uuid-facts-v1.ngql 和 docs/graph-ddl.md 为准；旧字段规范每边 11 属性和通用 entity TAG 是历史候选，不继续作为新模型目标。
- 四类业务 TAG：person(name,source_system)、company(name)、school(name)、major(name)。人物 VID 保持按来源，实体 VID 保持 e:<UUID> 并检查跨类型冲突；不重复存 id／kind／active。
- worked_at(start_month INT32 NULL,end_month INT32 NULL,is_current BOOL NOT NULL)；studied_at／studied_major 各两个可空月份。边 Rank=graph_edge_mapping.id，来源属性回查成对冻结的 SQL，图仍计算关系／路径。专业不新增人际关系，不顺带增加职位／项目／层级边。
- projection_meta 控制节点记录模型、投影、摘要、基准月与 staging／ready；无默认属性索引或 TTL。端点类别、VID／枚举、月份／区间、稳定 Rank 和发布范围依赖构建前预检，不假称 DDL 已强制这些约束。
- scripts/verify_graph_ddl.py 只用新建随机 relationship_lab_ddl_ 空间，结束只清理自己创建的空间，不覆盖报告、不重置凭据或服务。专项 10 项已通过，docs/graph-ddl-validation.md 记录失败和范围；没有 MySQL／Supabase 操作。运行应用仍 v0.16，未实现新源适配／API／清单迁移。

## 最新表设计优先级 v0.16.4（来源规则继续有效）

- 2026-11-06 用户确认最新依据为《人物关系图谱MySQL表结构设计说明_映射表精简版(3).docx》，替换(2)；旧独立三表方案继续废弃。
- 标准表为 graph_company_entity／graph_school_entity／graph_major_entity，UUID 主键，已删除 entity_key。名称映射统一为 graph_name_mapping，用户确认并在最新 Word 补回 is_deleted，字段表共 12 列；来源键为 source_namespace＋source_field_id；无 raw_name／item_no／source_record_id。is_deleted 为 TINYINT UNSIGNED NOT NULL、默认 0，仅 0／1。文字仍有旧列和旧表名残留，不能据此虚构其他字段。
- graph_edge_mapping.standard_entity_id 最新文档已写为 CHAR(36)，与目标主键一致；id 保留 BIGINT Rank。不建设独立实体／别名词典、不自行归一或恢复 UUID→BIGINT 实体桥接。
- 用户已确认简历原表与已提供专家 DDL 一致，expert 对应改为 resume，类型／空值／默认规则沿用；不重复要求确认同一结构，不把结构确认当跨库人物统一或真实数据可用的证明。
- 上下级 JSON 数字 0 同时表示确认无关系与未知；不再沿用旧三态解释，SQL NULL 的语义仍待确认。有效映射须同时已匹配且 is_deleted=0；删除标志为 1 不投影有效边，不自动删除人物或实体。生产删除通知／恢复／发布仍待确认，不根据处理中缺行清边。
- 新基线仅 worked_at／studied_at／studied_major，实体 VID 暂按 e:<UUID> 并检查跨表冲突、entity.id 使用 STRING。图计算关系／路径、SQL 回查来源方向不变，职位／项目不按旧样例默认投影。
- 本轮只维护文档：主架构 v0.16.4，字段规范 v3.3；15 表 251 列。运行代码仍 v0.16，新模型未建表／投影／联调，不覆盖现有 SQL／图、清单或服务，不访问 Supabase。下文历史约定仅对应当时实现。

## 第一阶段实现约定

- 当前为本地 FastAPI＋同步 SQLAlchemy 原型，默认 SQLite，可选本机 MySQL；前端 Vue 3＋Element Plus＋G6。v0.13 配置图投影后默认图内计算有界连接链，SQL 提供来源详情；无图配置保持 SQL。Redis 和生产同步 Worker 尚未接入。
- 后端安装、运行和检查均使用 `backend/.venv`；依赖由 `backend/uv.lock` 与 `frontend/package-lock.json` 锁定，不使用全局 Python 包。
- Pydantic 契约是接口类型来源，运行 `bash scripts/generate-api.sh` 生成 OpenAPI 与前端类型，不手改生成文件。
- 初始化保留已有数据；仅显式 reset 重置演示表，不把演示库指向真实业务数据库。
- 完整检查入口为 `bash scripts/check.sh`，启动入口为 `bash scripts/dev.sh`。服务只监听本机，结束时回收本次创建的子进程。

## v0.4 接入准备与正确性

- 数据交接说明为 `docs/data-handoff.md`，当前没有正式新表或结构说明。逻辑样例不约束上游 DDL 或文件格式。
- `validate-dataset --input` 必须保持只读，只输出 JSON 报告；初始化与预检复用 `domain/validation.py`，校验错误须在建表／写入前阻断。
- 人工预期为 `backend/tests/fixtures/query-cases.json`，不得用生产查询输出自动覆盖期望。独立基准不得调用生产查询、时间或证据函数。
- 500 人差分及快照修正使用隔离临时库；修正前停止旧服务生命周期，新版本启动后旧游标应失效。不将演练描述成生产增量链路。

## v0.5 查询与展示扩展

- v0.5 已实现两人对比、月份时间轴和公司／学校／职位多选；间接路径范围已由后续 v0.7 约定扩展，继续本机虚构数据模式。
- 多选类别内 OR、类别间 AND，公司／职位／任职时间仍匹配同一经历；旧单值字段合并到同类列表，排序去重后的集合绑定游标。
- 对比接口返回双方事实和后端证据；时间轴只转换展示位置，不重新计算关系。未知日期独立展示，同校不推断同期，不累加多条证据的重叠月份。
- 本轮没有数据库迁移，不能为启用新功能而重置已有演示库。架构持续维护于 v0.5 及后续版本。

## v0.6 专题、条件与导出

- 公司／学校专题使用独立条件，固定标准实体，复用查询分页；当前页人数不得标作在职人数或全库总数。
- `relation_*` 字段约束实际共同经历，旧背景字段保持候选背景语义；同期阈值按单条经历对在所选窗口内计算，不求多条累积。
- 范围内证据用 POST 查询并复核候选条件，原 GET 与两人对比保持完整证据；SQL、摘要、图和导出的关系规则必须一致。
- 本机只保存条件及版本，恢复后重新校验查询第一页；不保存游标和结果。导出严格为当前页，核对版本和人物，区分完整有效履历与筛选内关系证据。
- JSON／CSV 和 PNG 都保留模拟标识与范围；PNG 是局部图，不是完整列表。不得为此升级重置演示库或增加全量导出、外部数据库及账号系统。

## v0.7 有界连接链

- 用户已授权最多一位中间人物的连接链，取代早期仅直接关联的范围。没有任意深度、职位中间节点或全局推荐排名。
- 复用 RelationScope、SQL 关系对条件和证据规则，每段分别核实时段，不要求三人同期，不推断实际认识或可引荐。
- 候选、路径、事实、证据、时间、SQL VM 和 Python 核对均有预算。无结果且预算耗尽返回 limited，不能伪装为 not_found；真实存储故障保持错误响应。
- search_complete 表示中间人物连接存在性的核对完成，不等于每段证据都已完整展示；始终检查 truncated 和原因。图只转换选中链的后端证据。
- SQLite progress handler 只能在请求借用连接上设置，退出必须清除并回滚；前端取消请求不等于服务端同步工作立即终止，不承诺 HTTP 硬 SLA。
- 本轮不改数据版本／结构、不重置演示库；旧保存和导出范围保持 v0.6，路径暂不保存或导出。主方案维护于 v0.7 及后续版本。

## v0.8 R01 规模观察

- R01 已选定并完成，报告为 `docs/performance/r01-results.md`，原始接口及浏览器记录同目录；其余路线图方向仍是候选。
- 新入口为 `scripts/benchmark_scale.py` 与 `scripts/benchmark_browser.py`，必须使用 backend/.venv；旧 2000 人 benchmark 命令保留。新文件／报告不覆盖，禁止向默认演示库生成规模数据。
- 当前为隔离 SQLite 顺序 ASGI 请求和 Vite 浏览器观察，不代表生产并发或百万级容量。首次观测不等于系统冷缓存，嵌套阶段不能相加，VM 指令不等于扫描行数。
- 热门路径用最多 513 条索引记录探测选择 JOIN 或按 ID 的 EXISTS；谓词、来源、排序及业务预算保持一致。阈值只为原型调优，必须继续用独立集合及冻结参照验证。
- 诊断默认关闭、上下文隔离；观察器不能覆盖路径业务 progress handler，退出必须清理。长履历对比约 18 MB 响应仍保留完整证据，禁止为了数字好看静默裁剪。

## v0.9 本机 MySQL 验证

- 此阶段用户授权使用现有本机 MySQL；当时没有可用图数据库，Linux 测试服务器目前不可用。v0.9 先验证 MySQL；后续 v0.10 已按用户新请求建立图环境。现有 Canal 未接入。
- `RELATIONSHIP_MYSQL_URL` 只允许本机 `mysql+pymysql` 与 `relationship_lab_` 前缀库；API 会话只读，连接池 5、无溢出、等待 3 秒。实验结果仅覆盖实际 MySQL 9.7.1，不推定公司其他版本通过。
- `scripts/mysql_lab.py` 从独立 SQLite 快照创建新库和新输出目录；先分批校验，只读源快照事务，完整写入后发布元数据；拒绝覆盖。MySQL 不支持 CLI init/reset，不改变默认演示库。
- SQLRepository、SQLPathReader 和 read_model 共享两引擎规则，SQLite 历史导入保留。MySQL 热门关系用 513 条事实探测加子查询 NO_SEMIJOIN 提示；稀疏关联保留常规计划。阈值和提示都需在正式版本／分布重评，不调整全局 optimizer_switch。
- MySQL 路径只在借用连接上注入剩余 MAX_EXECUTION_TIME，退出移除监听并回滚；仅错误 3024 转换为 time_limit，断连等保留错误。SQLite VM 保护不模拟成 MySQL 扫描行数。
- MySQL 测试需显式 `RELATIONSHIP_MYSQL_TEST=1`，仅创建并清理本次随机临时库。规模报告见 `docs/performance/mysql-results.md`；图、Linux、并发负载与生产增量仍待验证。

## v0.10 独立图数据库环境

- 用户已授权建立本地图数据库环境。`infra/nebula/compose.yaml` 固定 NebulaGraph 3.8.0 ARM64 镜像摘要，单 Meta／Storage／Graph，单副本实验空间，独立网络和命名卷，只发布 127.0.0.1:19669。
- `bash scripts/nebula.sh up|status|stop|down` 管理本项目容器；stop/down 保留卷。不得用 down -v、系统 prune 或停止其他容器来重置环境；现有 MySQL／Canal 保留。
- 首次 Storage 需由 Graph ADD HOSTS 注册；启动不能依赖 Storage 先健康。按实际 OrbStack 使用独立 bridge 网络，不能照搬 internal 网络而忽视端口不可达。
- 启用认证；本机随机凭据仅存 data/nebula-lab/credentials.json，600 权限，不输出。已 bootstrap 的凭据失败不回退默认密码或自动重置；DDL 和密码传播等待限时且只重试明确状态。
- 环境 SDK 3.8.3 锁定在 backend/.venv，RPC 超时 15 秒、池上限 2；这是初始化／验收参数，不是业务路径预算或 HTTP SLA。
- `scripts/nebula_lab.py` 仅 bootstrap/check/smoke/verify；新建 relationship_lab_ 空间验证虚构事实，不提供任意查询入口。专项测试显式 RELATIONSHIP_NEBULA_TEST=1，只清理本次创建的测试空间。
- v0.10 结束时仅完成环境；业务图接入由后续 v0.11 约定扩展。不能把环境就绪描述成生产图查询已上线，不能据此冻结生产图模型。

## v0.11 不可变图投影与有界候选

以下为历史候选实现；v0.13 已替换配置图后的默认路径引擎，版本／权限／快照约束继续有效。

- `scripts/graph_projection.py` 从独立模拟 SQLite 快照新建图空间、回读对账后发布 manifest；只读源数据，拒绝覆盖。失败批次没有 ready manifest，不自动修复或续写旧图。
- 业务 API 仍由 SQL 负责人物筛选／展开、事实和证据。仅 PathService 的候选可选 GraphPathRepository；由 SQL 资格谓词和 Domain 逐段复核。RELATIONSHIP_NEBULA_MANIFEST 显式开启，取消该选择恢复原 SQL。
- 不可变空间内 VID 有命名空间并校验 UTF-8 字节长度；rank 按每人完整事实 ID 排序分配，事实 ID 为权威引用。跨批次可重新分配 rank，不将其用作跨版本经历键。
- 人物邻接、每实体 128 人的有序成员块是临时图读索引，不预计算全库人物对。最多 64 个参考实体、20000 图返回行、256 次图请求；SQL／时间／证据预算保留。块校验和、数量／顺序异常报错，不当作无关系。
- 图读取采用每投影独立 GUEST 账号，凭据在 manifest 同目录 reader-credentials.json，600 权限。运行时每次 RPC 单独回收 SDK 池、按剩余预算设超时，进程内并行 RPC 上限 4。SDK 超时不等于立即取消服务端执行，不承诺 HTTP 硬 SLA。
- 启动核对 SQL 版本、基准月和全量逻辑摘要；每次路径查询前后核对图 ready 标记／批次。运行中不修改任何已发布 SQL／图快照；同版本原位修改也不受支持。切换批次须停 API、更换成对配置后重启。
- 图故障返回 503，批次不符返回 409，不静默回退 SQL。图读取预算不足保留已核实结果并标 graph_limit；原候选、路径和证据限制继续生效。
- 已做 1 万人模拟投影／对照，见 docs/graph-query-validation.md。当前实验图辅助比纯 MySQL 慢，保持显式选择；不得称为图数据库加速已验证，不外推 10 万／百万级生产容量。
- 专项 RELATIONSHIP_GRAPH_TEST=1 只管理自己新建的空间／账号。逻辑快照共享校验、摘要在 infrastructure/snapshots.py；初始化／读模型 SQL 保持兼容，不重置默认库。

## v0.11.1 候选 Supabase 归一源评估

- 2026-11-04 已通过 MCP 只读核对 company-resolution-test 的 public 5 表／5 视图；结构和聚合证据见 docs/supabase-source-assessment.md。当前为持续处理的归一数据，不是冻结交付。架构文档 v0.11.1，业务代码仍 v0.11。
- 用户确认归一结果与原经历分别取得，职位归一目前未定。原工作／教育需回连人物、时间、状态及来源；original_database_id 是原记录候选键，不是人物键。尚未验证简历覆盖。
- company→organization、school→school；major 不替代 role，不据专业目录推断个人学历。组织上下级不自动扩大同公司关系，子／分公司保留独立实体。
- 以稳定 UUID／来源命名空间追溯，处理原记录多映射与实体合并，不按原记录取第一条、不将岗位／日期无条件复制给拆分公司。缺原 ID、待确认记录不能自行挂到人物。
- 源 ready_for_export、batch_no 和 updated_at 不代表完整人物数据发布或删除契约。先核对最终筛选与冻结版本，再实施适配、只读预检、人工对账和独立查询快照。
- 当前没有 PostgreSQL 运行仓储；MCP 可读不等于应用已接通。仅授权评估不顺带修改云端表／数据／权限或部署同步，不放宽既有 MySQL 本机实验限制。
- 现有 data_mode 固定 mock；正式接入需同步扩展契约、前端及导出模式／版本标志，不能只将真实数据装进原模拟库。源 UUID／entity_key 跨批次稳定性仍需上游确认。

## v0.12 严格只读来源样例演练

- 用户明确当前源库仍在处理、字段会筛选，不以当前物理结构为正式契约。仅为演练从 Supabase 做一次限量基础表 SELECT，之后全部离线；严禁修改云端数据／结构／权限／配置，不为验证而调用云端写入或未知函数。
- 采样 SQL、冻结文件、本轮调用记录为 docs/examples/source-trial-* 与 docs/data-sources/source-trial-cloud-read.json。它是本轮操作记录，不是全库审计；同事处理造成的数据变化不归因于本轮。
- scripts/source_trial.py 仅消费本地 JSON，新输出目录生成 mock-source、Dataset、追溯、问题、预检和独立 SQLite。当前字段转换只在 source_trial.read_seed，不建设 PostgreSQL 后端或通用采集框架。
- 真实归一实体用于模拟；人物、归属、任期、职位、来源标记及 mock-map 全部虚构，mock-raw／trial 前缀隔离原库 ID。采样映射只做结构检查和模板线索，不能挂真实原记录到虚构人。
- 多目标不猜测；同目标重复映射保留追溯后合并事实。专业不作职位，母子公司不自动作同公司。缺少正式字段不阻塞本轮补造虚构经历，不把样例通过记为正式接入完成。
- 三模式验收显式 RELATIONSHIP_SOURCE_TRIAL_DIR 配匹配本机 MySQL 与图 manifest；默认回归仅离线和 SQLite，原演示浏览器不加载新样例。专题初始化需选择当前有效实体，不能依赖 org:0 一定存在。

## v0.13 图内关系与路径引擎

- 用户确认图负责关系／路径，SQL 提供人物与经历来源。本轮落实到 /api/v1/relations/paths 的直接和一位中间人物连接；普通人物列表、专题、完整对比及导出仍 SQL，不宣称全部迁移。
- 配置 RELATIONSHIP_NEBULA_MANIFEST 后 GRAPH_ENGINE（完整名 RELATIONSHIP_GRAPH_ENGINE）默认 paths，响应 nebula。candidates 明确选择旧辅助引擎才返回 nebula_sql；无自动回退，无图配置保持 SQL。
- NativeGraphReader 的 nGQL 计算有效性、来源、共同实体、关系类型和单条经历对时间；GraphPathService 仅按图的事实 ID 取 SQL 来源并做属性完整性核对，不调用 SQL 候选／资格或 Python overlap/build_evidence 重算路径。
- 候选先去重实体邻接再 128 人游标分页，图内资格匹配后保持 ID 前缀；已知两端分别从人物读取经历。保留 64 参考实体、20000 返回行、256 RPC 和原预算；这些不等于图服务端扫描上限或即时取消。
- 复用既有 format_version=1 投影，无迁移／重置；只读账号、不可变成对快照、批次前后校验和故障分类不变。图证据属性不符返回 GRAPH_INTEGRITY，不静默修复。
- 验收与失败观察保存在 docs/graph-native-validation.md。本轮不访问 Supabase，生产容量与图加速仍待验证；benchmark_graph.py 遇图错误或 time_limit 停止后续场景，保留部分记录。

## v0.14 六表来源及三表／原表验证

- 用户确认六表为上游归一来源，三表为本项目词典／投影层；已提供专家主表及三类经历 DDL，Resume 按 expert→resume 模拟。真实数据、正式简历 DDL及发布规则仍待确认。最新证据见 docs/handoff-schema-validation.md 与 docs/projection-three-table-validation.md。
- handoff_schema.py／handoff_trial.py 与 scripts/handoff_lab.py 只管理新本机实验库，采用正文 graph_expert_name_mapping 名称，映射14字段。公司上下级数组／JSON数字0／SQL NULL不混用；专业不作职位，不按名称合并实体。
- 六表回读后复用现有 Dataset／预检及查询读模型；原履历明确补造。多目标不复制同一职位／日期，item_no 不作跨版本键或学校专业配对。新原文与映射不符必须定位，不自动修正。
- 新三表试验为 scripts/projection_source_lab.py，实际原表形状来自 docs/examples/expert-source-tables.sql，缺少的治理和匹配只用显式模拟样例。桥接 JSON 与初始编号不是正式 UUID→BIGINT持久定位或生产 ID 分配器。
- 三表槽位键 source_system/source_table/source_field_id/source_field，人物或目标变化不换槽位ID。ID为有符号64位正数，图Rank沿用该ID。原人物按来源分别生成VID，不自行跨库去重。
- 新实验 source-slot-lab-v2 与现有 API format_version=1 分开。lab-manifest.json不能作为 API 图配置；未替换当前图服务，也未建设增量Worker、在线旧边清理或新关系类型的业务查询。
- 文档缺少的合并指向、消歧属性、匹配审计与发布状态不擅自当作已定字段；继续图计算关系／SQL提供来源，不因文档写回源计算就恢复SQL重算。
- 新实验连接仅设置会话严格模式与UTC，不改变全局MySQL配置。实测可空后缀复合外键索引漏检，候选改用单列entity_id支持索引；其他目标版本需复测，应用预检仍是发布门槛。
- UI同名实体选项显示名称＋ID，提交值始终为ID。唯一名称不变；接口类型仍从OpenAPI生成，不引入上游DDL到业务Service。

## v0.15 原表／三表 API 与展示集成

- source-slots-v2 通过 RELATIONSHIP_SOURCE_API_MANIFEST 与 RELATIONSHIP_SOURCE_API_MYSQL_URL 显式启用，仅本机 relationship_lab_ 模拟库；默认 SQLite、旧 MySQL 和 format_version=1 图模式保留。不能混用配置或缺少清单后静默回退。
- scripts/source_api.py 只读复核已有实验 SQL 与完整预期图，再在新目录发布 format_version=2 清单；旧 lab-manifest.json 仍不能直接作为 API 清单。输入库、图空间和已有文件均不写入；本轮无 Supabase 调用。
- SourceRepository 通过八张原表、三表映射的 SELECT 子查询复用 QueryTables／SQLRepository／SQLPathReader，不创建物理事实表或视图，不要求生产额外建立 person／fact／relation。字段转换留在 infrastructure/source_read_model.py。
- 新人物 ID 保留 p:expert:<id>／p:resume:<id>，实体 API ID 是 BIGINT 字符串；slot:<映射主键> 对应 Rank 与源表行。职位仍来自同条工作经历，专业／项目不增加人际关系，跨库人物身份仍由上游负责。
- 新图配置下连接链由 worked_at／studied_at 的 nGQL 计算；SQL 不搜索候选或重算路径。Rank、源表／行／字段、端点和经历属性须核对。普通筛选、相关人物列表、专题、对比、展开和导出继续 SQL／Domain。
- 源 SQL 会话只读、严格模式、UTC，图用 GUEST；发布和请求前后完整摘要检查是小样本约定，单表 10000 行上限，不作为生产性能策略。原位修改不支持，漂移 409、图故障 503；保留预算与截断语义。
- 原表模式拒绝 init/reset，dev 不初始化默认 SQLite。先停服务，再换完整成对快照和清单；没有新增生产增量、在线旧边清理、持久桥接或 ID 分配器。
- 新来源专项需 RELATIONSHIP_SOURCE_API_TEST=1；浏览器需 RELATIONSHIP_SOURCE_API_BROWSER=1，加载匹配配置。独立原表基准不调用生产适配／时间／关系函数，期望不由查询结果自动生成。证据见 docs/source-api-validation.md。

## v0.16 修正与停服版本切换

- 用户要求先做修正与版本切换，并提供稳定标识／发布待确认问题。本轮只对冻结模拟 A 的内存副本应用明确指令，另建 B SQL 库和图空间；原 A、既有演示与已发布文件不覆盖，Supabase 不访问。
- CorrectionPlan 绑定完整源摘要、行键和原值条件，不改主键或来源槽位键；必须在创建新库之前检查引用、归属、时间和完整槽位。公司／学校纠正和人物移归属消费明确模拟上游结果，不重新识别身份或模糊归一。
- 完整图键为起点／终点／类型／Rank；稳定 Rank 不等于旧边已删除。新图完整重建验证旧键消失，旧图保留用于回退，不宣称生产增量旧边清理已实现。
- source_release.py 激活／回退仅在开发端口 8000／5173 可独占时执行，文件锁内完整核对候选 SQL／图，再原子替换单一 active.json；失败不改变当前指针。不会自动停止其他服务。
- RELATIONSHIP_SOURCE_RELEASE_STORE 显式选择激活目录，不可混用旧源或直接清单配置。API 固定启动时修订与文件摘要，请求前后漂移返回 RELEASE_CHANGED 409；必须停服换批次。init/reset 拒绝此模式，dev 不初始化默认演示库。
- 回退前重新核对旧 SQL／图和原配置摘要。激活后启动失败需显式 rollback，不自动热切换；状态记录是本机操作历史，不是生产分布式事务或不可篡改审计。
- 数据版本绑定内容与基准月，激活修订单独记录。A 游标在 B 无效，回到同一完整 A 后可重新有效；不宣称所有历史游标永久失效。
- 原生切换专项需 RELATIONSHIP_SOURCE_RELEASE_TEST=1 与 RELEASE_A／B（完整环境名 RELATIONSHIP_RELEASE_A／B）；修正 B 浏览器需 RELATIONSHIP_SOURCE_RELEASE_BROWSER=1。真实 HTTP 演练入口 scripts/rehearse_source_release.py，每次新输出，回收本次服务。
- 稳定键、UUID→BIGINT 持久桥接、人物跨库、多目标、删除通知、批次完成和历史保留仍待确认。可转发清单 docs/stable-identifiers-and-publishing-questions.md，验收 docs/source-release-validation.md；不冻结生产 DDL／增量契约。
