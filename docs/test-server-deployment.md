# 双服务器测试部署步骤与命令

版本 v1.10，2026-11-13，对应主架构v0.59.5，应用规则沿用v0.44。

## v1.10 当前提测部署

应用服务器121.43.176.65，目录/srv/relationship-map，图服务器内网地址172.16.0.154。查询API由relationship-query.service托管，127.0.0.1:19669的图入口由relationship-graph-tunnel.service转发。Nginx8088提供网页及API，当前静态根为frontend/dist-layout-v059-label-fix，入口index-B_uaB6X5.js，图组件GraphCanvas-6K1ga1Xw.js。

实际关系版本real-921e1ee2e6476b0925bb-202611已通过夜间发布，包含6711专家／27715事实。人物展示为mysql-live，姓名／业务编号搜索、分层图、四跳聚焦、导出和手机触摸已完成指定真实样例公网复验。三个服务active，nightly timer每天04:30 Asia/Shanghai执行，下次为2026年11月14日。

提测源码标签为qa-20261113-02。每次提测通过Git提交号和标签定位代码版本，部署时记录对应版本及前端入口。当前代码版本查看方式、部署入口和数据版本见[项目README](../README.md)。

环境凭据通过/etc/relationship-map/mysql.env管理，query.env指向当前发布目录，nightly.json管理夜间任务。前端使用服务器npm构建，历史资源随新静态目录保留以兼容已有页面。部署操作的阶段记录及命令保留于下文，当前状态由[主方案](query-system-architecture.md)维护。

## 历史部署记录

## v1.9 在线人物与自动输入部署验收

用户已逐步反馈v0.57补丁安装、私有凭据配置、EnvironmentFile接入和查询服务激活成功。实际API为mysql-live，3位人物原表字段比对通过，prepare-input瞬态任务完成6525人物／25241事实的新输入。定时器已恢复，下次2026-11-13 04:30 CST，三个运行服务active、timer与recover均enabled、真实API健康。首次完整自动采集、建图、切换仍待夜间执行验收，完整过程与范围见docs/live-mysql-and-nightly-input.md。

## v1.8 在线人物和自动采集补丁

用户已反馈v0.56源码、来源／夜间配置、输入准备、Nginx维护入口及systemd任务部署完成，timer和recover均enabled，首次定时运行原计划2026-11-13 04:30。用户进一步要求将人物在线展示及自动采集接入服务器，v0.57补丁已在本机实现并验证，实际服务器新补丁待上传。

部署前暂停夜间timer并核对当前任务状态，备份源码和实际配置，安装补丁后执行scripts/configure_server_mysql.py，通过隐藏输入准备私有mysql.env。随后安装query drop-in及新版nightly unit，核对API在线人物模式和实际原表字段，执行prepare-input验证自动输入，最后恢复timer。完整步骤及实际范围见docs/live-mysql-and-nightly-input.md。当前现有SSH密钥认证失败，继续用户终端逐步反馈。旧版本部署记录保留于以下章节。

## v1.7 夜间发布功能待部署

用户指定北京时间每日04:30、最多90分钟。夜间发布器、Nginx维护页面／API503及systemd定时／恢复模板已实现，使用docs/examples/nightly-release-config-v1.json。实际操作与功能范围见docs/nightly-release.md。

上传时同步nightly.py、nightly_host.py、pyproject.toml及uv.lock，以及来源配置改动、infra/nginx／infra/systemd和示例。服务器uv sync --project backend --python 3.12 --locked --no-dev安装声明后的运行依赖，备份并核验维护站点，再配置nightly.json和新的冻结输入目录。先plan检查，随后在约定维护窗口进行实际更新／回退验收，通过后启用timer与开机恢复服务。

本机50项夜间专项、完整617通过／247跳过及原生Nginx／Nebula演练通过，systemd249完成解析检查，服务器真实服务启停待验。当前夜间入口消费已准备输入，CDC输入供给和在线人物MySQL继续待接入，本轮未改变当前服务器运行状态。

## v1.6 来源连接配置

本机采集入口已支持--source-config，格式为real-mysql-source-config-v1，示例docs/examples/real-mysql-source-config-v1.json。实体／映射与人物／经历角色分别引用连接名，正式同库可引用同一连接。密码交互输入或使用password_env引用，TLS CA路径按配置文件目录解析。旧--person-database命令继续可用。

后续部署需同步新增backend/src/relationship_query/update/source_config.py及更新后的scripts/capture_real_graph_sources.py，服务器私有来源配置可放/etc/relationship-map/sources.json。当前服务器还运行原源码包，本轮未上传改动。实际采集前配置对应CA、账号和来源，并指定新的冻结目录。正式实例切换需新建一致性快照／CDC基线，图及在线人物来源配置配套更新，沿用夜间停服及失败回退流程。

本轮23项新增离线回归、后端567通过／247跳过及Ruff／Mypy通过，真实合库和自动夜间更新尚待验证。

## v1.5 后续夜间版本更新已确认

用户确认夜间可暂停查询并继续版本化发布。后续在指定维护窗口检查待发布范围，进入维护后排空请求、暂停relationship-query，在独立候选空间构建及核验事实／关系和完整发布材料。完成后切换发布配置、启动单API并通过启动／health／meta核对，再恢复入口。失败恢复上一完整发布，CDC采集与图隧道独立托管，成功后按保留策略清理历史空间及失败尝试。

夜间具体时间、频率及维护时限尚未指定，当前未创建定时配置或执行停服。自动单源CDC、在线人物MySQL、真实更新发布格式及调度恢复仍待实现。本节为确认的后续部署方向，以下v1.4及更早保留实际部署验收历史。

## v1.4 当前实际部署与验收

