# task-social-collection-eval 评估记录（2026-10-24）

## 结论：可行，零凭证最小版已实现

**task-social-collection-eval**（来自 2026-10-23 竞品分析 append）——Feedtrip 2026
新赛道（TikTok/IG 分享 → 地图 → 行程，视频删除仍保留）启发。

## 竞品实证（2026-10-24 检索）

- **Feedtrip**（feedtrip.app，2026 上线，比利时 solo founder）：粘贴/分享
  TikTok 或 IG 视频/轮播 → 观看视频 + 读 caption → 提取每个提及地点
  （餐厅/咖啡/酒吧/酒店/商店/博物馆/地标），钉在地图上，按城市归档；
  「视频可以删，地点永久保留」（your spots are saved forever, even if the
  original video disappears）；免费 3 次扫描/月，Pro 50 次/月 + Plan my day
  （路线规划）。Instagram carousel（一图一个地点）也能读。
- **Plotline**（iOS）：同类 TikTok/IG 收藏→地图，额外支持 YouTube/博客，
  iOS-only。
- 我们的差距：输入通道已有 note（攻略文本）/screenshot（截图）/email（邮件）/
  link（分享链接）四通道，但**没有「社交收藏文本」（caption）通道**；link_import
  只做 og:title/description 抓取，小红书/IG/TikTok 分享页反爬大概率挡
  （2026-10-22 task-link-import-zh-eval 已评估：小红书不碰深度抽取）。

## 关键评估：三条路线对比

| 路线 | 成本 | 风险 | 结论 |
|---|---|---|---|
| A. 抓 TikTok/IG/小红书分享页 | 需要处理反爬/登录墙/动态渲染 | 高（隐私/被封/内容壳），且视频内容需多模态理解 | ❌ 不做 |
| B. 接平台 API（TikTok/IG 官方） | 凭证+审核+配额 | 高（凭证消耗违反铁律 9） | ❌ 不做 |
| **C. 粘贴 caption 文本 → 规则提取** | 零凭证、零依赖、零网络 | 低；只处理用户粘贴文本 | ✅ **已实现** |

C 路线与 task-email-import「零凭证粘贴版」哲学完全同构：用户分享时系统给出
「复制链接/文案」，把 caption（或 文案+链接）粘贴进来即可。没有视频理解能力
的情况下，caption 是地点清单的最高置信文本载体（Feedtrip 也读 caption）。

## 实现（最小版，backend）

- `app/services/social_import.py`（纯函数、零外部依赖、确定性）：
  - `parse_social(text)` → `SocialImportResult`
  - URL 只识别平台（tiktok/instagram/xiaohongshu/douyin/weibo/bilibili）、
    剥除文本、绝不抓取（反爬墙绕过）；
  - 子句级规则：街道/寺庙/公园/博物馆/餐厅/咖啡/民宿/酒店 等 40+ 地名收尾词
    + 顿号/逗号/冒号列举拆分 + 标签（#杭州美食）剥离 + emoji/语气词噪声剥离
    （谁懂啊/绝了/yyds/家人们/狠狠/冲/码住/避雷…）+ 价格语剥离（人均¥200）+
    方位前缀剥离（西湖边的山外山菜馆 → 山外山菜馆）；
  - 类型推断 food/hotel/attraction（复用 note_import 特征）；
  - 敌意输入：复用 note_import `_INJECTION_RE`，指令型子句标记剥离，
    绝不把文本当指令执行；
  - 候选复用 `NoteStopCandidate`（可勾选并入行程，前端复用现有
    POST /days/{day_id}/stops）。
- `app/schemas/social_import.py`：请求/响应 Pydantic（text ≤ 20k）。
- `app/api/v1/social_import.py`：POST /trips/social/import（登录必需，
  超长 422）。
- `tests/test_social_import.py`：12 用例（TikTok/IG/小红书/抖音 caption、
  单行顿号列举、链接净化、类型推断、价格提取、去重、无地点不误报、
  链接收藏兜底、敌意输入两类、API 鉴权/流程/超长）。

## 验收对照

- [x] 粘贴分享文本（caption+链接）→ 规则提取地点候选
- [x] 不抓 URL 不碰反爬（只处理粘贴文本）
- [x] 恶意注入文本按敌意输入处理（flagged_lines 剥离，不进候选）
- [x] 候选复用 note-import 结构可勾选并入行程
- [x] 可行则最小版 + 测试（12 例专项，全套 471+ 测试通过）
- [x] API 层 POST /api/v1/trips/social/import（登录必需，超长 422）

## 降级兜底（保留）

纯链接粘贴（无 caption 文本）→ 走既有 link_import 链接收藏（extracted=false），
本功能不新增抓取路径，不回退已可用能力。

## 差距 → 后续行动项（未列入本夜，供用户评估）

1. **caption 复制引导**（前端）：分享弹窗/粘贴框提示「把文案一起复制进来」，
   社交 Tab 入口（复用 ImportDialog 四通道模式）——需并入
   nightly/2026-10-06/2-task-import-ui-wiring 未合分支一并处理。
2. **视频内容理解**（Feedtrip 差异核心）：OCR 字幕/画面文字 → 地点，
   需要多模态能力，超出零凭证范围，暂缓。
3. **地图打点**（Feedtrip 钉地图）：候选勾选后已有 stops 地图，无需新做。