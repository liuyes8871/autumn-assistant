# 来源审计与复用边界

审计基准：2026-09-14（Asia/Shanghai）。`registry/companies.json` 中的 252 家是人工维护的注册表；与中国互联网协会前百家和固定 Hiring Radar 种子合并去重后，候选池为 358 家，仍不等于已经接入。只有通过官方性、校招性、字段完整性、访问边界和随机抽查后，才可将 `sourceStatus` 更新为人工 `VERIFIED`；满足完整自动证据、连续两次健康运行和异常降幅检查的公开连接器可标记为 `AUTO_VERIFIED`。两类状态都必须在本文件补充证据 URL、健康状态和替换记录。

## 2026-09-14 来源扩展收尾

本轮新增 2 家登记公司和 2 个来源条目：Robinhood 与 Point72。Robinhood 的官方 Careers 页面反向链接公开 Greenhouse 岗位接口，完成来源、robots、条款、届别与岗位抽查核验，标记为 `VERIFIED`；Point72 虽有官方早期职业入口和公开岗位线索，但官网条款禁止未经许可的自动化抓取，因此只保留为 `TARGET`/人工导入线索，不发起自动请求。

本轮公开目录从 1,009 条增加到 1,020 条岗位（净增 11 条），活跃岗位从 987 条变为 992 条。Robinhood 原始公开岗位 21 条，其中 11 条通过文科/社科/商科受众门禁后进入目录；其余 7 条明确超出范围、3 条信息不足，均保留在受众审计报告而不公开。当前已核验可运行来源为 20 个，候选公司池为 358 家，公开公司入口目录为 270 家（20 个官方入口、250 个待确认线索）。