应用服务器121.43.176.65与图服务器172.16.0.154均已按用户root会话完成部署。应用目录/srv/relationship-map，Python3.12.14项目虚拟环境、单worker API127.0.0.1:8000、systemd SSH转发127.0.0.1:19669及Nginx8088已运行。NebulaGraph3.8.0使用relationship-nebula-test独立Compose项目，原生监听绑定图服务器loopback，图空间relationship_lab_sync_7bb2f3daef15已完成全量及GUEST四跳核对。

用户反馈修复版前端已在服务器构建并切换至/srv/relationship-map/frontend/dist-http-save-v1，Nginx校验与重载成功，当前入口assets/index-jdcDm5My.js。配置备份/etc/nginx/conf.d/relationship-map.conf.before-http-save，源码备份/tmp/relationship-map-useSavedQueries.before-http-save.ts，候选包含旧assets以支持已打开页面的资源请求。

助手实际公网HTTP14次业务检查通过，随后最终公网浏览器4项通过，覆盖保存恢复、关系及证据、导出、公司筛选、分页、手机详情与同校前提路径。实际公网截图目录data/test-server-deployment/20261111/browser-20261112-final，桌面四跳及手机路径截图已查看，手机路径截图记录请求加载中界面。GraphCanvas分块体积提示保留，生产容量和长期运行待验。

当前查询使用冻结真实发布data/releases/test-20261111-v1。用户要求继续考虑源MySQL更新接入，代码差距与实施顺序见主架构v0.46及mysql-change-sync-design.md v1.6。双源持续采集、微批自动发布及其systemd入口待实现和部署。

以下保留逐步部署历史及Ubuntu22.04／24.04、deploy账号的初版命令模板，当前路径、账号和服务状态以本节为准。

## v1.3 公网恢复与保存条件补丁

2026-11-12用户反馈公网已可访问，助手随后直接GET公网meta成功，并通过14次业务HTTP检查，覆盖1至4跳、同校前提正反例及跨教育行正例、两人路径、展开与导出。现有公网浏览器用例3项通过，第4项在保存常用条件时发现crypto.randomUUID is not a function。实际HTTP来源window.isSecureContext=false，randomUUID不可用。

已将useSavedQueries.ts的新记录ID生成为getRandomValues提供的16字节随机值的32位十六进制字符串，保存记录继续使用schemaVersion1及字符串ID。新增缺少randomUUID情况下保存与刷新恢复回归。本机构建、类型及格式检查通过，默认浏览器38通过／26跳过。以本机修复构建拦截公网HTTP页面的静态资源、调用真实已部署API，保存、刷新恢复、导出和路径验证通过，secureContext=false、randomUUID=undefined、控制台错误为空，桌面及手机截图已查看。该预览使用本机修复产物，服务器前端补丁待更新。

补丁交付data/test-server-deployment/20261111/http-save-fix/useSavedQueries.ts，4690字节。原源码SHA256为cf75d1e0e39caf73b92b0088021f77aecb74d0fe310ae7c50f8732495f3b8f0d，新源码SHA256为c8a5b82fd574178bfe78a1ab145e937973160113261897b5a1072144641281e9。后续按用户逐步反馈上传至应用服务器/tmp/relationship-map-useSavedQueries.ts，核对摘要并备份源码，在服务器构建候选目录frontend/dist-http-save-v1，候选保留旧assets后切换Nginx静态根并校验重载，最后重跑公网浏览器验收。用户反馈HTTP保存兼容修复源码已上传成功。下一步在应用服务器核对原源码与/tmp/relationship-map-useSavedQueries.ts的SHA256，将原源码备份到/tmp/relationship-map-useSavedQueries.before-http-save.ts，替换源码并npm run build -- --outDir dist-http-save-v1，生成候选前端目录。用户已反馈原源码和修复文件两份SHA256均OK，源码已备份并替换，服务器修复版候选构建通过vue-tsc／Vite7.3.7，耗时观察12.32秒，目录frontend/dist-http-save-v1，入口assets/index-jdcDm5My.js。下一步合并原dist/assets到候选并设置读权限，备份Nginx站点配置后切换静态根，nginx -t及reload失败时恢复备份并重载，最后读取本机入口及新bundle。激活及最终公网浏览器验收待反馈。

## 2026-11-12 公网访问待核对

2026-11-12用户反馈应用内浏览器访问http://121.43.176.65:8088/出现ERR_HTTP_RESPONSE_CODE_FAILURE。此前服务器本机页面及API代理均已通过，助手公网curl探测返回错误52，当前故障原因待核对。下一步先由用户在电脑Chrome或Safari地址栏访问同一HTTP地址，再在应用服务器读取三项服务状态、监听端口、使用公网Host头的本机HTTP响应、UFW状态及最近Nginx访问／错误日志。当前仅安排只读诊断，结果及公网和业务验收待反馈。

用户于2026-11-12反馈nginx、relationship-query和relationship-graph-tunnel均active，监听为0.0.0.0:8088(Nginx)、127.0.0.1:8000(Python)、127.0.0.1:19669(SSH)，本机带Host:121.43.176.65:8088的HEAD返回200／468字节，UFW inactive。最近访问日志含公网扫描与本机10:02:30的HEAD 200；现有日志格式未区分端口。用户补充的错误日志为11月11日启动／重载notice两行。下一步优先核对应用实例121.43.176.65所关联安全组的TCP8088入方向允许规则和授权来源，若缺少则按测试访问范围添加；安全组配置尚未取得，原因保持待确认。随后再次用电脑浏览器访问，公网及业务验收待反馈。

