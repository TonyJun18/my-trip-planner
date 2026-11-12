# task-share-target-eval 评估记录 · 2026-11-13

> 来源：2026-11-13 竞品分析 §Reels 导入红海潮（Rhyme/Travo/Scoop/Triparchi/Dream Trip/MapDreamy/Pictoura 一周 8+ app 全押原生 share sheet；Stardrift 把视频导入当新卖点）
> 结论：**评估通过，落地 PWA Web Share Target 接收分享（最小版：manifest + SPA 路由 + 预填导入，零凭证）**

## 1. 背景与任务

我们五通道导入（note/screenshot/email/link/social）全部是「**主动粘贴文本**」形态：用户在 app 内打开导入对话框，把分享文本/链接粘进来。
缺「**被动接收分享**」入口：用户在 TikTok/IG 点系统分享 → 直接把链接/文本发给 PWA。

竞品潮（2026-11）：
| 竞品 | 动作 |
|---|---|
| Rhyme / Travo / Scoop / Triparchi / Dream Trip / MapDreamy / Pictoura | 11 月 App Store 一周 8+ app 全押「分享 → 导入」原生 share sheet |
| Stardrift | 把「视频导入」当新卖点宣传 |
| （对照）11-10 task-social-favorites-flow-eval | 曾把 Web Share Target 登记为「不排期」——竞品潮推上前排 |

## 2. 支持矩阵（权威数据：MDN BCD 2026-11 实测）

`manifest.webmanifest share_target` 浏览器支持（mdn/browser-compat-data main 分支 manifests/webapp/share_target.json）：

| 浏览器 | 支持 | 版本/备注 |
|---|---|---|
| Chrome (desktop) | ✅ | 89+ |
| Chrome Android | ✅ | 76+ |
| Edge | ✅ | mirror Chrome |
| Opera / Opera Android | ✅ | 76 / 63 |
| Samsung Internet | ✅ | mirror |
| Firefox / Firefox Android | ❌ | bugzil.la/1476515（parses, no effect） |
| Safari / iOS Safari | ❌ | webkit.org/b/194593 |
| WebView Android / iOS | ❌ | — |

**结论**：Android 生态（Chrome/Edge/Samsung）全部可用，桌面 Chrome 89+ 可用；**iOS Safari 不支持**（用户从 iPhone 的 TikTok/IG 分享时，PWA 不会出现在分享面板）。
→ 落地为**渐进增强**：Android 用户获得「分享 → 随行」入口，iOS 用户保持手动粘贴（社交导入已覆盖）。

## 3. 与既有导入通道的叠加关系

```
系统分享（TikTok/IG/浏览器等）
      │ GET /share-target?title=…&text=…&url=…
      ▼
ShareTargetView（新，登录后 /share-target）
      ├─ 有 text → POST /trips/social/import（社交粘贴解析，纯规则零凭证）
      ├─ 只有 url → POST /trips/link/import（链接收藏兜底）
      └─ 都没有  → 降级引导：说明 + 手动粘贴入口（复用现有对话框能力）
      ▼
候选列表 → 「汇入行程」或「收进收集箱」（复用 favorite-spots collect-first）
```

- **不新增后端**：复用 social_import / link_import 端点（它们本身就是「外部内容敌意源」处理：规则解析、指令行剥离、不抓 URL）。
- **不新增 SW 逻辑**：manifest `share_target` 用 **GET**（纯文本/链接，无文件）→ 系统直接以 GET 打开 `/share-target?…`；SA 的 navigate network-first handler 天然把它当导航请求回退 index.html → SPA 路由接管。
- **不碰文件分享**：分享图片/视频需 POST + multipart + 文件落库，超出「零凭证零抓视频」边界，明确不做（记遗留）。

## 4. 无分享上下文降级

- 直接访问 `/share-target` 且无 query → 展示「从 TikTok/IG 点分享 → 选择「随行」」引导 + 手动粘贴输入框（复用 social 解析），不让用户面对空页。
- 未登录进分享 → 路由守卫 redirect `/login?redirect=/share-target?…`，登录后回来自动解析（AuthView 已支持 redirect 完整字符串）。
- iOS/不支持环境 → 不会进入此路由（share_target 不存在），无影响；手动粘贴入口同样可用。

## 5. 实现（最小版落地）

**manifest**（`frontend/public/manifest.webmanifest`）：
```json
"share_target": {
  "action": "/share-target",
  "method": "GET",
  "params": { "title": "title", "text": "text", "url": "url" }
}
```
- GET 方式：text 分享文本、url 分享链接；不声明 files（不做图片/视频）。

**路由**（`frontend/src/router/index.js`）：新增 `/share-target`（需登录，非 public）。

**视图**（`frontend/src/views/ShareTargetView.vue`）：
- 挂载时读 `route.query`：取 text / url / title。
- 有 text → `api.importSocial({ text })`；否则有 url → `api.importLink({ url })`；都没有 → 降级引导。
- 候选渲染：复用 ImportDialog 同款交互（勾选 → 选行程汇入 / 收进收集箱），不做新 API。
- 外部内容只作为候选数据展示，绝不作为指令执行（后端已剥离 flagged_lines）。

**i18n**：zh-CN / en-US 各加 `shareTarget.*` keys。

## 6. 验收

- [x] 评估记录（本文档）：支持矩阵 + 叠加关系 + 降级路径
- [x] manifest share_target（GET，title/text/url）
- [x] SPA 路由 `/share-target` + 视图预填导入（social 优先 / link 兜底 / 无上下文降级）
- [x] 前端 `npm run build` 通过 + `check:i18n` 通过
- [x] 铁律：零凭证；外部内容敌意源（复用后端剥离）；不抓 URL；无文件分享；不新增后端代码（避免动测试基线）

## 7. 遗留与后续（记入 checkpoint issues）

1. **iOS Safari 不支持 share_target**（webkit.org/b/194593）——iOS 用户维持手动粘贴；若未来 Safari 支持，本实现直接生效无需改动。
2. **文件（图片/视频）分享未做**：需 POST + multipart + 文件存储，超「零凭证」边界，维持不排期（与 Reels 视频解析同理）。
3. **Firefox 不支持**（bugzil.la/1476515）：桌面 Firefox 用户看不到分享入口，手动粘贴兜底。
4. **评估中未做真机 E2E**：Cron 无人值守环境无 Android 设备；白天可在 Android Chrome 安装 PWA 后实测「TikTok 分享 → 随行」链路。