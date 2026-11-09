# 小红书「免复制直发」打通方案调研

- 日期：2026-11-09
- 范围：随行（my-trip-planner）已能生成小红书笔记文案与 3:4 封面卡，本调研解决"最后一公里"——**从平台直接投递到小红书，不复制粘贴**。
- 结论口径：以下所有"当前状态"均为 2026-11-09 实测/官方页面原文，未经验证的标「待验证」，不写推测。

---

## 0. 结论先行

| 问题 | 答案 |
|---|---|
| 现在有官方"发笔记"API 吗？ | **没有**。开放平台 scope 里 `write_notes` 仍是「规划中」；分享 SDK 站点挂着「暂停接入」。 |
| 今天能做到"零复制"吗？ | **能**，但只能靠自动化驱动官方创作服务平台（`creator.xiaohongshu.com`），或移动端系统分享面板。 |
| 建议做哪个？ | 分三层：P0 移动端"一次分享"（零风险，半天）→ P1 自托管发布器（自用/单账号，3–5 天）→ P2 对外多用户**等官方**。 |
| 绝对不该做什么？ | 为 C 端用户托管小红书登录 cookie（等于代持账号控制权）。 |

---

## 1. 我们这边已有的底子（改造量小）

| 资产 | 位置 | 说明 |
|---|---|---|
| 发布器抽象 | `backend/app/services/xhs_service.py:58-88` | 已有 `BasePublisher`（`publish_note` / `list_channels` / `health`）与 `XhsManualPublisher`，注释里就写明"方案 B 预留插槽" |
| 工厂 | `backend/app/services/xhs_service.py:199-204` | `get_publisher("xhs")` 返回实现，换通道只改这一处，接口层零改动 |
| 文案生成 | 同上 `generate_xhs_note()` | LLM 主路径 + 规则模板兜底，带 `source` 诚实标注 |
| 前端对话框 | `frontend/src/components/XhsNoteDialog.vue` | 已有 `copyAll` / `copyBody` / `openApp` / `exportCover`（html2canvas 导出 1080×1440 等效 PNG） |
| 晒图渠道模板 | `backend/app/services/story_service.py:120` | `xhs` 规格 1080×1440 / 3:4，与发布要求一致 |

**关键缺口（这是真正的工作量所在）**：

1. **图片只在前端**。封面卡由浏览器 `html2canvas` 渲染后下载成 PNG，后端 `backend/.venv` 里没有 `Pillow`，项目里没有任何 `UploadFile` / `StaticFiles`。而两条发布路线都需要"图片二进制"：
   - 官方 SDK / API 要**公网可访问的图片 URL**；
   - 自动化发布要**服务端能读到的文件路径**（社区实现明确推荐本地绝对路径，网络图容易失效）。
   → 需要新增：前端 canvas `toBlob()` 上传 + 后端落盘（`POST /api/v1/trips/{id}/xhs-assets`），或后端 Pillow 出图（推荐后者与历史一致、可复用）。
2. **没有发布任务与状态**。发布是异步的（要等审核/风控），需要 job 表或复用 `plan_tasks` 模式，前端要能看 "队列中 / 已发布 / 失败原因"。

---

## 2. 官方通道逐条核实

### 2.1 分享开放平台（agora）— 能力对路，但**暂停接入**

- 站点 `https://agora.xiaohongshu.com/` 原文能力项：**「一键分享」**（第三方 App/网页将图文视频分享到小红书）、**「快速发布」**（基于小红书 App 内置发布能力，自动识别内容类型并挂载话题）、「站内活动联动」。
- SDK 覆盖：iOS / Android / HarmonyOS / JavaScript。
- **当前状态（2026-11-09 实测页面）**：首屏、导航、"常见问题"上方、"更多想象空间"处共 4 处显示 **「暂停接入」**。→ 新应用无法申请。
- 若恢复接入，调用形态（第三方博客与官方文档一致）：服务端用 `appKey/appSecret` 生成 `nonce/timestamp/signature`，前端调 `xhs.share({shareInfo:{type:'normal',title,content,images[]},verifyConfig})` **唤起 App 并预填发布页**，用户在 App 内点"发布"。
- 硬约束：`images` **必须是公网地址**（不支持本地路径）→ 呼应第 1 节的缺口。
- 判定：**合规最好的路，现在走不通**。可做的是登记/商务渠道表达接入意愿，不构成方案。

