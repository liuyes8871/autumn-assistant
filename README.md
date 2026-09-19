# 秋招助手 · Autumn Assistant

面向中国应届生的开源、本地优先秋招岗位库与投递进度 PWA。

> 当前仓库已进入真实来源试运行：`apps/web/public/data` 是 2026-09-14（Asia/Shanghai）生成的公开岗位目录。岗位仍应以企业官网最新信息为准；来源只有完成官方性、访问边界、校招识别、字段抽查和投递链接核验后，才会进入目录。公司入口与岗位来源分层，入口线索不会被当成可运行来源。

当前试运行目录含 1,020 条岗位（其中 992 条活跃、28 条按生命周期规则保留的关闭记录）、20 个已核验公开校招来源；最近一次完整抓取观测到 4,537 条岗位，其中 992 条通过文科、社科、商科友好准入，3,330 条明确超出范围，215 条信息不足进入待核验。现有注册表、中国互联网协会 2025 年前百家和固定版本 Hiring Radar 种子合并后形成 358 家候选企业；其中 198 家被纳入“中国互联网行业优先”重点配置，198 家已有登记来源、5 家具备当前可运行来源。当前静态公司入口目录包含 270 家企业（20 个官方入口、250 个入口线索·待确认）；这些数字与 20 个可运行岗位来源分开统计。本轮新增登记 Robinhood 与 Point72 两家公司，其中 Robinhood 已完成公开来源核验并新增 11 条合格岗位，Point72 因官网条款限制保留为人工导入线索。新增候选缺少一手规模/上市证据时保持“未知”，另有字节跳动、莉莉丝、拓竹科技和仙工智能作为行业覆盖例外。当前已达到 20 家试运行门禁，但仍未达到“50 家正式验收”，候选名单和入口线索不能计作已接入来源。

## 已实现