安全组操作依据[阿里云官方说明](https://help.aliyun.com/zh/ecs/user-guide/start-using-security-groups)。

## v1.2 当前逐步执行方式

按已反馈环境，NebulaGraph服务在Milvus服务器Docker独立部署，初始化、冻结输入构建及SQL对账由应用服务器既有Python3.12.14虚拟环境通过SSH转发执行。此流程替换v0.45初版在图服务器安装Python依赖并构建后回传整套发布的安排，应用服务器生成配套发布目录。用户已从应用服务器SSH到root@172.16.0.154，返回主机名iZbp1eoksk549i98rt6mawZ、nproc为8，ED25519指纹SHA256:9OPPpTzS/FfMr5aD+Gg9JyqjgQwUp/PCf8gfrWi2j+0已由用户确认并写入known_hosts。用户反馈compose.yaml已通过scp完整传到图服务器/tmp/relationship-nebula-compose-source.yaml，2612字节。用户反馈图服务器已生成/srv/relationship-nebula/compose.yaml，独立项目relationship-nebula-test，平台linux/amd64、restart=unless-stopped，移除原ARM64摘要并保留127.0.0.1:19669映射，Compose校验通过，metad／storaged／graphd的v3.8.0镜像均已拉取完成。用户反馈up -d已创建独立网络、五个卷及三个容器，metad为Healthy，storaged和graphd为Started。首次状态检查因容器curl不支持--retry-connrefused中断，参数已修正为现有healthcheck的curl -sf。用户随后反馈HTTP返回git_info_sha=7458486、status=running，Compose ps中graphd和metad均healthy，storaged为health: starting，宿主绑定127.0.0.1:19669。用户反馈应用服务器排除SSH_AUTH_SOCK、BatchMode=yes及StrictHostKeyChecking=yes的SSH验证通过，返回图服务器主机名，本机19669无监听。用户反馈relationship-graph-tunnel.service已enabled并active(running)，主进程ssh的PID为1925434，本机127.0.0.1:19669由同一SSH进程监听，转发目标为图服务器127.0.0.1:19669。用户已在应用服务器执行scripts/nebula_lab.py bootstrap和check，两次均返回storaged:9779为ONLINE、graphd:9669为ONLINE、Version=3.8.0、authentication=true。初始化期间SDK输出Closing a connection that is in use，随后两次查询均成功；凭据由程序在应用服务器data/nebula-lab/credentials.json私有保存。用户反馈服务器新图relationship_lab_sync_7bb2f3daef15已构建为verified，版本real-2a106af85a3330dba3c2-202611，19326节点、25239事实、331783关系证据、357022总边，validation.passed=true且all_graph_rows_verified=true，构建观察161.423秒。四类独立SQL逐证据计数和摘要与本机原发布一致，图摘要8e45c2f75957c2be30b00cd3eed0e4c305af8142328281745a199d46d270d43e。用户反馈verify_real_graph_queries.py的GUEST核对passed=true，中心p:expert:1076的1至4跳候选数1／2／3／4，逐段连接和SQL事实回查通过，单次小邻域顺序观察44.224／35.433／55.586／66.309毫秒。用户反馈应用服务器80／443／8000／8088无监听，curl为/usr/bin/curl，PATH未找到nginx，nginx服务inactive。下一步按当前root环境创建relationship-query.service，单worker监听127.0.0.1:8000，EnvironmentFile指向已验证真实发布目录，依赖SSH转发，开机启动并失败重启。用户反馈已写入query.env与relationship-query.service并enable --now，服务active(running)，主进程Python PID1925910，开始时间为2026-11-11 20:46:28 CST。用户随后提供journal日志，20:46:29 Waiting for application startup，20:47:03 Application startup complete并监听127.0.0.1:8000，该启动日志窗口约34秒。下一步直接读取health与meta，核对真实模式、版本、6525人物／25239事实及4跳能力。用户反馈HTTP health为status=ok、data_mode=real、版本real-2a106af85a3330dba3c2-202611，meta为6525专家、0简历、12801实体、25239事实、max_relation_hops=4、graph_model=numeric-relations-v1、relation_backend=nebula-materialized。用户提供的安装附件显示Nginx1.18.0(Ubuntu)、包1.18.0-6ubuntu14.22安装完成，9个新包、0升级，needrestart列出的服务重启被延后，最终nginx -v成功。下一步配置/etc/nginx/conf.d/relationship-map.conf，监听8088，静态根为/srv/relationship-map/frontend/dist，/api/转发至127.0.0.1:8000，规范前端产物读权限后nginx -t并启用／重载，再本机检查页面和代理meta。用户反馈nginx -t通过，nginx已enable并reload，本机http://127.0.0.1:8088/的HEAD返回200、Content-Type=text/html、Content-Length=468，代理/api/v1/meta返回预期真实版本、6525专家、25239事实及4跳能力。助手从本机执行公网HEAD及排除代理的GET /api/v1/meta，两次均收到curl错误52 Empty reply from server。公网可达性原因尚待核对，下一步由用户在本机浏览器访问http://121.43.176.65:8088并反馈页面或报错，再完成业务查询验收。网页、业务查询和完整验收待反馈；上述构建和查询耗时均属于当前冻结样本观察。

下文第3至11节保留初版双机独立构建模板，实际执行以本节及对话逐步命令为准。图服务器运行Docker服务，应用服务器通过SSH完成bootstrap和build-prepared并直接生成发布目录。初版模板的图服务器Python环境安装、整包复制及回传步骤为历史安排，按本轮逐步流程替换。

## 2026-11-11 交互部署进度

用户确认前端在应用测试服务器构建，后续每一步根据用户反馈给出命令。用户已反馈应用服务器为Ubuntu22.04.5 LTS、x86_64，当前登录root，内存7.1GiB／available4.1GiB、根盘40G／可用22G、无swap。Node显示v22.23.4，npm命令缺失，系统Python3.10.12，uv位于/root/.local/bin/uv，command -v未找到nginx。以上属于用户终端反馈，独立服务器连接及实机部署验收待执行。

用户进一步反馈/usr/local/bin/node指向/opt/node-v22.23.4-linux-x64/bin/node，dpkg未登记nodejs或npm。该Node目录的bin/npm和bin/npx链接存在，npm-cli.js文件存在。用户已在/usr/local/bin补齐npm和npx软链接并执行hash -r，两者版本均回查为10.9.9。用户回查uv为0.12.7，uv python install 3.12报告该版本已存在，经uv python find定位后执行版本查询为Python3.12.14。用户已回查默认python3为/usr/bin/python3、版本3.10.12。用户已反馈源码包上传到应用服务器121.43.176.65，已反馈服务器SHA256为OK、解压、backend/.venv依赖安装与前端构建完成，图服务器环境已获用户反馈，下一步验证应用到图服务器SSH。前端构建上传完整源码和锁文件，应用服务器安装依赖并生成dist。下文deploy账号及sudo为初版模板，现场执行命令按已反馈root会话逐步适配，实际服务账号在后续步骤核定。

实际交付源码包data/test-server-deployment/20261111/relationship-map-test-20261111.tgz已准备，7970799字节，179个归档项。包包含完整构建所需前端源码、锁文件、tsconfig及其测试引用、后端源码和锁文件、图构建程序及六份冻结输入。5份prepared文件摘要和SQL完整性通过，机器记录为同目录package-validation.json。用户反馈源码包已上传至121.43.176.65，sha256sum -c返回OK，已解压到/srv/relationship-map，data为700权限。服务器uv sync --project backend --python 3.12 --locked --no-dev已在backend/.venv创建Python3.12.14环境并安装35个包，uv pip check反馈All installed packages are compatible。用户反馈应用服务器npm ci安装199个包、vite7.3.7及vue-tsc构建成功，frontend/dist包含index.html与assets，构建观察12.50秒。GraphCanvas为1418.01kB／gzip411.80kB，带既有chunk体积提示。用户反馈图服务器为Ubuntu22.04.5 LTS／x86_64、root会话，内网地址172.16.0.154（另有Docker网桥172.18.0.1和172.17.0.1），内存总30GiB／available27GiB、根盘492G／可用456G、无swap。Docker29.5.3、Compose5.1.4已就绪，现有milvus-standalone、milvus-etcd及milvus-minio均healthy，存活端口检查9669／19669为空。系统Python3.10.12，command -v未找到uv。以上为用户反馈，跨机SSH随后已反馈通过，图安装及业务验收待执行。按已反馈环境，NebulaGraph服务在Milvus服务器Docker独立部署，初始化、冻结输入构建及SQL对账由应用服务器既有Python3.12.14虚拟环境通过SSH转发执行。此流程替换v0.45初版在图服务器安装Python依赖并构建后回传整套发布的安排，应用服务器生成配套发布目录。用户已从应用服务器SSH到root@172.16.0.154，返回主机名iZbp1eoksk549i98rt6mawZ、nproc为8，ED25519指纹SHA256:9OPPpTzS/FfMr5aD+Gg9JyqjgQwUp/PCf8gfrWi2j+0已由用户确认并写入known_hosts。用户反馈compose.yaml已通过scp完整传到图服务器/tmp/relationship-nebula-compose-source.yaml，2612字节。用户反馈图服务器已生成/srv/relationship-nebula/compose.yaml，独立项目relationship-nebula-test，平台linux/amd64、restart=unless-stopped，移除原ARM64摘要并保留127.0.0.1:19669映射，Compose校验通过，metad／storaged／graphd的v3.8.0镜像均已拉取完成。用户反馈up -d已创建独立网络、五个卷及三个容器，metad为Healthy，storaged和graphd为Started。首次状态检查因容器curl不支持--retry-connrefused中断，参数已修正为现有healthcheck的curl -sf。用户随后反馈HTTP返回git_info_sha=7458486、status=running，Compose ps中graphd和metad均healthy，storaged为health: starting，宿主绑定127.0.0.1:19669。用户反馈应用服务器排除SSH_AUTH_SOCK、BatchMode=yes及StrictHostKeyChecking=yes的SSH验证通过，返回图服务器主机名，本机19669无监听。用户反馈relationship-graph-tunnel.service已enabled并active(running)，主进程ssh的PID为1925434，本机127.0.0.1:19669由同一SSH进程监听，转发目标为图服务器127.0.0.1:19669。用户已在应用服务器执行scripts/nebula_lab.py bootstrap和check，两次均返回storaged:9779为ONLINE、graphd:9669为ONLINE、Version=3.8.0、authentication=true。初始化期间SDK输出Closing a connection that is in use，随后两次查询均成功；凭据由程序在应用服务器data/nebula-lab/credentials.json私有保存。用户反馈服务器新图relationship_lab_sync_7bb2f3daef15已构建为verified，版本real-2a106af85a3330dba3c2-202611，19326节点、25239事实、331783关系证据、357022总边，validation.passed=true且all_graph_rows_verified=true，构建观察161.423秒。四类独立SQL逐证据计数和摘要与本机原发布一致，图摘要8e45c2f75957c2be30b00cd3eed0e4c305af8142328281745a199d46d270d43e。用户反馈verify_real_graph_queries.py的GUEST核对passed=true，中心p:expert:1076的1至4跳候选数1／2／3／4，逐段连接和SQL事实回查通过，单次小邻域顺序观察44.224／35.433／55.586／66.309毫秒。用户反馈应用服务器80／443／8000／8088无监听，curl为/usr/bin/curl，PATH未找到nginx，nginx服务inactive。下一步按当前root环境创建relationship-query.service，单worker监听127.0.0.1:8000，EnvironmentFile指向已验证真实发布目录，依赖SSH转发，开机启动并失败重启。用户反馈已写入query.env与relationship-query.service并enable --now，服务active(running)，主进程Python PID1925910，开始时间为2026-11-11 20:46:28 CST。用户随后提供journal日志，20:46:29 Waiting for application startup，20:47:03 Application startup complete并监听127.0.0.1:8000，该启动日志窗口约34秒。下一步直接读取health与meta，核对真实模式、版本、6525人物／25239事实及4跳能力。用户反馈HTTP health为status=ok、data_mode=real、版本real-2a106af85a3330dba3c2-202611，meta为6525专家、0简历、12801实体、25239事实、max_relation_hops=4、graph_model=numeric-relations-v1、relation_backend=nebula-materialized。用户提供的安装附件显示Nginx1.18.0(Ubuntu)、包1.18.0-6ubuntu14.22安装完成，9个新包、0升级，needrestart列出的服务重启被延后，最终nginx -v成功。下一步配置/etc/nginx/conf.d/relationship-map.conf，监听8088，静态根为/srv/relationship-map/frontend/dist，/api/转发至127.0.0.1:8000，规范前端产物读权限后nginx -t并启用／重载，再本机检查页面和代理meta。用户反馈nginx -t通过，nginx已enable并reload，本机http://127.0.0.1:8088/的HEAD返回200、Content-Type=text/html、Content-Length=468，代理/api/v1/meta返回预期真实版本、6525专家、25239事实及4跳能力。助手从本机执行公网HEAD及排除代理的GET /api/v1/meta，两次均收到curl错误52 Empty reply from server。公网可达性原因尚待核对，下一步由用户在本机浏览器访问http://121.43.176.65:8088并反馈页面或报错，再完成业务查询验收。网页、业务查询和完整验收待反馈；上述构建和查询耗时均属于当前冻结样本观察。

源码包SHA256为 `7bc70ac6993cfaea0f675b5660308bcf02194e28cde476142116df8cc9f0332b`。

## 1 部署安排

| 位置 | 内容 | 访问方式 |
| --- | --- | --- |
| 应用测试服务器 | Nginx 静态前端、Python API、配套只读 SQLite 发布快照 | 浏览器访问应用服务器的 8088 端口，API 监听本机 8000 |
| Milvus 测试服务器 | 独立 NebulaGraph 3.8.0 的 metad／storaged／graphd | Graph Service 映射到该机 127.0.0.1 的 19669 端口 |
| 应用到图服务器 | systemd 托管 SSH 本地转发 | 应用本机 127.0.0.1:19669 → SSH → 图服务器 127.0.0.1:19669 |

当前 ReaderCredentials 与构建凭据类型固定为 `127.0.0.1:19669`，现有 Compose 固定本机 ARM64 镜像摘要。因此本手册采用 SSH 转发，并在服务器生成适配本机架构的测试 Compose。新 Compose 使用独立项目名、网络及数据卷，NebulaGraph 与 Milvus 共存。

本次部署使用已冻结的真实输入。在图服务器重建新图空间、生成 GUEST 账号并完成独立 SQL 核对后，将整套发布目录交给应用服务器。查询详情取自发布内的 source.sqlite，当前来源为 6525 位专家、25239 条事实。首次上线按此固定版本验收，持续 CDC 发布、源库新数据同步和简历覆盖属于后续运行能力。

容器内存上限沿用当前实验配置，metad 512MiB、storaged 2GiB、graphd 1GiB，CPU 配额合计 3.5 核。与 Milvus 共存的实际余量和性能需要服务器实测。单机单副本用于本轮测试。

Docker Compose 部署方式与 NebulaGraph 3.8 文档一致，镜像取本机架构的 v3.8.0 标签。现场执行 pull 后核对镜像和服务版本。[NebulaGraph 官方部署文档](https://docs.nebula-graph.io/3.8.0/4.deployment-and-installation/2.compile-and-install-nebula-graph/3.deploy-nebula-graph-with-docker-compose/)

## 2 核对两台服务器

分别 SSH 登录两台服务器，以 `deploy` 执行。将地址替换为实际值。

```bash
ssh deploy@应用服务器地址
ssh deploy@Milvus服务器地址
```

在各自会话中执行。

```bash
cat /etc/os-release
uname -m
free -h
df -h
ss -lnt
```

在 Milvus 服务器另外执行，确认 Docker 和 Compose 插件可用，并查看现有容器占用。

```bash
docker version
docker compose version
docker ps
docker stats --no-stream
```

需要浏览器能访问应用服务器 8088，应用服务器能 SSH 到 Milvus 服务器。两台机器的本机 19669 端口需可用，应用服务器的本机 8000 需可用。若 SSH 使用其他端口，在 scp／ssh、ssh-copy-id 和后文 SSH 配置中设置同一个实际端口。

## 3 本机打包代码和冻结输入

以下在当前 Mac 项目目录打包完整前端源码、配置和锁文件。前端在应用测试服务器构建，后端虚拟环境在Linux服务器创建。

```bash
cd /Users/yuka/Developer/character_relationship_map
```

设置实际地址和部署账号，然后生成本轮发布包。文件包含私有人物来源快照，暂存目录使用 700 权限，包使用 600 权限。

```bash
export APP_HOST='替换应用服务器地址'
export GRAPH_HOST='替换Milvus服务器地址'
export SSH_USER='deploy'
export DEPLOY_STAGE="$(mktemp -d /tmp/relationship-map-deploy.XXXXXX)"
export DEPLOY_BUNDLE="$DEPLOY_STAGE/relationship-map-test-20261111.tgz"
umask 077

mkdir -p "$DEPLOY_STAGE/data/releases/test-20261111-v1"
for artifact in contract.json source-snapshot.json input-audit.json source.sqlite graph-plan.json prepared.json
do
  cp "data/real-graph/run-v1/build-v1/$artifact" \
    "$DEPLOY_STAGE/data/releases/test-20261111-v1/$artifact"
done

COPYFILE_DISABLE=1 tar \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='frontend/node_modules' \
  --exclude='frontend/dist' \
  --exclude='frontend/test-results' \
  --exclude='frontend/playwright-report' \
  --exclude='.DS_Store' \
  -czf "$DEPLOY_BUNDLE" \
  backend/pyproject.toml backend/uv.lock backend/src \
  scripts/build_real_graph.py scripts/verify_real_graph_queries.py scripts/nebula_lab.py \
  infra/nebula \
  docs/examples/update-authoritative-contract-v1.json \
  frontend \
  -C "$DEPLOY_STAGE" data/releases/test-20261111-v1

chmod 600 "$DEPLOY_BUNDLE"
shasum -a 256 "$DEPLOY_BUNDLE"
scp "$DEPLOY_BUNDLE" "$SSH_USER@$APP_HOST:/tmp/relationship-map-test-20261111.tgz"
scp "$DEPLOY_BUNDLE" "$SSH_USER@$GRAPH_HOST:/tmp/relationship-map-test-20261111.tgz"
```

包内的六份输入来自已核对的 build-v1。构建时沿用原基准月和数据版本，同时生成服务器自己的图空间、收据及只读账号。

## 4 两台服务器安装后端运行环境

以下在两台服务器各执行一次。Milvus 服务器已有 Docker 和 Compose 的情况下，直接沿用该安装。

```bash
sudo apt-get update
sudo apt-get install -y curl ca-certificates python3 openssh-client
sudo install -d -o deploy -g deploy -m 755 /srv/relationship-map
chmod 600 /tmp/relationship-map-test-20261111.tgz
sha256sum /tmp/relationship-map-test-20261111.tgz

tar -xzf /tmp/relationship-map-test-20261111.tgz -C /srv/relationship-map
cd /srv/relationship-map
chmod 700 data data/releases data/releases/test-20261111-v1
chmod 600 data/releases/test-20261111-v1/*

curl -LsSf https://astral.sh/uv/install.sh -o /tmp/relationship-map-uv-install.sh
sh /tmp/relationship-map-uv-install.sh
export PATH="$HOME/.local/bin:$PATH"
uv python install 3.12
uv sync --project backend --python 3.12 --locked --no-dev
backend/.venv/bin/python --version
```

核对服务器显示的包 SHA256 与本机值一致。`uv sync --locked` 使用仓库锁文件，环境建立在 backend/.venv。[uv 官方安装说明](https://docs.astral.sh/uv/getting-started/installation/)、[锁定与同步说明](https://docs.astral.sh/uv/concepts/projects/sync/)

## 5 Milvus 服务器安装并初始化 NebulaGraph

以下仅在 Milvus 服务器执行。

### 5.1 生成服务器测试 Compose

```bash
cd /srv/relationship-map
backend/.venv/bin/python - <<'PY'
import re
from pathlib import Path

source = Path('infra/nebula/compose.yaml').read_text()
source = re.sub(r'^#.*\n', '', source, count=1)
source = source.replace('name: relationship-nebula-lab', 'name: relationship-nebula-test')
source = source.replace('  platform: linux/arm64\n', '')
source = source.replace('  restart: "no"', '  restart: unless-stopped')
source = re.sub(r'@sha256:[0-9a-f]{64}', '', source)
Path('infra/nebula/compose.test.yaml').write_text(source)
PY

docker compose -p relationship-nebula-test -f infra/nebula/compose.test.yaml config --quiet
docker compose -p relationship-nebula-test -f infra/nebula/compose.test.yaml pull
docker compose -p relationship-nebula-test -f infra/nebula/compose.test.yaml up -d
```

### 5.2 初始化账号、注册存储服务并检查

先检查 Graph Service 的 HTTP 状态接口，返回正常状态后继续初始化。

```bash
docker compose -p relationship-nebula-test -f infra/nebula/compose.test.yaml \
  exec -T graphd curl -sf http://127.0.0.1:19669/status

backend/.venv/bin/python scripts/nebula_lab.py bootstrap

docker compose -p relationship-nebula-test -f infra/nebula/compose.test.yaml \
  up -d --wait --wait-timeout 120

backend/.venv/bin/python scripts/nebula_lab.py check
docker compose -p relationship-nebula-test -f infra/nebula/compose.test.yaml ps
docker compose -p relationship-nebula-test -f infra/nebula/compose.test.yaml images
```

bootstrap 为本轮独立实例初始化 root 密码并注册 storaged，凭据保存在该服务器 data/nebula-lab/credentials.json。检查结果应包含 ONLINE 存储节点和 3.8.0 版本。若初始化失败，先查看本节日志并修复，再继续构建。

```bash
docker compose -p relationship-nebula-test -f infra/nebula/compose.test.yaml \
  logs --tail 100 metad storaged graphd
```

### 5.3 从冻结输入重建真实图并独立核对

```bash
cd /srv/relationship-map
backend/.venv/bin/python scripts/build_real_graph.py \
  --output data/releases/test-20261111-v1 \
  --build-prepared

backend/.venv/bin/python scripts/verify_real_graph_queries.py \
  --output data/releases/test-20261111-v1
```

第一次命令生成新空间并核对完整图摘要、四类人物关系的全部独立 SQL 证据。第二次核对只读账号上的真实小邻域 1 至 4 跳。manifest.json 中 state 应为 verified，validation.passed 应为 true。脚本失败时保留材料排查，重新构建使用新的候选目录，复制第3节的六份原输入后再执行。

```bash
backend/.venv/bin/python - <<'PY'
import json
from pathlib import Path

release = Path('data/releases/test-20261111-v1')
manifest = json.loads((release / 'manifest.json').read_text())
assert manifest['state'] == 'verified' and manifest['validation']['passed'] is True
print(json.dumps({
    'version': manifest['version'],
    'space': manifest['graph']['space'],
    'nodes': manifest['graph']['node_count'],
    'facts': manifest['graph']['fact_count'],
    'relations': manifest['graph']['relation_count'],
}, ensure_ascii=False, indent=2))
PY

umask 077
tar -czf /tmp/relationship-map-verified-20261111.tgz \
  -C /srv/relationship-map/data/releases test-20261111-v1
chmod 600 /tmp/relationship-map-verified-20261111.tgz
sha256sum /tmp/relationship-map-verified-20261111.tgz
```

预期为19326节点、25239事实、331783关系证据，版本 real-2a106af85a3330dba3c2-202611。图空间名由本次构建自动生成。

## 6 将已核对发布目录交给应用服务器

回到本机 Mac，在第3节的同一终端执行。

```bash
scp "$SSH_USER@$GRAPH_HOST:/tmp/relationship-map-verified-20261111.tgz" \
  "$DEPLOY_STAGE/relationship-map-verified-20261111.tgz"
chmod 600 "$DEPLOY_STAGE/relationship-map-verified-20261111.tgz"
shasum -a 256 "$DEPLOY_STAGE/relationship-map-verified-20261111.tgz"
scp "$DEPLOY_STAGE/relationship-map-verified-20261111.tgz" \
  "$SSH_USER@$APP_HOST:/tmp/relationship-map-verified-20261111.tgz"
```

应用服务器执行，核对包 SHA256 后解压。该步骤在首次启动 API 前完成。

```bash
cd /srv/relationship-map
chmod 600 /tmp/relationship-map-verified-20261111.tgz
sha256sum /tmp/relationship-map-verified-20261111.tgz
tar -xzf /tmp/relationship-map-verified-20261111.tgz -C data/releases
chmod 700 data/releases/test-20261111-v1 data/releases/test-20261111-v1/graph
chmod 600 data/releases/test-20261111-v1/graph/reader-credentials.json
```

此发布包包含配套只读查询账号，查询服务通过该账号访问本次服务器新图。

## 7 应用服务器建立持久 SSH 转发

以下仅在应用服务器执行，以 deploy 登录。填写 Milvus 服务器地址。公钥登录沿用现有部署授权，首次 SSH 连接核对服务器指纹。

```bash
export GRAPH_HOST='替换Milvus服务器地址'
install -d -m 700 "$HOME/.ssh"
ssh-keygen -t ed25519 -f "$HOME/.ssh/relationship-test-graph" -N ''
ssh-copy-id -i "$HOME/.ssh/relationship-test-graph.pub" "deploy@$GRAPH_HOST"

cat >> "$HOME/.ssh/config" <<EOF

Host relationship-test-graph
  HostName $GRAPH_HOST
  User deploy
  Port 22
  IdentityFile ~/.ssh/relationship-test-graph
  IdentitiesOnly yes
EOF
chmod 600 "$HOME/.ssh/config"
ssh relationship-test-graph true
```

新建转发服务。

```bash
sudo tee /etc/systemd/system/relationship-graph-tunnel.service > /dev/null <<'EOF'
[Unit]
Description=Relationship test graph SSH tunnel
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
User=deploy
ExecStart=/usr/bin/ssh -N -T -o BatchMode=yes -o StrictHostKeyChecking=yes -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -L 127.0.0.1:19669:127.0.0.1:19669 relationship-test-graph
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now relationship-graph-tunnel.service
sudo systemctl status relationship-graph-tunnel.service --no-pager
ss -lnt | grep 19669
```

## 8 应用服务器启动 API

配置指向已核对的新发布目录。

```bash
sudo install -d -m 755 /etc/relationship-map
sudo tee /etc/relationship-map/query.env > /dev/null <<'EOF'
RELATIONSHIP_NUMERIC_RELEASE_STORE=/srv/relationship-map/data/releases/test-20261111-v1
PYTHONUNBUFFERED=1
EOF
sudo chmod 600 /etc/relationship-map/query.env

sudo tee /etc/systemd/system/relationship-query.service > /dev/null <<'EOF'
[Unit]
Description=Relationship test query API
Requires=relationship-graph-tunnel.service
After=network-online.target relationship-graph-tunnel.service

[Service]
Type=simple
User=deploy
Group=deploy
WorkingDirectory=/srv/relationship-map
EnvironmentFile=/etc/relationship-map/query.env
ExecStart=/srv/relationship-map/backend/.venv/bin/python -m uvicorn relationship_query.app:app --host 127.0.0.1 --port 8000 --workers 1 --proxy-headers --forwarded-allow-ips 127.0.0.1
Restart=on-failure
RestartSec=10
TimeoutStopSec=30
UMask=0077

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now relationship-query.service
sudo journalctl -u relationship-query.service -n 100 --no-pager
```

启动时程序完整核对发布摘要和整图，现有代码启动核对预算120秒。本机同规模曾观察19.476秒，服务器耗时需要现场测量。以 health 成功作为就绪条件。

```bash
curl --fail --retry 40 --retry-connrefused --retry-delay 3 \
  --retry-max-time 180 http://127.0.0.1:8000/api/v1/health
curl --fail http://127.0.0.1:8000/api/v1/meta
```

meta 应显示 data_mode=real、6525专家、25239事实、max_relation_hops=4。

## 9 应用服务器发布前端

先在应用服务器完成Node与npm安装核对。当前Node版本已反馈为v22.23.4，其/opt安装目录内npm文件已存在，用户已修复命令入口，npm／npx回查均为10.9.9。npm可用后执行服务器构建。

```bash
cd /srv/relationship-map
node --version
npm --version
npm --prefix frontend ci --include=dev --no-audit --no-fund
npm --prefix frontend run build
```

以下为独立 Nginx 8088 测试入口。若机器已有 Nginx，继续在其 conf.d 中加入本项目配置。

```bash
sudo apt-get install -y nginx
cd /srv/relationship-map
chmod 755 /srv/relationship-map frontend
find frontend/dist -type d -exec chmod 755 {} +
find frontend/dist -type f -exec chmod 644 {} +

sudo tee /etc/nginx/conf.d/relationship-map.conf > /dev/null <<'EOF'
server {
    listen 8088;
    server_name _;
    root /srv/relationship-map/frontend/dist;
    index index.html;

    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_connect_timeout 5s;
        proxy_read_timeout 180s;
    }

    location / {
        try_files $uri $uri/ /index.html;
    }
}
EOF

sudo nginx -t
sudo systemctl enable --now nginx
sudo systemctl reload nginx
curl --fail http://127.0.0.1:8088/api/v1/meta
```

静态文件路径和 API 前缀保持项目现有前端调用约定。[Nginx 官方入门文档](https://nginx.org/en/docs/beginners_guide.html)

完成后浏览器访问 `http://应用服务器地址:8088`。

## 10 上线验收

应用服务器执行真实规则检查。

```bash
curl --fail http://127.0.0.1:8088/api/v1/persons/p:expert:1000/relations/search \
  -H 'Content-Type: application/json' \
  -d '{"relation_type":"same_major","require_same_school":true,"page_size":50}' \
  -o /tmp/relationship-map-school-check.json

/srv/relationship-map/backend/.venv/bin/python - <<'PY'
import json
from pathlib import Path

result = json.loads(Path('/tmp/relationship-map-school-check.json').read_text())
assert result['data_mode'] == 'real'
assert result['applied_filters']['require_same_school'] is True
assert [item['person']['id'] for item in result['items']] == ['p:expert:6590']
print('真实数据与同校前提核对通过')
PY
```

再通过浏览器验收以下入口。

- 页面显示真实数据，人物搜索和公司／学校筛选可用。
- 同专业的“要求同校”默认勾选，取消并提交后可返回跨校同专业人物。
- 单人物1至4跳、两人路径、证据详情、导出和保存恢复正常。
- 重启应用服务后 health 恢复，核对 SSH 转发随机器启动。

当前源码已有本机真实数据和模拟数据回归记录，服务器侧以上验收完成后再登记实际部署结果。

## 11 日常操作和数据发布回退

应用服务器查看状态及日志。

```bash
sudo systemctl status relationship-query relationship-graph-tunnel --no-pager
sudo journalctl -u relationship-query -n 100 --no-pager
sudo journalctl -u relationship-graph-tunnel -n 100 --no-pager
sudo systemctl restart relationship-query
```

图服务器查看状态或停止本项目容器。

```bash
cd /srv/relationship-map
docker compose -p relationship-nebula-test -f infra/nebula/compose.test.yaml ps
docker compose -p relationship-nebula-test -f infra/nebula/compose.test.yaml logs --tail 100
docker compose -p relationship-nebula-test -f infra/nebula/compose.test.yaml stop
```

后续新数据使用新的候选发布目录，在新图空间完成核对，将整套候选目录复制到应用服务器，再修改 query.env 的 RELATIONSHIP_NUMERIC_RELEASE_STORE 并重启 API。保留先前成对发布目录、图空间与其 GUEST 账号，需回退时将同一变量指回先前目录并重启，然后检查 health、meta 和业务查询。

源库密码继续由数据采集侧保管。当前部署的查询配置使用发布快照及 GUEST 图账号。持续采集／自动发布部署需沿主方案的双源业务版本边界和 CDC 调度另行完成验收。

## v1.0 本机核对记录

已通过21段 Bash 语法检查、3段内嵌 Python 语法检查，以及生成后的 Docker Compose config 解析。本机实际执行了第3节的打包流程中构建产物归档部分，检查127个归档项、5份 prepared 文件摘要、source.sqlite 完整性及6525人物／25239事实计数。包内容按源码、静态构建和六份冻结输入生成。Nginx 运行配置、Linux 依赖安装、systemd、跨机连接、远端镜像拉取及服务器业务查询仍需现场执行。

## v1.1 修订记录

2026-11-11按用户说明改为应用服务器构建前端，包包含frontend源码、配置、测试引用与package-lock，排除node_modules、dist及测试产物。旧v1.0的127项归档记录对应当时静态产物包，当前源码包的核对结果另行登记。应用服务器当前npm补齐和构建待用户逐步执行反馈。

v1.1本机检查通过22段Bash语法与3段内嵌Python语法，实际归档183项，已核对源码、锁文件、配置和测试引用齐备，构建产物及依赖目录排除。服务器构建继续等待npm诊断及后续执行反馈。

Python解释器隔离按uv默认带版本号入口及项目backend/.venv设计。uv行为依据[官方Python管理说明](https://docs.astral.sh/uv/guides/install-python/)。用户已回查默认python3为/usr/bin/python3、Python3.10.12。