### 2.2 小红书开放平台（openaccount）— 新平台，只有登录

- `https://openaccount.xiaohongshu.com/docs/quick-start` 原文：「**首期能力**：当前仅开放『用户基本信息』授权范围（`basic_info`）。更多能力将在后续版本陆续开放。」
- `console/apply` 创建应用页 scope 列表：`basic_info`（可申请）、`user_profile` / `read_notes` / **`write_notes`** / `read_followers` **均标「规划中」**。
- 支持 OAuth2 授权码模式、PKCE、Web/车机设备授权（RFC 8628 扫码）、Webhook 通知。审核 1–3 工作日。
- 判定：**注册占位有价值**（未来放量的第一入口，且 app_id 可复用于登录打通），但今天拿不到发布能力。

### 2.3 电商开放平台（open.xiaohongshu.com）— 商家/服务商，需商务

- 面向商家与服务商，需企业资质、逐项申请权限、审核有周期；能力集中在商品/订单/物流/售后 + 广告（聚光 `adapi.xiaohongshu.com`）。
- 广告侧接口（如 `/api/open/jg/note/list`）只做**笔记查询**，**没有发布接口**。
- 判定：普通开发主体拿不到；若随行要做 B 端（旅行定制师账号矩阵），走商务洽谈（蒲公英/服务商入驻）才有戏。

### 2.4 创作服务平台（creator）— **有 Web 发布能力，但没有 API**

- `https://creator.xiaohongshu.com/publish/publish?source=official` 支持图文/视频笔记、定时发布、草稿箱、批量上传。
- 这是**唯一当下真实可用**的发布入口，但它是给人点的页面，无公开接口。
- 判定：**自动化的靶子**。证据：社区成熟实现直接以该 URL 为入口（`xpzouying/xiaohongshu-mcp` 源码 `urlOfPublic = creator.xiaohongshu.com/publish/publish?source=official`）。

---

## 3. 五条路线对比

| # | 路线 | 合规 | 今天可用 | 工作量 | 主要成本/风险 |
|---|---|---|---|---|---|
| A | 官方分享 SDK（agora `xhs.share`） | ★★★★★ | ✗ 暂停接入 | 2–3 天（恢复后） | 零风险，等平台 |
| B | 官方开放平台 `write_notes` API | ★★★★★ | ✗ 规划中 | 3–5 天（放量后） | 零风险，等平台 |
| C | 自托管自动化（Playwright/Rod 驱动 creator） | ★★ | ✓ | 3–5 天 | 风控/协议灰色、选择器维护、会踢掉用户网页端会话 |
| D | 第三方 SaaS / 服务商通道 | ★★☆ | ✓（需商务核实） | 1–2 天对接 | 账号数据出境、按账号付费、对方也可能被限 |
| E | 移动端系统分享面板 + 二维码投递 | ★★★★☆ | ✓（**待真机验证**） | 0.5–1 天 | 体验因机型/App 版本而异，文本可能只进链接卡片 |

### C 路线细节（最现实的"今天就能用"）

- 社区有成熟开源实现 `xpzouying/xiaohongshu-mcp`（Go + Rod，v2.7.0 于 **2026-11-01** 发布，持续活跃），能力与我们要的几乎一一对应：
  - `publish_content(title, content, images[], tags[], schedule_at, is_original, visibility)` — 含**定时发布**（1 小时–14 天）、原创声明、可见范围（公开/仅自己/仅互关好友）
  - `publish_with_video(...)`、搜索、评论、登录二维码（`get_login_qrcode` 返回 base64）
  - 登录态落 `~/.xiaohongshu/cookies.json`；首次人工扫码
