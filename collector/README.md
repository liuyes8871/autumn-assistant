# Collector

采集器负责把经过来源门禁的岗位快照转成 GitHub Pages 可直接读取的静态数据。当前 `demo_raw.json` 只是脱敏夹具，不代表实时来源；生产模式只会请求完成审核、状态为 `VERIFIED` 或证据完整的 `AUTO_VERIFIED` 的公开来源。

## 目录生成

```bash
python -m pip install -r collector/requirements.txt
python -m collector.cli --input collector/demo_raw.json --output apps/web/public/data
```

实时模式（不传 `--input`）：

```bash
python -m collector.cli --sources registry/sources.json --state collector/state.json --output apps/web/public/data
```

实时模式允许运行人工 `VERIFIED` 和证据完整的 `AUTO_VERIFIED` 来源；两者都必须有公开 HTTPS 端点、校招限定和域名白名单。`TARGET`、`PROVISIONAL`、`QUARANTINED`、`BLOCKED` 仍只进入审计队列，不会发起正式采集。当前支持腾讯、飞书、百度、京东、Workday、Greenhouse、Lever、Ashby、北森现代/旧版、Teamtailor、Recruitee、SuccessFactors、Workable、SmartRecruiters、Personio、BambooHR、Breezy、Oracle、iCIMS、JSON-LD、RSS/XML 和受控 DOM；BOSS、Moka、登录墙、验证码和安全挑战永远不会自动运行。所有公开请求（包括分页 POST）都会在服务端提供时保存 ETag/Last-Modified 等校验元数据，304 时复用上一次岗位快照；响应内容 hash 用于变化追踪，最近三次完整抓取的中位数用于异常降幅隔离。`--min-verified-sources` 统计人工与自动核验来源的可发布总数，但 manifest 同时保留两类来源的独立计数。

公司接入队列按 `registry/internet-focus.json` 的互联网重点层级优先，再按“已上市且已核验员工规模不少于 500 人”排序；没有证据时不会猜测。重点配置只改变发现顺序，不会提升来源状态：

```bash
python -m collector.discovery --companies registry/companies.json --sources registry/sources.json --focus registry/internet-focus.json --output artifacts/source-coverage.json
```

对 `TARGET` 来源生成 ATS、公开 feed、JSON-LD 和 sitemap 候选提示（只读、不会升级来源状态）：

```bash
python -m collector.discovery --companies registry/companies.json --sources registry/sources.json --discover-target-sources --output artifacts/source-coverage.json
```

候选提示只保存 ATS 类型、候选 URL、当前届信号和复核原因，不保存页面正文。人工完成官网反向确认、robots/条款、校招性质和岗位抽查后，才可以把实际 endpoint 写回来源注册表。

发现报告中的 `classification` 把每个目标来源明确分到四个后续动作：
`CONNECTOR_CANDIDATE`（已有公开解析器或结构化入口）、`NEEDS_MANUAL_REVIEW`
（识别到 ATS 但 endpoint/租户契约仍需人工确认）、`MANUAL_IMPORT_ONLY`
（没有安全的公开连接器，只能由用户主动导入）和
`PUBLIC_ACCESS_UNAVAILABLE`（404、401/403/429、超时或其他不可公开访问）。
`fieldCompleteness` 只统计标题、投递 URL、地点、描述、发布日期和招聘组织等
结构化字段的存在率；这些指标和候选 endpoint 都不能绕过 `VERIFIED` 门禁。

无法公开提供接口的岗位可以由用户主动导入本地 inbox，仍会经过岗位归一化、校招判断、受众门禁和去重：

```bash
python -m collector.inbox --input collector/inbox-import.json --output collector/local-inbox.json
python -m collector.cli --sources registry/sources.json --state collector/state.json --inbox collector/local-inbox.json --output apps/web/public/data
```

inbox 只接受 HTTPS 岗位/来源链接，敏感字段、Cookie、token、请求头、验证码和原始 HTML 会被丢弃；本地导入不会增加 `VERIFIED` 来源数量。

每日发现工作流会额外使用 `--check-candidate-sources` 低频串行检查 `TARGET` 来源的公开落地页，只记录 HTTP 状态、内容类型、可达性和阻断/错误类型，不保存响应正文，也不会自动将来源提升为 `VERIFIED`。遇到 401、403、429、验证码或安全验证直接进入待审核/阻断记录，不重试绕过。