Robinhood 证据：官方 [Careers](https://careers.robinhood.com/)、[Greenhouse 公共岗位接口](https://api.greenhouse.io/v1/boards/robinhood/jobs) 及岗位投递链接；Point72 证据：[Students & Early Career](https://point72.com/students-early-career/)、[Point72 Academy](https://point72.com/point72-academy/) 和 [招聘门户](https://careers.point72.com/)。

## 2026-09-09 公司入口层快照（历史基线）

本次入口层与岗位来源层分离后，候选池和公开入口的统计如下；它们不等同于已完成岗位自动采集的来源数量：

| 指标 | 数量 | 口径 |
| --- | ---: | --- |
| 合并候选公司池 | 356 | 现有注册表、互联网协会前百家和固定 Hiring Radar 种子去重后的候选，不代表当前校招已开放 |
| 公司入口目录 | 268 | 有可追溯公开招聘入口且当前静态构建允许展示 |
| 官方入口 | 19 | 官网/官方 ATS 入口，且对应岗位来源已完成核验或有当前届官网信号 |
| 入口线索·待确认 | 249 | 可访问或已登记的公开入口线索，尚未完成企业官网反向确认，不自动采集岗位 |
| 已核验可运行岗位来源 | 19 | `registry/sources.json` 中 `VERIFIED` 且健康的来源 |
| 权威名录记录 | 100 | 中国互联网协会 2025 年前百家固定索引，全部完成格式、排名和重复检查 |
| Hiring Radar 公司记录 | 157 | 固定 MIT commit 的发现种子，仅保存公司/ATS/入口线索 |

当前构建尚未生成 `collector/company-directory-state.json`，因此本地兼容模式会使用注册表和已有入口线索；每日入口探测任务写入状态文件后，生产发布将以 `ACTIVE_CONFIRMED`/`ACTIVE_LEAD` 观测为唯一可见性依据。任何候选、入口线索或 `TARGET` 来源都不会被统计为 `VERIFIED`，也不会进入五小时岗位采集任务。

本轮新增 15 家互联网企业入口，均保留为 `TARGET`/`ACTIVE_LEAD`：腾讯音乐、巨人网络、三七互娱、同程旅行、满帮、斗鱼、库洛游戏、芒果 TV、喜马拉雅、阅文集团、去哪儿、虎牙、美图、4399 游戏和网龙。登记依据为企业招聘官网或可追溯的官方 ATS 入口；其中满帮、芒果 TV 等 Moka 链接以及 Hiring Radar 提供的库洛游戏入口仍需企业官网反向确认，不能计入已核验来源。4399 的历史 HTTP 入口另记录为安全边界复核项。

2026-09-09 追加 13 家互联网/数字服务企业入口：荣耀、极兔速递、中通快递、叮咚买菜、盒马、微众银行、Momenta、蘑菇街、旷视科技、Keep、顺丰、安能物流和苏宁易购。它们均登记为 `TARGET`，在入口目录中以 `ACTIVE_LEAD` 展示；本批没有新增 `VERIFIED` 来源。荣耀、极兔、中通、盒马、微众银行、Momenta、蘑菇街、旷视科技和 Keep 的公开入口可完成基础访问探测；叮咚买菜和苏宁返回 403，顺丰入口返回 502，均保持待审核/阻断边界，不绕过安全策略。详细 URL、探测状态和下一步见 `artifacts/internet-expansion-20260909.json`。

2026-09-09 再追加 5 家互联网/数字服务企业入口：SHEIN、得物、BOSS 直聘、Soul 和房天下，并补齐美团官方校园招聘页证据。入口均登记为 `TARGET`，不会被五小时岗位采集任务请求；得物页面可见 2027 届校园招聘配置，房天下、BOSS 直聘和 Soul 页面可访问，SHEIN Careers 页面可访问但中国大陆当前届信号仍待确认。它们在目录中统一标为 `入口线索·待确认`，详细 URL、探测边界和下一步以 `registry/sources.json` 及 `artifacts/source-coverage.json` 为准。

2026-09-09 继续扩充互联网重点入口：商汤科技、金山办公、度小满、作业帮、掌阅科技和豆瓣，并补齐米哈游、网易游戏、哔哩哔哩、蚂蚁集团、知乎、哈啰、用友和金蝶的可追溯招聘入口。新增和修正来源共 6 个新公司、8 个既有公司入口，全部保持 `TARGET`/`ACTIVE_LEAD`；商汤、米哈游、度小满、金蝶和知乎的公开页面出现 2027 届校招信号，网易互娱、哔哩哔哩、蚂蚁、掌阅和豆瓣仅登记官方招聘入口或当前信号待确认。蚂蚁页面触发安全验证、未绕过；网易游戏旧 `career.netease.com` 地址无法解析，已改为网易官方 `game.campus.163.com`。本批不新增 `VERIFIED` 来源，详细证据和下一步见 `artifacts/internet-expansion-20260909.json`。

2026-09-09 互联网扩容批次 4 新增电魂网络、诗悦网络、游卡网络、散爆网络、拾象科技、不鸣科技、MetaApp、句子互动、面壁智能、零一万物、爱笔智能和新浪等 12 家注册企业，并为微博补充官方 careers 入口线索。企业官网均完成一次低频公开可达性检查，结果与边界记录见 `artifacts/internet-expansion-20260909-batch4.json`；其中不鸣科技页面仅发现往届校园栏目，新浪页面以社会招聘为主，均不能据此确认 2027 届校招。13 个新增/补充入口全部保持 `TARGET`，来源等级为 B，暂不自动采集、不计入 `VERIFIED`，后续仍需完成当前届信号、企业官网反向确认、robots/条款、岗位抽查和投递域名白名单。
2026-09-09 互联网扩容批次 5 新增易娱网络、爱诗科技和生数科技 3 家游戏/AI 企业入口。三个官方企业站均完成一次低频可达性检查，结果见 `artifacts/internet-expansion-20260909-batch5.json`；本批尚未确认 2027 届校园招聘信号，因此来源仍为 `TARGET`，不自动采集岗位，也不计入已核验来源。

2026-09-09 互联网扩容批次 7 新增网易云音乐、欢聚集团、富途、途家和优刻得 5 家互联网企业入口，并更新同花顺官方校招页证据。六个入口均通过低频公开页面检查并保持 `TARGET`；同花顺页面明确显示 2027 届校招，其余入口的当前届信号仍需官方刷新或人工复核。批次记录见 `artifacts/internet-expansion-20260909-batch7.json`，不会自动采集岗位或计入 19 个 `VERIFIED` 来源。

2026-09-09 互联网扩容批次 8 新增波克城市、祖龙娱乐、途牛旅游网、咪咕文化、唯品会、爱奇艺和金山云 7 个互联网企业入口，覆盖游戏、在线旅行、数字内容、电商、长视频和云服务。波克、途牛和金山云官方页面出现 2027 届信号；祖龙、咪咕、唯品会和爱奇艺先登记官方校园入口，当前届信号或岗位接口仍需刷新/复核。7 个来源全部保持 `TARGET`，不会进入五小时岗位采集，也不计入 19 个 `VERIFIED`；页面访问、证据 URL 和边界记录见 `artifacts/internet-expansion-20260909-batch8.json`。

2026-09-09 互联网扩容批次 10 新增第四范式、云从科技、七牛云、青云科技、思谋科技、DolphinDB、北森、涂鸦智能和 PingCAP 9 家公司，并为完美世界、东方财富补齐公开招聘入口。11 个入口均完成低频 HTTPS 可达性检查并登记为 `TARGET`；其中完美世界校园站、东方财富 Moka、第四范式 Moka、七牛云校园站和思谋/DolphinDB Moka 入口可直接访问，其余为官网 Careers/招聘入口，当前 2027 届信号仍需企业官网反向确认。云从科技原 `/careers` 路径返回 404，已按官网导航采用 `/Join`，不绕过访问限制。详细 URL、状态和后续核验见 `artifacts/internet-expansion-20260909-batch10.json`。

岗位页的公司筛选现在同时支持细分赛道和入口状态（官方入口、入口线索·待确认、已同步岗位、仅入口公司）。细分赛道来自互联网重点配置、权威名录或 Hiring Radar 的发现元数据；它只影响展示筛选和排序，不改变来源状态。发布门禁会检查 `companies.json` 的目录状态、入口类型、HTTPS 证据和重复公司 ID，防止失效入口或错误状态进入公开目录。

## 来源等级

- A：企业自有域名或企业明确链接的公开校园招聘 ATS，有结构化岗位详情。
- B：企业官方活动页明确校招届别/批次，但需要普通浏览器渲染；不绕过登录、验证码或反自动化。
- C：第三方或学校页面，只做发现线索，不能直接进入公开目录。
- `BLOCKED`：出现登录、Cookie、验证码、403/429、风控或无法确认届别时隔离，不重试也不发布。

## 2026-09-06 扩容批次

本批新增 11 家公司和 16 个官方招聘入口，全部保持 `TARGET`，只进入“发现—访问边界—适配器—三条岗位抽查”队列，不计入已接入来源：

| 公司 | 官方入口 | 当前处理 |
| --- | --- | --- |
| 拼多多、快手、携程、滴滴 | [PDD 校园](https://careers.pddglobalhr.com/campus/)、[快手招聘](https://zhaopin.kuaishou.cn/)、[携程校园](https://campus.ctrip.com/)、[滴滴校园](https://campus.didiglobal.com/) | 等待公开岗位数据和访问边界核验 |
| 美的、比亚迪、宁德时代、海尔、海信、大疆 | [美的](https://careers.midea.com/)、[比亚迪](https://job.byd.com/portal/mobile/school-home)、[CATL](https://talent.catl.com/)、[海尔](https://www.haier.com/careers/)、[海信](https://hxfw.hisense.com/jiaruwomen/)、[大疆](https://we.dji.com/) | 技术岗位占比高的来源仍执行文社商准入门禁 |
| 中国移动、欧莱雅、阿里巴巴、招商银行、建设银行 | [中国移动](https://job.10086.cn/)、[欧莱雅](https://careers.loreal.com/zh_CN/content/Home?3_110_3=43216538)、[阿里巴巴](https://www.alibabagroup.com/en-US/careers/)、[招行校园](https://career.cmbchina.com/notice/school)、[建行校招计划](https://job.ccb.com/chn/job/plan_index.html?planType=XY) | 等待校招字段、分页和条款核验 |
| 中国电信、平安集团 | [中国电信校园招聘](https://job.chinatelecom.com.cn/wt/TELE/web/index?brandCode=1)、[平安校园招聘](https://talent.pingan.com/recruit/campus.html) | 等待岗位接口、届别和访问边界核验 |

候选池和来源注册表的数量由 `artifacts/company-candidate-backlog.json`、`artifacts/source-coverage.json` 自动生成；候选公司的官方入口存在，不代表已经抓取岗位。每周任务另外生成 `artifacts/company-discovery.json`，从交易所/国资委等权威名录提取去重后的公司身份线索；该报告只进入人工审核队列，不会自动写入公司注册表或来源状态。

## 2026-09-08 互联网重点审核队列

以下入口已根据企业公开页面登记为 `TARGET`，用于优先安排人工核验；它们尚未具备可运行适配器，因此不计入 19 个 `VERIFIED` 来源，也不会被五小时采集任务请求：

| 公司 | 已登记入口 | 下一步 |
| --- | --- | --- |
| 网易游戏 | [game.career.netease.com](https://game.career.netease.com/) | 核验校招识别、robots/条款、公开岗位结构和三条岗位 |
| 哔哩哔哩 | [jobs.bilibili.com](https://jobs.bilibili.com/) | 核验校园入口与官方投递域名 |
| 蚂蚁集团 | [talent.antgroup.com](https://talent.antgroup.com/) | 核验公开 ATS/DOM 与访问边界 |
| 米哈游 | [jobs.mihoyo.com](https://jobs.mihoyo.com/) | 核验岗位分页、校招届别和投递链接 |
| 小红书、360、贝壳 | [小红书](https://job.xiaohongshu.com/)、[360](https://360campus.zhiye.com/)、[贝壳](https://join.ke.com/) | 仅在完成同一套来源审计后再启用 |

重点配置只改变发现与审核顺序，不会将 `TARGET` 自动提升为 `VERIFIED`；若入口要求登录、Cookie、验证码或返回 403/429，将记录为阻断/待审核并保留上一版目录。

## 2026-09-16 国企上市公司与央企入口发现

本轮以用户提供的 `EN_EquityNatureAll(Merge Query).xlsx` 为只读输入，精确筛选出 1,441 家
`股权性质=国企` 上市公司（1,402 条非空官网、39 条缺失；1,424 家正常上市、17 家其他上市状态；
截止日期均为 2025-12-31）。国资委官方正文页的双栏解析得到 99 家中央企业集团。官网探测按每批
最多 100 个不同域名、同域串行、跨域最多 8 并发和至少 0.5 秒间隔完成 15 批，结果写入
`artifacts/state-owned-source-discovery.json`。

全量探测发现 540 个招聘入口候选，其中 132 个出现北森、Moka 或静态 HTML 结构化迹象；489 个
公开访问受阻，359 个只能人工导入，461 个待人工复核。ATS 迹象分布为北森 54、Moka 13、静态
HTML 92（一个候选可同时命中多个迹象）。所有记录仍是 `TARGET` 且 `runnable=false`，本轮没有
升级 `VERIFIED` 来源，也没有新增自动抓取或文社商门禁岗位。入口发现证据不改变现有 20 个已核验
来源和 992 条活跃岗位目录；异常、阻断或失败结果均保留在审核队列，不会清空旧快照。

`company-discovery.json` 是发现证据而不是岗位数据。当前解析器对已登记的公开 JSON 分页接口使用声明过的分页参数，对普通 HTML 只读取表格单元格；每个权威来源最多读取 4 MB，报告只保存公司名称、股票代码、名录来源、分页/可达性状态和稳定身份键，不保存响应正文。2026-09-08 的运行发现 1,701 条上交所候选记录，另有深交所、北交所、港交所和国资委入口分别记录可达或阻断状态；这些记录均仍需人工确认企业官网招聘关系，不能计入已接入来源。

2026-09-06 的一次低频落地页探测检查了 29 个 `TARGET` 来源：20 个可达、1 个返回 403 并保持阻断、9 个出现超时/连接错误或非预期状态。该结果只用于安排人工核验，不会改变 `TARGET`/`VERIFIED` 状态，也不会把页面内容写入报告。

### 公开 ATS 适配器边界

采集器提供 Feishu、Workday CXS、Greenhouse、Lever、Ashby、北森 iTalent/Wecruit、Teamtailor、Recruitee、SuccessFactors、Workable、JSON-LD、RSS/XML 和普通服务器渲染 DOM 的保守解析器。它们只接受来源注册表中人工登记的公开端点/选择器，保留官方投递链接并执行校招/社招过滤；缺少公开投递链接、岗位列表结构或校招证据时会将本次抓取标记为不完整。适配器不会执行页面脚本、读取 Cookie 或登录态，也不会猜测隐藏 API；Moka 目前只在发现报告中标记为待人工复核，不执行解密或访问控制绕过。适配器测试使用脱敏夹具，来源仍必须完成官方性、robots/条款、三条岗位抽查和投递域名白名单核验后，才可将 `TARGET` 改为 `VERIFIED`。

## 开源候选

| 项目 | 许可证 | 本项目边界 |
| --- | --- | --- |
| [Hiring Radar](https://github.com/simonlin1212/Hiring-Radar) | MIT | 作为中国招聘源和解析器结构参考；只选择性复用许可允许的适配器/夹具，重写校招门禁、质量门禁、调度和发布流程。原项目命令写死 `python3`，本项目使用当前 Python 解释器并在 Windows CI 验证。 |
| [ats-scrapers](https://github.com/kalil0321/ats-scrapers) | MIT | 选择性复用 Workday、Greenhouse、Lever、Ashby、SuccessFactors 等标准 ATS 适配器和脱敏夹具；不使用托管数据集作为中国主数据源。 |
| [JobSync](https://github.com/Gsync/jobsync) | MIT | 只参考收藏、看板和申请阶段交互；其 Next.js/SQLite/服务端账号架构不整仓继承。 |
| [Rambo-WuDi/JobTracker](https://github.com/Rambo-WuDi/JobTracker) | MIT | 第二阶段浏览器扩展参考页面提取策略。 |
| [autumn-job-assistant-tracker](https://github.com/ljkss/autumn-job-assistant-tracker) | 未提供许可证 | 仅作市场存在性证据，不复制代码、素材或配置。 |
| [graduate-jobs-mvp](https://github.com/lantxgx/graduate-jobs-mvp) | 未提供许可证 | 仅作市场线索，不复用实现。 |
| [job-application-tracker-extension](https://github.com/zoepan0109-coder/job-application-tracker-extension) | PolyForm Noncommercial | 不采用；属于 source-available 而非 OSI 开源，限制未来运营/商业化。 |
| [Campus2027](https://github.com/Picrew/Campus2027) | 未提供许可证 | 只把链接当检索线索，回到企业官网独立核验，不复制列表。 |

### 构建期第三方依赖

| 依赖 | 许可证 | 使用边界 |
| --- | --- | --- |
| [vite-plugin-singlefile](https://github.com/richardtallent/vite-plugin-singlefile) | MIT | 仅作为 Vite 构建插件，将生产脚本和样式内嵌到 `dist/index.html` 以支持本地双击打开；不采集数据、不运行在用户端，保留其 MIT 版权与许可证。 |
| [Simple Icons](https://github.com/simple-icons/simple-icons) | CC0-1.0 | 仅将本地品牌路径用于视觉识别；这不是企业官方 Logo 的背书。完成企业一方素材授权和来源审计后，可通过 `CompanyLogo` 组件替换；没有可靠资产时始终显示文字标识。 |

### 前端设计参考

| 项目 | 许可证 | 本项目边界 |
| --- | --- | --- |
| [shadcn/ui](https://github.com/shadcn-ui/ui) | MIT | 参考其可组合组件和信息层级；当前界面没有复制其模板代码或品牌素材。 |
| [Magic UI](https://github.com/magicuidesign/magicui) | MIT | 参考其校园产品的节奏与轻量动效；本项目保留低动效和离线优先约束，没有复制组件代码。 |
| [React Bits](https://github.com/DavidHDev/react-bits) | 未提供 SPDX 许可证 | 未采用其代码或素材，避免在许可证不明确时复用。 |

完整的直接依赖清单、许可证和后续复制代码的版权要求见 [`THIRD_PARTY_NOTICES.md`](./THIRD_PARTY_NOTICES.md)。

### 公司标识资产

腾讯卡片使用仓库内的本地 PNG 方形标识，来源为 [腾讯官网公开的方形品牌资源](https://www.tencent.com/wp-content/uploads/2024/05/cropped-04_Tencent_Graphics2-192x192.png)；联想卡片使用仓库内的本地 PNG 标识，源文件来自 [联想官网 favicon](https://www.lenovo.com/favicon.ico)，核验日期均为 2026-09-02。两者只用于识别公司，不代表企业与本项目存在合作或背书关系。其余公司优先使用本地 Simple Icons 品牌路径；无法确认或不适合方形裁切的标识继续显示中文文字回退。后续获得企业授权的 SVG/PNG 后，可在同一 `CompanyLogo` 组件中替换并补充来源记录。

## 采集门禁

1. 仅访问公开、无需登录的企业招聘信息；不收集候选人简历、手机号、联系人、Cookie 或个人内推码。
2. 同一域名串行请求并随机间隔；只对超时和 5xx 做有限退避，401/403/429/验证码不重试。
3. 单次岗位数较上次下降超过 50% 时隔离，抓取失败不改变旧目录。
4. 岗位需连续两次完整成功抓取且缺失，才允许标记关闭；关闭岗位保留 90 天。
5. 只发布企业域名或已核验企业 ATS 的投递链接；外部 HTML 在采集端转纯文本并截断，前端不渲染来源 HTML。
6. 公司行业、所有制、规模由人工注册表维护；无证据写 `未知`，不调用不透明模型猜测。

## 岗位受众准入审计

`collector/audience_policy.py` 的 `humanities-social-business-v1` 是所有来源共用的发布前门禁。它将完整归一化岗位分为 `TARGET_GENERALIST`（公开）、`OUT_OF_SCOPE`（明确技术/医学/法务/专门专业门槛，不公开）和 `NEEDS_REVIEW`（信息不足，不公开）。岗位数量骤降和来源健康仍按官网完整抓取数量计算，不会因为过滤技术岗位误触发隔离。

每次构建的 `apps/web/public/data/manifest.json` 会记录受众策略版本及通过、排除、待核验数量；`apps/web/public/data/sources.json` 分别保存 `fetchedJobCount`、`eligibleJobCount`、`excludedJobCount` 和 `reviewJobCount`。不含完整 JD 的 `artifacts/audience-filter-report.json` 保存按来源、原因码聚合的统计、完整的 `reviewJobs` 轻量清单和有限排除样本。发布前 `collector.release_gate --jobs-dir ...` 会重新从详情分片执行同一规则，目录中出现不合格岗位会阻止发布并保留上一版。

边界口径：软件/算法/硬件/工程研发、医学临床、法务合规、生产工艺及强制设计/美术/建筑/体育专业或作品集优先排除；技术专业仅为“优先”且同时接受文社商或不限专业时允许；Excel、SQL、BI、Python、建模等技能不构成排除；名称无法判断且没有专业信息的岗位进入待核验。既有用户本地快照不会被删除，进度页会显示“历史岗位 · 已退出公共库”。

## 自动更新节奏

`.github/workflows/update-catalog.yml` 使用 `17 */5 * * *`，约每五小时触发一次。该节奏只负责调度，来源仍按串行、低频、域名白名单和公开页面门禁执行；抓取失败或来源骤降时保留上一版目录，不把空结果直接发布为岗位关闭。

## 替换记录

目前没有静默替换。基础公司注册表为 252 家，与固定发现输入合并后的候选池为 358 家；`registry/sources.json` 登记 235 个来源，其中 20 个已完成公开访问审计并进入试运行：腾讯、字节、百度、京东、蔚来、小鹏汽车、梅花生物、普源精电、亚信安全、水羊股份、影石创新、莉莉丝、德赛西威、中科创达、拓竹科技、亿咖通、仙工智能、小马智行和 Robinhood。本次 2026-09-14（上海时间）的目录包含 1,020 条通过岗位级校招与受众准入的记录，其中 992 条活跃；完整抓取观测到 4,537 条岗位，992 条通过文社商友好准入，3,330 条明确超出范围，215 条待核验。当前目录已经不是演示数据并达到 20 家试运行门禁，但距离“50 家正式验收”仍有明显差距。互联网重点配置已扩展到 198 家，其中 198 家已有登记来源、5 家当前可运行；静态公司入口目录包含 270 家企业（20 个官方入口、250 个入口线索·待确认）。重点配置只改变发现顺序，不会将 `TARGET` 自动计为已接入。

本轮抽样链接审计见 `artifacts/source-audit.json`；来源岗位数已按受众准入后的公共目录计数，完整抓取与过滤数量见 `artifacts/audience-filter-report.json`。百度本轮抽查 3 条岗位，官方 `GRADUATE` 接口当前返回 145 条原始校招岗位，其中 39 条通过受众门禁；其 `robots.txt` 当前为 HTTP 404，已记录为来源审计风险并采用低频串行访问。抽样成功只证明本轮公开可访问，不代表企业长期授权或岗位永远有效。

公司接入优先级报告见 `artifacts/source-coverage.json`。当前 20 家试运行企业中，15 家为已核验的上市且登记规模区间不少于 500 人的企业；百度按官方投资者关系页记录为纳斯达克与港交所上市、全职员工约 33,500 人。字节跳动作为互联网行业覆盖例外明确标记为规模和上市状态未知，莉莉丝作为游戏行业覆盖例外标记为未上市、规模未知，拓竹科技保留公开校招来源但规模和上市状态未知，仙工智能已核验上市但尚未找到一手员工规模数字。亿咖通按官方投资者关系页记录为纳斯达克上市、员工约 1,400 人，小马智行按官方年报记录为纳斯达克与港交所上市、员工约 1,669 人，Robinhood 的规模保持“未知”。Point72 仍是 `TARGET` 人工导入线索，不计入试运行企业。不会把缺少证据的规模写成确定值，其余公司保持 `TARGET` 或事实字段为 `未知`，不会为了扩大数字自动标记为已接入。

若目标来源关闭、需登录或被阻断，须记录“原目标、失败原因、替代来源、核验日期”，再按计划顺序启用替补公司。腾讯采集器每次先使用官方公开字典确认校招筛选代码，只请求应届生、实习生和青云计划；飞书采集器使用校园招聘类型 `201`，不请求社招类型 `101`。Moka AES 解密、Cookie、登录态、验证码与访问控制绕过仍明确禁止。