- 移动优先 PWA：岗位、进度、日程、设置四个工作台；桌面顶部全局导航，手机底部导航。
- 组合筛选：搜索、地区、可多选的省份/城市/岗位类别、行业、公司类型、届别、批次、阶段、意向、截止时间和偏好匹配；同一维度取并集，不同维度取交集。
- 岗位目录按公司分组展示，同一公司默认显示 5 条，支持展开全部；桌面筛选栏与目录各自独立滚动，移动端改用筛选抽屉。
- 公司筛选支持细分赛道和入口状态（官方入口、入口线索·待确认、已同步岗位、仅入口公司）；公司筛选可以作用于入口行和岗位组，岗位专属筛选仍会隐藏没有岗位的入口公司。
- 公司入口与岗位数据分层展示：当前校招入口可先以“官方入口”或“入口线索·待确认”进入目录，具体岗位只来自人工 `VERIFIED` 或证据完整的 `AUTO_VERIFIED` 来源；当前静态目录已生成 270 个可追溯入口，其中 20 个官方入口、250 个待确认线索。入口线索只保留可追溯的招聘入口，不代表企业已经完成岗位采集核验。
- 地区采用“中国大陆 / 港澳台 / 海外 / 远程 / 未知”分层；中国大陆按省份、城市和区县归一化，旧目录城市文本仍可兼容读取。
- 岗位详情：JD 纯文本、任职要求、企业发布日期/截止日/首次收录/最后核验、来源证据和官方投递入口。
- 本地 IndexedDB：兴趣（合适/不合适）与投递阶段（未投递/已投递/初筛/测评/面试/Offer/已挂/已放弃）分开存储。
- 进度看板/表格、阶段历史、今日看板、逾期待跟进和多轮面试日程。
- 完整 JSON 备份/恢复；带 UTF-8 BOM、公式注入防护且默认排除笔记的 CSV 导出。
- PWA Service Worker：应用壳和目录可在离线时回退；目录版本更新显示站内提示。
- Python 采集器：Pydantic 结构化校验、校招/社招门禁、文科/社科/商科受众准入门禁、HTML 转纯文本、稳定去重 ID、来源骤降隔离、生命周期追踪和静态目录生成；实时模式只运行已审核的公开来源。除现有腾讯、字节跳动、百度、京东等来源外，采集器已提供 Workday、Greenhouse、Lever 和人工审核 DOM 的保守解析能力，但适配器只有在逐家公司完成官方入口、robots/条款、三条岗位抽查和投递域名核验后才可启用。当前已接入的 20 个来源包含新增的 Robinhood Greenhouse 公开岗位来源。
- 目标企业注册表（`registry/companies.json`）、中国互联网协会前百家固定索引（`registry/internet-authority-top100.json`）与来源审计规则（`SOURCE_AUDIT.md`）。三者合并后的候选池由 `npm run collector:candidates` 生成；目标池不是“已接入”清单，只有 `VERIFIED` 或满足完整自动证据的 `AUTO_VERIFIED` 才能计入岗位来源验收。前百家索引通过 `npm run collector:authority` 生成去重审计，不会自动添加招聘 URL。当前人工注册表为 252 家、来源登记 235 个；本轮收尾新增 Robinhood（已核验并自动采集）与 Point72（人工导入线索），此前扩容的第四范式、云从科技、七牛云、青云科技、思谋科技、DolphinDB、北森、涂鸦智能和 PingCAP 等仍按 `TARGET` 规则管理，不自动采集岗位。
- Hiring Radar 的公司/ATS 种子固定在 `registry/hiring-radar-seed.json`（MIT，commit `3784ed9286e7e7c6f214e1d03e1196595b56b6a4`），通过 `npm run collector:hiring-radar` 导入候选池和发现审计；它不是独立的已接入来源，也不会复制上游抓取代码、Moka 解密逻辑或登录态。含公开入口 URL 的种子记录只能作为 `ENTRY_LEAD` 线索，不能自动运行或发布岗位。
- 目标来源阻断时的分类替换顺序记录在 `registry/replacements.json`，不允许静默更换企业。
- “今日新开”严格区分企业今日开放活动、官网今日发布岗位和今日首次收录；业务日期统一按 `Asia/Shanghai` 计算。
- 来源发现与岗位更新分离：每日刷新公开官方来源发现报告，每周刷新候选公司池，已核验来源约每 5 小时更新岗位；候选、待核验和受阻来源不会计入已接入数量。
- 来源发现报告会把每个 `TARGET` 入口分为 `CONNECTOR_CANDIDATE`、`NEEDS_MANUAL_REVIEW`、`MANUAL_IMPORT_ONLY` 或 `PUBLIC_ACCESS_UNAVAILABLE`，并记录 ATS、候选 endpoint、JSON-LD/Feed/Sitemap 证据、当前届信号和字段完整度；这些结果始终是审核队列，不会自动升级为 `VERIFIED`。
- 国企上市公司扩展已完成只读导入和全量入口发现：用户 Excel 精确得到 1,441 家 `股权性质=国企` 候选（1,402 条非空官网、39 条缺失，1,424 家正常上市、17 家其他状态），国资委官方双栏名录解析得到 99 家央企集团。为响应“岗位数量优先”，公开入口临时采集共解析 1,734 条原始记录、归一化 1,402 条，其中 497 条通过现有文社商/不限专业基础口径，684 条属于信息不足但未明确超出范围的 `NEEDS_REVIEW`，合计 1,181 条来自 225 家公司、355 个公开页面；这 1,181 条已通过 `provisional-jobs.json` 接入网站，统一标记“公开入口临时采集 · 待核验”。明确技术、医学、法务、设计等超出范围的 221 条仍不发布。临时岗位不计入 20 个 `VERIFIED` 来源和正式目录，仍需以企业官网为准。详细证据在 [`artifacts/state-owned-company-candidates.json`](./artifacts/state-owned-company-candidates.json)、[`artifacts/state-owned-source-discovery.json`](./artifacts/state-owned-source-discovery.json) 和 [`artifacts/state-owned-provisional-jobs.json`](./artifacts/state-owned-provisional-jobs.json)，运行方式见 [`collector/README.md`](./collector/README.md)。
- 候选公司发现任务会低频解析交易所、国资委等权威名录，输出去重后的 `artifacts/company-discovery.json`；固定百强和 Hiring Radar 种子则通过 `artifacts/internet-authority-import.json`、`artifacts/hiring-radar-import.json` 合并进候选池。所有发现记录只进入审核队列，不会自动运行未审核来源或发布岗位。
- 公司发现报告记录权威名录的可达性、分页和候选数量，并与 `registry/internet-focus.json` 的重点层级关联；一次真实运行（2026-09-08）发现 1,701 条上交所候选记录，报告仅作为人工审核队列，不代表这些公司已有校招来源。
- 当前进入“中国互联网行业优先扩容”阶段：`registry/internet-focus.json` 以综合平台、搜索与 AI、电商、本地生活、内容社区、游戏、在线旅行、金融科技和企业软件为重点，优先安排发现与审核。本轮重点配置扩展到 198 家，新增第四范式、云从科技、七牛云、青云科技、思谋科技、DolphinDB、北森、涂鸦智能和 PingCAP，并补齐完美世界、东方财富入口；重点名单只改变队列顺序，不会把 `TARGET` 自动升级为 `VERIFIED`；非互联网已核验来源继续采集。
- 可选的社区线索同步：在已由用户自行打开并登录的 Edge/Chrome 会话中运行 `npm run xhs:sync`，通过 OpenCLI 只读搜索小红书公开帖子，生成 `apps/web/public/data/community-leads.json`。该文件只保存去掉 `xsec_token` 的公开帖子链接、可识别的公司官网入口和脱敏标题；不读取、导出或保存浏览器 Cookie，不访问私信和个人资料，也不保存个人内推码、内推链接或奖励关系。社区线索在设置页单独显示为“需核验”，不会自动升级来源或进入岗位目录。