公司候选池与岗位来源保持分离。候选池只生成发现/审核报告，不会因为出现在交易所、国资委、互联网协会百强或 Hiring Radar 种子中就自动变成可抓取来源：

```bash
python -m collector.candidate_sync \
  --companies registry/companies.json \
  --sources registry/sources.json \
  --focus registry/internet-focus.json \
  --output artifacts/company-candidate-backlog.json
```

每周候选任务还会对交易所、国资委等权威名录做一次低频解析，生成
`artifacts/company-discovery.json`。解析器支持已登记的公开 JSON 分页接口和普通
HTML 表格，最多读取 4 MB 响应并只保留公司名称、股票代码、名录来源和去重后的身份键；
新名称会标记为 `DISCOVERED`，与注册表已有公司会标记为 `MATCHED_REGISTRY`。这个报告
是发现队列，不是来源注册表：不会自动新增公司、不会自动生成招聘 URL，也不会将候选或
名录页面的内容写入公共岗位目录。只有人工核验企业官网/官方 ATS、robots 与条款、访问
边界、校招性质、三条岗位抽查和适配器测试后，才可更新 `registry/sources.json` 的状态。

中国互联网协会《2025 年中国互联网综合实力前百家企业》作为固定的一手候选索引，保存在
`registry/internet-authority-top100.json`。运行 `npm run collector:authority` 会生成
`artifacts/internet-authority-import.json`，报告 100 条原始排名、与注册表的匹配、去重和冲突；
索引只用于候选发现，不会凭名录创建官方招聘入口。Hiring Radar 的 157 条公司/ATS 种子同样
固定在 `registry/hiring-radar-seed.json`，运行 `npm run collector:hiring-radar` 可生成导入报告。
运行 `npm run collector:candidates` 时，两类固定发现输入会与现有注册表合并，当前生成 326 家去重候选；报告中的 `discoverySource`、`hiringRadar`、`doNotPublishAsConnected` 和 `nextAction` 用于追踪来源边界。含招聘入口 URL 的 Hiring Radar 记录可进入公司入口层成为 `ACTIVE_LEAD`，但在每日当前届信号/企业官网核验完成前不会进入 `VERIFIED` 岗位采集。

候选池每周更新；岗位来源仍由 GitHub Actions 约每 5 小时检查一次。设置页会分别展示候选公司、已核验来源、当前有合格岗位的公司和有规模证据的 500 人以上企业，避免把目标名单误认为已接入岗位。

每日发现任务还会对权威候选发现页和注册表中的 `TARGET` 官方招聘落地页做一次低频、串行的可达性检查：只记录 HTTP 状态、内容类型和粗略访问结果，不保存响应正文，也不会从交易所名录自动推断企业招聘入口。401/403/429、验证码或条款限制会进入阻断/待审核报告，不重试绕过；只有人工补齐企业官网或官方 ATS 证据、访问边界、校招识别和至少三条岗位抽查后，才允许把来源从 `TARGET` 提升为 `VERIFIED`。

入口层每日任务可使用：

```bash
python -m collector.company_discovery \
  --companies registry/companies.json \
  --probe-career-entries \
  --entry-state collector/company-directory-state.json \
  --output artifacts/company-entry-discovery.json
```

它只读取 HTTPS 企业招聘入口，检测 `2027 届`、秋招或校园招聘开放等可见信号，保存状态码、信号码和 URL 证据，不保存 HTML、Cookie 或重定向正文。暂时不可访问的入口先进入 `STALE`，连续失败后转为 `INACTIVE`；该报告不会自动把来源升级为 `VERIFIED`。

生成真实目录后，可对每个成功来源抽样并核验投递域名/HTTP 状态：

```bash
python -m collector.audit --catalog apps/web/public/data/catalog.json --sources registry/sources.json --output artifacts/source-audit.json --check-links
```

来源健康报告只输出计数、字段完整度、重复率、届别未知率、详情成功率、freshness 和 304 命中，不包含岗位正文：

```bash
python -m collector.health --sources apps/web/public/data/sources.json --state collector/state.json --output artifacts/source-health.json
```

发布前可额外检查活跃岗位字段和 HTTPS 链接：