- 它的 README 自述的**限制与坑（作者口径，非官方）**：
  1. **同一账号不允许在多个网页端登录**——跑起发布器后，用户自己在电脑上登创作平台会被互相踢；
  2. 有账号被「风控限制网页版发布」的实际案例（Q&A 排查第一条）；
  3. 图片路径**不能含中文字符**；图片过大会失败；
  4. 每天发帖量约 50 篇上限；
  5. UI 一变就要修选择器（v2.7.0 的更新日志里一半是发布/搜索流程的选择器与竞态修复）——**这就是长期维护成本的真实写照**。
- 对我们意味着：技术可行（等于已验证过一轮），但**必须做"半自动"而不是"全自动"**：填好标题/正文/图片 → 停在发布页 → 用户确认点发布。风控、责任、以及"内容最终由人负责"三点都更干净，成本几乎一样。

### E 路线细节（最轻的"免复制"）

- 移动端 H5 页用 `navigator.share({ files: [封面 PNG], text: 正文, url })` 调起系统分享 → 选小红书 → 进 App 发布页。
- 桌面 Web 无法唤起手机 App，所以配套：**发布页二维码** → 手机扫码打开 → 分享。
- **未验证点（必须真机实测）**：小红书 App 接收 web share 时，图片是否直接进发布页、文本落在正文还是仅作链接卡片。不同版本行为不同，所以这条只能当"体验优化"，不能当方案基石。

---

## 4. 推荐落地路径（分层，可独立验收）

### P0 — 半天，零风险，先把"复制"干掉 60%

1. 新增移动端发布投递页 `/xhs/:tripId`（免登录 token 复用现有 `ShareToken` 机制）：展示可编辑文案 + 封面图 + 「分享到小红书」按钮（`navigator.share`，不支持时降级为复制）。
2. `XhsNoteDialog` 加「手机发布」入口：生成二维码指向上面这页。
3. `exportCover` 旁边加「打包下载」（封面 PNG + 正文 txt 的 zip），给"我要在电脑上发"的用户。
4. 后端零改动（文案接口已有）。

验收：手机扫码 → 点分享 → 小红书出现在分享面板；封面图无损。

### P1 — 3–5 天，自用/单账号，真正"平台内一键发"

1. `XhsRpaPublisher(BasePublisher)` 落在 `app/services/publishers/xhs_rpa.py`，`get_publisher()` 按配置切换（`XHS_PUBLISH_MODE=manual|rpa`，默认 manual——**默认不改变现有行为**）。
2. 登录：本地起 headed Playwright 打开 creator 登录页 → 用户扫码 → `storage_state` 落 `backend/var/xhs-state.json`（复用 `chrome-cdp-automation` 技能里"不代输密码/验证码"的红线）。
3. 出图：后端 Pillow 复刻封面卡（推荐），或前端 canvas `toBlob` 上传到 `POST /api/v1/trips/{id}/xhs-assets`（落 `backend/var/xhs-assets/`，文件名去中文）。
4. 发布任务：`POST /trips/{id}/xhs-publish` 返回 job；后台执行"填表 → 传图 → 填标题/正文/话题 → **停住**（默认不点发布）→ 记录截图与 URL"；`GET /xhs-publish/{job}` 回状态。
5. 失败处理：截图落盘 + 错误码分类（登录失效 / 风控 / 图片问题 / 选择器失配），前端给"重新扫码""改用复制"降级按钮。
6. 新依赖：`playwright`（`playwright install chromium`）。⚠️ 当前 venv 无 `playwright`/`Pillow`/`python-multipart`，需一并加。