### 文科、社科、商科友好准入

正式公共目录采用版本化的确定性规则 `humanities-social-business-v1`。只有明确面向文科、社科、商科或不限专业的通用岗位才会公开；软件、算法、硬件、工程研发、医学临床、法务合规、生产工艺以及强制专门专业/作品集的岗位会被排除。Excel、SQL、BI、Python、建模等技能只是展示标签，不会单独触发排除；“计算机专业优先”也不会覆盖同时接受商科或不限专业的岗位。名称和要求不足以判断的岗位进入 `NEEDS_REVIEW`，不会进入正式公共目录；当前数量优先的国企临时快照是单独的 `provisional-jobs.json` 展示层，会明确标记“待核验”，但不会改变正式目录或来源状态。

每次采集都会在 `manifest.json` 写入 `audiencePolicy` 摘要，并生成不含完整 JD 的 `artifacts/audience-filter-report.json`，按来源、原因码统计通过、排除和待核验数量。发布门禁会从详情分片重新执行同一规则；任何不合格岗位被插入目录都会阻止本次发布并保留上一版目录。用户已经标记或投递过的技术岗位不会从本机 IndexedDB 删除，而是在进度页显示为“历史岗位 · 已退出公共库”。

## 本地运行

需要 Node.js 20+ 与 Python 3.11+。

```bash
npm install
npm run dev
```

打开终端提示的本地地址即可体验。首次打开会出现偏好设置引导；所有投递状态、面试安排和笔记仅写入当前浏览器。

Windows 用户也可以直接双击项目根目录的“启动秋招助手.cmd”。它会检查 127.0.0.1:5173 是否已经运行；如果没有，会在隐藏窗口中启动开发服务器，等待就绪后自动打开浏览器。浏览器收藏的 127.0.0.1:5173 地址本身不会在电脑重启后自动启动服务。

