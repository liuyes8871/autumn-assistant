# 第三方依赖与复用说明

本项目自己的代码以 AGPL-3.0 发布。以下是首版直接使用的主要第三方依赖；它们的许可证文本随 npm 包发布，构建时不会把用户个人数据发送给这些项目。

| 依赖 | 用途 | 许可证 | 项目地址 |
| --- | --- | --- | --- |
| React / React DOM | Web UI | MIT | https://github.com/facebook/react |
| Vite / `@vitejs/plugin-react` | 构建与开发服务器 | MIT | https://github.com/vitejs/vite |
| `vite-plugin-pwa` | Service Worker 与 PWA manifest | MIT | https://github.com/vite-pwa/vite-plugin-pwa |
| `vite-plugin-singlefile` | 本地双击打开时内嵌构建产物 | MIT | https://github.com/richardtallent/vite-plugin-singlefile |
| Radix Select / Dialog / Popover / Tabs | 无障碍交互基础组件 | MIT | https://github.com/radix-ui/primitives |
| shadcn/ui 组件模式 | 本地复制并定制的 Button、Input、Label、Select、Popover、Command、Checkbox 组件结构 | MIT | https://github.com/shadcn-ui/ui |
| Tailwind CSS / `@tailwindcss/vite` | 本地 UI utility 编译与 Vite 集成 | MIT | https://github.com/tailwindlabs/tailwindcss |
| Phosphor Icons | 统一功能图标 | MIT | https://github.com/phosphor-icons/react |
| Simple Icons | 本地品牌标识路径（缺少可靠资产时回退文字） | CC0-1.0 | https://github.com/simple-icons/simple-icons |
| Dexie / Dexie React Hooks | IndexedDB 本地存储 | Apache-2.0 | https://github.com/dexie/Dexie.js |
| Zod | 备份与数据校验 | MIT | https://github.com/colinhacks/zod |
| TanStack Virtual | 长列表虚拟化 | MIT | https://github.com/TanStack/virtual |

## 白墨新章 UI 复用记录

- shadcn/ui CLI 核验版本：`4.21.0`。
- 审阅基准 commit：`3ba91b1cc83e1bbe4ab35a422ff2a694849c5048`。
- Tailwind CSS 与 `@tailwindcss/vite`：`4.3.3`。
- 实际复用范围：组件源码进入 `apps/web/src/components/ui/` 后统一改为白墨令牌、朱砂焦点和 Phosphor 图标；没有引入 shadcn 默认后台主题、远程运行时资源或现成模板。
- 未使用 shadcn `Card` 作为通用容器；公司、投递和日程实体继续由业务结构控制。

## 采集器参考

### 开源连接器复用与自动核验（本轮）

- [Hiring-Radar](https://github.com/simonlin1212/Hiring-Radar)，MIT，固定参考 commit `d89da4632751879a3aa02a9b2565994e71be47cc`。本项目只采用公司种子、飞书/北森租户线索和公开接口字段映射思路；未复制 Moka 解密、登录态、代理或托管岗位全集。
- [ats-scrapers](https://github.com/kalil0321/ats-scrapers)，MIT，固定参考 commit `6b44a1badc9bfbf5cf176f75265cc5729e520e99`。本项目只参考 ATS resolver、分页保护、异常检测和脱敏夹具组织方式；没有引入 `httpcloak`、`cloakbrowser`、隐身浏览器、代理或上游数据集。

实际进入本项目的代码仍是 `collector/` 内的独立实现。新增来源必须通过公开 HTTPS、校招证据、企业身份、投递域名、字段完整度、重复率和连续健康运行检查，才能标记为 `AUTO_VERIFIED`；上游项目和租户清单本身不会触发发布。

- [Hiring Radar](https://github.com/simonlin1212/Hiring-Radar)：MIT。固定参考 commit `d89da4632751879a3aa02a9b2565994e71be47cc` 的公司/ATS 发现线索；本项目不复制上游抓取代码、Moka 解密逻辑或登录态。保留上游版权与完整许可见 [`third_party/Hiring-Radar-LICENSE.txt`](./third_party/Hiring-Radar-LICENSE.txt)。
- [ats-scrapers](https://github.com/kalil0321/ats-scrapers)：MIT。固定参考 commit `6b44a1badc9bfbf5cf176f75265cc5729e520e99` 的标准 ATS 适配器、分页保护和脱敏夹具思路；没有把其托管数据集当作本项目主数据源。
- [job-pro](https://github.com/HA7CH/job-pro)：MIT。只借鉴通用 ATS factory 与公司配置表的组织方式；没有接入其 CDP/反风控、猎聘第三方 fallback、Moka 解密或自动投递路径。
- [Scrapy](https://github.com/scrapy/scrapy)：BSD 3-Clause。当前未作为运行时依赖；仅保留为未来在来源规模和队列需求显著增长时的基础设施候选。
- [JobSync](https://github.com/Gsync/jobsync)：MIT。只参考申请阶段和看板交互；没有继承其 Next.js、SQLite 或服务端账号架构。

如果后续继续复制或改编第三方源代码，贡献者必须在同一变更中写明文件、上游 commit、版权声明和许可证全文位置，并在发布前重新检查 AGPL-3.0 的兼容性。

## 企业品牌资产

`apps/web/src/assets/company-logos/tencent.png` 来自腾讯官网公开资源 [cropped-04_Tencent_Graphics2-192x192.png](https://www.tencent.com/wp-content/uploads/2024/05/cropped-04_Tencent_Graphics2-192x192.png)；`apps/web/src/assets/company-logos/lenovo-official.png` 来自联想官网公开 favicon [lenovo.com/favicon.ico](https://www.lenovo.com/favicon.ico)，并转换为本地 PNG 以便离线 PWA 使用。两者仅作公司识别使用，不表示企业背书。企业名称和 Logo 仍属于各自权利人的商标或品牌资产；后续新增一方 Logo 前必须记录来源、核验日期和使用边界。