```bash
python -m collector.release_gate \
  --manifest apps/web/public/data/manifest.json \
  --catalog apps/web/public/data/catalog.json \
  --jobs-dir apps/web/public/data/jobs \
  --companies apps/web/public/data/companies.json \
  --min-verified-sources 20
```

生成器会：

- 通过 Pydantic 校验字段和 URL；
- 识别并拒绝社招/未确认校招岗位；
- 删除脚本、样式和危险 HTML，只保留截断后的纯文本；
- 优先使用来源岗位 ID，否则使用公司、标题、城市、届别和官方 URL 的稳定哈希；
- 输出列表目录、详情分片和 manifest；
- 同时输出 `campaigns.json`、`sources.json` 和（存在公司注册表时）`companies.json`；manifest 的业务日期统一为 `Asia/Shanghai`；
- 将来源地点归一化为中国大陆/港澳台/海外/远程/未知，并保留原始地点文本；中国大陆继续拆到省份、城市和已知区县；
- 记录来源质量报告，岗位量骤降超过 50% 时隔离。
- 在完整归一化结果之后执行版本化的文科、社科、商科友好受众准入门禁：`TARGET_GENERALIST` 才会进入公共目录，`OUT_OF_SCOPE` 和 `NEEDS_REVIEW` 进入 `artifacts/audience-filter-report.json`，不使用大模型猜测专业门槛。
- 受众审计报告同时保存总体 `reasonCounts`、逐来源 `bySource` 统计和不含完整 JD 的 `reviewJobs` 清单；排除岗位只保留有限样本，便于复核而不会把完整招聘文本写进审计产物。
- 来源健康和骤降判断使用官网完整抓取数量，不能因为过滤技术岗位而误触发来源隔离；失败抓取继续保留上一次通过准入的公共快照。
- 发布门禁会重新从详情分片执行同一准入规则，发现不合格岗位时整次发布失败，避免有人只修改轻量列表目录绕过门禁。
- 200 响应如果没有可识别的岗位列表结构，会标记为不完整并保留上一版快照，不把风控页或接口改版误判为空目录。
- 同时校验来源页和投递页仍在已审核的企业/ATS 域名下；来源页或投递页为 HTTP、伪造域名或短链时拒绝发布。
- 不同域名最多四组并行，同一域名始终串行；分页达到安全上限仍未结束时将整次抓取标记为不完整，不发布截断结果。

生产适配器需要实现同样的 `RawJob` 输出，并在来源审计中证明官方性、访问边界和校招识别依据。请使用 `sys.executable` 调用子进程，以兼容 Windows，不要写死 `python3`。

## 公司入口目录

公司校招入口和岗位来源是两个独立层级。已登记公开招聘网址的企业可以
作为 `ACTIVE_LEAD` 入口展示；只有完成来源审核并通过岗位受众门禁的来源
才会自动发布具体岗位。已有静态目录更新时，可以只刷新入口文件，不重新
请求任何招聘站点：

```bash
npm run collector:directory
```

该命令会更新 `apps/web/public/data/companies.json` 和 manifest 中的
`companyDirectory` 摘要。当前静态目录包含 270 家可追溯入口（20 个官方入口、
250 个入口线索·待确认）；没有每日入口状态文件时使用兼容回退，只纳入有公开招聘
URL 的候选。CI 的每日入口任务会写入 `collector/company-directory-state.json`，
之后以当前届官网信号为准，只公开 `ACTIVE_CONFIRMED` / `ACTIVE_LEAD`，并将
`STALE`、`INACTIVE`、`BLOCKED` 隐藏。无论哪种模式，`TARGET` 都不会被升级为
`VERIFIED`，入口线索也不会被岗位采集器自动运行。

## 国企上市公司与央企入口发现

`collector/state_owned.py` 是一个只读的 Excel 导入器。它直接读取用户提供的
`EN_EquityNatureAll(Merge Query).xlsx`，精确保留 `股权性质 = 国企` 的记录，股票代码始终按六位
字符串保存；原始工作簿不会复制到 `apps/web/public` 或提交到仓库。混合股权、缺少官网、多个官网地址和
异常网址都会进入复核队列。Excel 中的公司网址只代表“从哪里开始找”，不会被写成 `careerUrl`，也不会
凭自身升级为岗位来源。