部署到自己的仓库时可设置 `VITE_REPOSITORY_URL=https://github.com/<owner>/<repo>`，岗位页和设置页的“报告错误”会自动生成预填充 Issue；未设置时仅显示 GitHub 入口占位，不会上传任何用户数据。

构建与测试：

```bash
npm run build
npm test
python -m pip install -r collector/requirements.txt
python -m pytest tests
```

构建完成后也可以不启动服务器，直接双击打开 `apps/web/dist/index.html`。生产构建会把应用脚本和样式内嵌到单个 HTML 文件中，适合在 Windows 资源管理器中离线查看；此模式使用内置演示目录，想读取最新岗位目录请使用 `npm run dev` 或 GitHub Pages 地址。误打开源码入口 `apps/web/index.html` 时，页面会自动跳转到这个可运行版本。

如果本机已安装 Playwright 浏览器，还可以启动 `npm run build` 后运行 `python tests/ui_smoke.py`，检查 375/768/1024/1440px 视口、详情弹层、阶段持久化和设置页。

使用脱敏夹具生成静态目录：

```bash
npm run collector:build
```

采集器不会把社招夹具写入校招目录。正式适配器必须在 `registry/sources.json` 登记，并补充来源证据、访问边界、核验日期和失败原因。

实时采集（仅请求来源注册表中 `VERIFIED` 或证据完整的 `AUTO_VERIFIED`、公开且完成访问审计的来源）：

```bash
npm run collector:live
```

默认实时模式不会因为来源尚未审核而生成岗位；工作流通过 `AUTUMN_LIVE_COLLECTION=true` 开启，并用 `AUTUMN_REQUIRED_SOURCES`（当前试运行默认 20，正式验收设为 50）执行发布门禁。只有完成公开访问审计的 JSON/DOM 来源才会请求；未达到门槛或采集失败时，工作流不应把演示目录伪装成生产目录，也不应提交异常删除结果。

社区线索同步（可选，仅在本机浏览器会话中运行）：

```bash
npm run xhs:sync
```

该命令依赖已连接的 OpenCLI 浏览器会话；如果同时连接了多个浏览器，可先在 OpenCLI 中确认 Edge profile，并通过 `XHS_OPENCLI_PROFILE=edge npm run xhs:sync`（PowerShell 使用 `$env:XHS_OPENCLI_PROFILE='edge'; npm run xhs:sync`）显式选择。它不是 GitHub Actions 的定时采集任务：云端任务没有你的浏览器登录态，也不会接收 Cookie。搜索受限或触发风控时命令会保留已有目录并记录错误，不会尝试绕过验证码、403/429 或安全验证。

## 发布到 GitHub Pages

仓库包含 `.github/workflows/deploy-pages.yml`。将代码推送到 GitHub 后，在仓库 Settings → Pages 选择 GitHub Actions；工作流会根据仓库名设置 `BASE_URL`，使用 Hash Router 兼容项目子路径。公共 Pages 只承载静态岗位目录，个人数据不会上传。

目录更新工作流位于 `.github/workflows/update-catalog.yml`，默认每 5 小时运行一次（UTC 的 00:17、05:17、10:17、15:17、20:17）；`.github/workflows/discover-open-sources.yml` 每日刷新来源可达性和当前届入口信号，`.github/workflows/discover-company-candidates.yml` 每周同步权威名录、候选池和开源种子。正式启用前应先完成来源审计，在 `collector/adapters.py` 中补齐并测试对应适配器，再登记到 `registry/sources.json`；不绕过登录、Cookie、验证码、403/429 或反自动化措施。

首次接入真实岗位时，请在自己的设备上完成 GitHub 官方登录或把仓库协作者权限授予执行环境，不要把 Personal Access Token 粘贴到聊天、代码或数据目录。授权后先做只读仓库和 Actions 配置检查，再单独确认是否允许写入来源审计表和发布目录；本地求职记录始终不会随这些操作上传。