验收：一个真实行程 → 平台内点「发布到小红书」→ 浏览器自动填好 → 人工点发布 → 笔记真实出现在账号。

### P2 — 对外多用户：**只走官方**

- 等 agora 恢复接入或 `write_notes` 放量；或接第三方服务商并明确告知用户风险。
- **明确不做**：在服务端存用户 cookie 做多租户代发。理由：cookie 等价账号控制权，一旦泄露=账号被盗；且平台协议普遍禁止账号共享/代操作，商业化前需法务结论。

---

## 5. 风险与红线（判断可行性时请重点看这段）

| 风险 | 影响 | 缓解 |
|---|---|---|
| 平台协议/风控 | 网页端发布被限、限流、极端情况封号（非官方授权自动化） | 单账号、低频、真实内容；半自动（人点发布）；不批量矩阵 |
| 同账号多网页端互踢 | 用户自己在电脑上登创作平台会被挤掉 | UI 明确提示；只在"要发布时"启用会话 |
| 选择器随 UI 变更断裂 | 发布失败静默 | 选择器版本化 + 失败必截图 + 立刻降级到复制通道 |
| 图片约束（公网 URL / 无中文路径 / 大小） | 官方 SDK 与 RPA 都卡 | 服务端资产目录用 ASCII 名 + 尺寸校验 1080×1440 |
| 多租户 cookie 托管 | 安全与合规事故 | 不提供；只做本地/单账号模式 |
| 法律 | 模拟操作 + cookie 可能触及平台协议与《反不正当竞争》 | 规模化前法务确认；B 端合作走官方商务 |

---

## 6. 需要你拍板的三个问题

1. **谁在发？**
   - 你自己 / 少数运营账号 → P1 直接可行。
   - 每个 C 端用户发到自己账号 → 只能等官方，或接第三方（P2）。
2. **发布端在哪？** 用户主要在手机 → P0 先上；主要在电脑 → P1 更值（创作平台支持 PC 发布）。
3. **全自动还是半自动？** 建议**半自动**（填好等人点发布）：风控与责任都低一个量级，成本几乎相同。

---

## 7. 30 分钟可做的验证实验（不写业务代码）

1. 真机测 `navigator.share` 到小红书 App 的接收行为（图片是否进发布页 / 文本落点）——决定 P0 的形态。
2. `playwright` 起 headed 浏览器登 `creator.xiaohongshu.com`，只做"打开发布页 + 填标题正文 + 传一张图"，**不点发布**——验证 P1 的可行性与当前选择器。
3. 提交 `openaccount` 创建应用（basic_info，1–3 工作日）——占位未来 `write_notes`，顺带可用于小红书登录。

---

## 附：证据清单（2026-11-09 核查）

| 来源 | 用途 |
|---|---|
| `https://agora.xiaohongshu.com/`（实测页面，4 处「暂停接入」） | 分享 SDK 当前不可申请；能力含一键分享/快速发布；JS SDK 存在 |
| `https://openaccount.xiaohongshu.com/docs/quick-start`（原文） | 「首期能力：当前仅开放 basic_info」 |
| `https://openaccount.xiaohongshu.com/console/apply`（scope 列表） | `write_notes` 等标「规划中」 |
| `https://open.xiaohongshu.com/document/developer/file/1` | 电商开放平台开发者文档入口 |
| `https://ad-market.xiaohongshu.com/docs-center?...`（`/api/open/jg/note/list`） | 广告侧只有笔记查询，无发布 |
| `https://creator.xiaohongshu.com/publish/publish?source=official` | 官方 Web 发布页（自动化靶子） |
| `https://github.com/xpzouying/xiaohongshu-mcp`（v2.7.0, 2026-11-01 release notes） | 自动化发布的可抄实现 + 已知坑（多端互踢、风控、图片命名、日发上限） |
| 掘金《我做了套小红书一键发布系统》 | `xhs.share()` 参数表与签名流程（第三方，与官方字段表一致） |