国资委 99 家中央企业集团由 `collector/sasac.py` 读取官方正文页的左右双栏名单，生成
`registry/sasac-central-enterprises.json`。解析器在数量不是 99 或序号不连续时拒绝替换上一版名单；
集团名录只是身份和官网发现证据，不是招聘岗位来源。

运行入口发现（每批最多 100 个不同域名、同域串行、跨域最多 8 个并发、请求间隔至少 0.5 秒）：

```bash
npm run collector:state-owned:import
npm run collector:state-owned:discover
```

手动续跑某一批时显式指定批号并复用已有报告，例如：

```bash
python -m collector.state_owned_discovery \
  --excel "C:/Users/<user>/Desktop/中国上市公司股权性质文件(联表查询)233542178/EN_EquityNatureAll(Merge Query).xlsx" \
  --companies registry/companies.json \
  --sasac registry/sasac-central-enterprises.json \
  --output artifacts/state-owned-source-discovery.json \
  --previous artifacts/state-owned-source-discovery.json \
  --batch 2 --batch-size 100 --max-domain-workers 8 --interval 0.5
```

完整结果保存在 `artifacts/state-owned-company-candidates.json` 和
`artifacts/state-owned-source-discovery.json`。发现器只跟随企业官网公开的招聘/人才/校园招聘链接，记录
ATS、JSON-LD、RSS/XML、sitemap、静态页面和当前届信号等轻量证据，不保存 HTML、Cookie 或请求正文。
公开响应若提供 `ETag` / `Last-Modified`，发现器只保存这些校验标识和内容 hash；下次检查会带上
`If-None-Match` / `If-Modified-Since`，收到 304 时复用上一条轻量结果，不重新解析详情。
每条结果都保持 `sourceStatus=TARGET`、`runnable=false`，并分为 `CONNECTOR_CANDIDATE`、
`NEEDS_MANUAL_REVIEW`、`MANUAL_IMPORT_ONLY`、`PUBLIC_ACCESS_UNAVAILABLE` 四类。只有补齐官网反向
链接、robots/条款、当前届证据、至少三条岗位抽查、投递域名和字段质量后，才允许人工登记为
`VERIFIED`；因此“入口候选数”不等于“已接入来源数”，更不等于“新增岗位数”。

发现任务按批次从第 1 批到最后一批保存进度。重复运行时通过 `--previous` 保留已完成批次；官网失败、
超时或触发 401/403/429/验证码不会清空旧结果，也不会尝试绕过访问控制。需要补充岗位的受阻来源，
只能由用户主动把公开岗位链接导入本地 inbox，仍会经过同一套归一化、校招和文科/社科/商科准入门禁。

仅登记新入口或刷新候选池后，可运行 `npm run collector:sources` 将注册表中的来源元数据同步到
`apps/web/public/data/sources.json`。该命令不访问招聘站点，只为新增 `TARGET` 行填入
`not_ready` 状态，并保留既有来源的健康与岗位计数；下一次五小时采集成功后再由实时构建更新计数。

### 岗位数量优先的公开入口临时采集

如果不希望等待逐家公司完成正式来源审核，可以运行：

```bash
npm run collector:state-owned:provisional
```

该命令读取 `artifacts/state-owned-source-discovery.json` 中的公开 HTTPS 招聘入口，复用岗位归一化、去重和文科/社科/商科准入规则，并生成：

- `artifacts/state-owned-provisional-jobs.json`：完整采集审计报告；
- `apps/web/public/data/provisional-jobs.json`：网站可读取的临时岗位快照。

这条通道只为提高覆盖和岗位数量，不会登录、读取 Cookie/token、执行验证码绕过，也不会把来源注册表升级为 `VERIFIED`。当前已按“岗位数量优先”运行：网站会把 497 条通过基础受众口径、以及 684 条仅因信息不足而暂未自动判断的岗位一起发布，共 1,181 条、来自 225 家公司。它们统一显示为“公开入口临时采集 · 待核验”，正式目录、正式来源数和入口状态仍按原门禁统计；明确识别为技术、医学、法务、设计等超出范围的岗位仍不会发布。后续运行 `npm run collector:state-owned:provisional` 会继续默认带上 `--include-review-jobs`，如需只看低噪声版本，可单独调用 `build_web_catalog(..., include_review=False)`。