### 公司标识策略

岗位卡优先显示仓库内已完成来源核验的企业标识。当前腾讯使用腾讯官网公开的方形品牌资产，联想使用联想官网公开 favicon；其他已收录品牌使用本地 Simple Icons 路径，找不到可靠资产时回退为中文文字标识。品牌标识不会从第三方 CDN 运行时加载，适合离线 PWA；新增企业一方 Logo 前需要在 `SOURCE_AUDIT.md` 记录来源、核验日期和使用边界。

## 数据接口

- `/data/manifest.json`：目录版本、生成时间、上海业务日期、今日三类计数、来源健康、全行业候选覆盖、互联网重点覆盖摘要和分片清单。
- `/data/locations.json`：国家/地区、省份、城市和区县的公开筛选字典；无法确认的地点保留为未知，不由模型猜测。
- `/data/campaigns.json`：企业校招活动目录；活动发布日期和岗位发布日期不混用。
- `/data/catalog.json`：列表与筛选轻量字段。
- `/data/jobs/{shard}.json`：点击岗位后按分片加载完整 JD、来源证据和生命周期。
- `/data/companies.json`：公司分类、当前届校招入口、入口证据和独立目录状态；当前目录会随公开入口发现任务更新，`ACTIVE_LEAD` 仅表示可点击的待确认入口，不代表可自动采集。
- `/data/sources.json`：可公开展示的来源健康与审计摘要，不包含内部请求堆栈、Cookie 或用户数据。

公共目录故意不接受用户投递数据。岗位从目录关闭时，已经在本地交互过的岗位仍以快照形式留在进度页。

## 研究与复用边界

市场参照包括牛客校招日程、实习僧，以及 Huntr、Teal、Simplify 的职位收录与申请管道设计。前端视觉方向参考 taste-skill 的反模板化原则、shadcn/ui 的可组合组件和 Magic UI 的轻量节奏，但没有复制模板代码；React Bits 因许可证不明确不采用。开源候选与许可证、实际复用边界记录在 [`SOURCE_AUDIT.md`](./SOURCE_AUDIT.md)：Hiring Radar 和 ats-scrapers 只作为选择性采集器/夹具参考，JobSync 只参考交互；无许可证仓库和 PolyForm Noncommercial 仓库不复制实现。

## 路线图与限制

当前不包含账号、云同步、消息推送、社区统计或浏览器扩展；无法提供公开接口的岗位可通过用户主动选择的 HTTPS JSON 记录导入本地 inbox，仍会经过同一套归一化、校招/受众门禁和去重，不会提升来源的 `VERIFIED` 状态。当前真实目录有 20 个已核验来源，距离 50 家正式验收仍有 30 家；互联网重点配置已扩展到 198 家、入口目录 270 家，但仍处于持续发现和审核阶段。全网全量没有永久完成日期，只有在连续两个周度发现周期无新增合格来源、所有公开可访问来源均已接入或有明确阻断记录时，才可称为首轮发现饱和。实时采集器已经具备审核、受众准入和发布门禁，不会把剩余目标名单计为真实来源。只有互联网重点来源达到发现饱和后，才会按相同审核标准扩展中国制造业来源。下一阶段再考虑浏览器一键收录、可选跨设备同步和站内/邮件提醒；任何云同步都必须重新设计同意、删除权、隐私政策和后端安全方案。

隐私与合规说明见 [`PRIVACY.md`](./PRIVACY.md)。这是一套风险控制设计，不构成正式法律意见。

## 许可证

本项目以 AGPL-3.0 发布。第三方复用代码须保留其版权和许可证；详见 [`SOURCE_AUDIT.md`](./SOURCE_AUDIT.md)。
直接依赖和采集器参考边界见 [`THIRD_PARTY_NOTICES.md`](./THIRD_PARTY_NOTICES.md)。
