# 小红书发布通道（方案 C）实施说明

- 日期：2026-11-09
- 前置调研：`docs/plans/2026-11-09-xhs-direct-publish-research.md`（官方三入口实测、五条路线对比、风险清单）
- 状态：**代码 + 单测/接口测试全绿**；真实浏览器链路需按 §6 校准选择器（默认走 manual，不会影响线上）

---

## 1. 三种设计模式怎么落的

| 模式 | 落点 | 作用 |
|---|---|---|
| **策略** | `BasePublisher` 的每个子类：`ManualPublisher` / `RpaPublisher` / 未来 `OpenApiPublisher` | 通道可互换，调用方只依赖契约 |
| **模板方法** | `BasePublisher.publish_note()` 固定编排：`_validate → _prepare → _deliver_assets → _check_ready → _submit → _finalize` | 所有通道共用同一套校验/日志/失败口径；子类只填钩子（`_submit` 是唯一抽象方法） |
| **工厂** | `publishers/registry.py`：`PublisherFactory` + `@register_publisher("xxx")` | 按 `XHS_PUBLISH_MODE` 或请求参数返回策略；新增通道不改业务代码 |

为什么这样切：

- **换通道零成本**——官方 `write_notes` 放量后，只需新增 `XhsOpenApiPublisher` 并注册一行；`trips_crud.py` 与前端完全不动。
- **换驱动零成本**——`PublishDriver` 协议把「怎么落到界面」抽出来：Playwright 启动 / CDP 接管 / 未来 HTTP API 都只是驱动实现。
- **可测**——`FakeDriver` 让整条编排在无浏览器、无网络的情况下真实跑一遍（这正是 40 个测试的基础）。

---

## 2. 文件地图

```
backend/app/services/
├── publishers/
│   ├── base.py                  # 契约 + 模板方法（XhsNote / PublishResult / PublishError）
│   ├── manual.py                # 策略：手动（默认）
│   ├── rpa.py                   # 策略：自动化填表（半自动为主）
│   ├── registry.py              # 工厂 + 注册表（+ 未知 mode 回落 manual）
│   └── drivers/
│       ├── protocol.py          # PublishDriver 协议 / PublishForm / DriverOutcome
│       ├── fake.py              # 假驱动（测试 + 演练）
│       └── playwright_creator.py# 真驱动（多候选选择器 + 失败截图）
├── xhs_assets.py                # 封面图落盘（magic bytes / 大小 / 归属校验）
├── xhs_publish_service.py       # 异步 job + 状态机 + 单浏览器串行
└── xhs_service.py               # 文案生成（原有）+ 旧符号再导出（兼容）
backend/scripts/xhs_login.py     # 扫码登录一次，保存 storage_state
backend/tests/test_xhs_publishers.py    # 27 个：策略/工厂/模板方法/校验/资产安全
backend/tests/test_xhs_publish_api.py   # 13 个：HTTP → 任务 → 策略 → 驱动 → 状态回写
frontend/src/components/XhsNoteDialog.vue  # 「发布到小红书」按钮 + 状态轮询
frontend/src/utils/export.js               # renderToDataUrl（canvas → PNG dataURL）
```

---

## 3. API 契约

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/v1/trips/{id}/xhs-assets` | body `{data_url}` → `{asset_id, width, height, bytes, url}`（只收 png/jpeg/webp，magic bytes 校验，默认 ≤8MB） |
| GET | `/api/v1/trips/{id}/xhs-assets/{asset_id}` | 读取图片（owner only；asset_id 含行程前缀，阻断跨行程与目录穿越） |
| GET | `/api/v1/trips/{id}/xhs-channels` | `{mode, connected, requires_images, supports_auto_submit, hint, available_modes, driver}` |
| POST | `/api/v1/trips/{id}/xhs-publish` | body `{title, body, topics[], asset_ids[], mode?, auto_submit?}` → **202** + job（同步阶段只做快速失败 400） |
| GET | `/api/v1/trips/{id}/xhs-publish/{job_id}` | 任务状态 |

**状态机（诚实口径）**

```
queued → running → ready      半自动：表单已填好，等人点发布（不宣称已发布）
                 → published  自动：点了发布且读到回执
                 → unknown    点了发布但没读到回执（不编造链接）
                 → failed     校验/登录/页面结构失败（带稳定 reason）
                 → manual     手动通道（服务端不投递）
```

`reason` 码：`login_required` / `driver_not_ready` / `no_images` / `asset_missing` / `asset_path_not_ascii` / `title_too_long` / `body_too_long` / `submit_failed` / `selector_miss` / `auto_submit_unsupported` / `internal_error`。前端按码给不同引导（见 `xhsNote.publishReason*` i18n）。

---

## 4. 配置与开关

```bash
# 默认手动：复制文案（零依赖、零风控），上线不影响任何现有行为
XHS_PUBLISH_MODE=manual

# 切换到自动填表（半自动：填好等你点发布）
XHS_PUBLISH_MODE=rpa
XHS_RPA_HEADLESS=false          # 半自动必须 false
XHS_RPA_KEEP_OPEN=true          # 填完保留窗口
XHS_RPA_TIMEOUT=60

# 登录态两种来源（优先 CDP 接管，免扫码）
XHS_RPA_CDP_URL=http://127.0.0.1:9333
XHS_RPA_STATE_PATH=backend/var/xhs-state.json

# 资产
XHS_ASSET_DIR=backend/var/xhs-assets
XHS_ASSET_MAX_BYTES=8388608
```

安装依赖（只有 rpa 通道需要）：

```bash
uv pip install --python .venv/bin/python --group publish
.venv/bin/python -m playwright install chromium
```

---

## 5. 两条上线路径

### A. 复用已有登录态（推荐，免扫码）

按 `chrome-cdp-automation` 技能克隆 profile 起一个带调试端口的 Chrome，登录一次创作平台，然后：

```bash
XHS_RPA_CDP_URL=http://127.0.0.1:9333 XHS_PUBLISH_MODE=rpa \
  .venv/bin/python -m uvicorn app.main:app --port 8090
```

### B. Playwright 自持登录态

```bash
cd backend
.venv/bin/python scripts/xhs_login.py          # 弹窗 → 扫码 → 自动保存 var/xhs-state.json
.venv/bin/python scripts/xhs_login.py --check  # 只看登录态
```

> ⚠️ 同一小红书账号不允许同时存在多个网页端会话，发布时可能挤掉你在浏览器里登的创作平台。扫码/登录交给人，脚本不代输任何凭据。

---

## 6. 选择器校准（2026-11-09 真机完成）

选择器集中在 `playwright_creator.py` 的 `SELECTORS`，`SELECTOR_SET_VERSION="2026-11-09.calibrated(publish-click-unverified)"`。
校准工具：`backend/scripts/xhs_calibrate.py`（dump 结构 + 试命中 + 可选填表验证）。

### 实测得到的关键事实

| 环节 | 真机结论 |
|---|---|
| 未登录访问发布页 | 302 → `/login?source=official&redirectReason=401`（URL 判定可靠） |
| 登录页 | 「短信登录」（手机号 + 验证码），卡片右上角可切二维码 |
| 登录态判定 | **必须看 `web_session` cookie**：登录后停在首页，首页既无标题框也无发布按钮，只看元素会误判未登录（已踩） |
| 发布页默认 tab | **「上传视频」**；图文 tab 容器 = `div.creator-tab`，同名 `<span class="title">` 是视口外副本（点它会超时→已内置遍历可见项点击） |
| 图片上传 | `input[type=file][accept*='png']`（accept=`.jpg,.jpeg,.png,.webp`）；file input 是隐藏元素，**不能用 is_visible 过滤** |
| 标题 | `input[placeholder*='标题']`（实际 placeholder：填写标题会有更多赞哦） |
| 正文 | `div.tiptap.ProseMirror`（**不再是 quill `.ql-editor`**） |
| 底部动作栏 | `<xhs-publish-btn>` 自定义元素，**closed shadow root**：CSS/文本选择器都穿不进去（`button:has-text('发布')` 命中 0、`text=发布` 只能匹配到「发布笔记/定时发布」）。但暴露属性 `submit-text="发布"` / `submit-disabled` / `save-text="暂存离开"` |
| 点发布 | 用属性判可用性 + 在栏宽 ~61% 处做**真实鼠标坐标点击**（真实点击能命中 shadow 内部节点）。**此步未真机验证**——不会为了验证而往你的账号发测试笔记 |
| 正文写入方式 | **必须一次性 `editor.fill(正文 + 话题)`**：先 `insert_text(body)` 再 Enter + `insert_text(topics)` 会与 ProseMirror 渲染竞态，出现「正文尾部被挤到话题之后」的错位（实测过） |
| 话题输入 | 输入 `#话题` 会弹联想浮层盖住页面 → `Esc` 关闭（文本保留）；否则半自动留下的现场被浮层遮住 |
| 引导气泡 | 上传图片后弹「图片可以编辑啦/我知道了」，会盖住编辑区 → `_dismiss_overlays()` 在上传后与填完后各扫一次 |

### 复校步骤（平台改版时）

```bash
cd backend
.venv/bin/python scripts/xhs_calibrate.py --state var/xhs-state.json --headless --tab image --fill /tmp/cover.png
```

看输出里 `selector_probe` 的命中数：哪一组变 0 就改哪一组；截图在 `backend/var/xhs-screenshots/`。
改完把 `SELECTOR_SET_VERSION` 更新成当天日期。

失败排查顺序（与 `xiaohongshu-mcp` 的 Q&A 一致）：截图 → 是否被风控限制网页端发布 → 图片大小/命名（必须 ASCII）→ 登录态 → 页面改版。

---

## 7. 明确不做的事

- **不为多租户托管用户 cookie**：cookie 等价账号控制权，泄露=账号被盗。当前只支持"本机/单账号"模式。
- **不默认全自动点发布**：`auto_submit` 默认 false；即使打开，读不到回执只报 `unknown`。
- **不伪造成功**：`ready` 不等于 `published`，无回执不给 `note_url`。
- **不代输密码/验证码**：登录一律由人扫码。

---

## 8. 验证记录（2026-11-09）

| 项 | 结果 |
|---|---|
| 后端全量测试 | `872 passed`（含新增 44 个小红书用例） |
| ruff（本次改动文件） | All checks passed |
| 前端 `npm run build` | ✓ built |
| i18n 自检 | 1058 keys × 2 语言，无缺失/重复 |
| 真实浏览器链路 | **已真机全流程验证**：未登录 → `login_required`；扫码登录后 `RpaPublisher` 真实填表 → `state=ready`（标题/正文/话题/图片全部正确落地，未点发布）；截图留证 |
| 未验证项 | `auto_submit=true` 的「点发布」——代码已按 closed shadow 属性 + 坐标点击实现，但不为验证而真发测试笔记到账号；首次真实自动发布会得 `published` 或诚实的 `unknown` |

---

## 9. 服务端部署与多用户（重要）

### 9.1 目录与配置（不在代码里写死路径）

所有可写目录统一由 `publishers/paths.py` 解析，**禁止**在业务代码里拼
`Path(__file__).parents[...]`——那等于把开发机的目录布局写死进项目。

| 环境变量 | 默认 | 说明 |
|---|---|---|
| `XHS_DATA_DIR` | `var/xhs`（相对 backend/） | 数据根；容器里设 `/data/xhs` 并挂卷 |
| `XHS_ASSET_DIR` | `{DATA_DIR}/assets` | 发布图片 |
| `XHS_SCREENSHOT_DIR` | `{DATA_DIR}/screenshots` | 现场截图（失败取证） |
| `XHS_STATE_DIR` | `{DATA_DIR}/states` | 单机登录态目录（多用户不用它） |
| `XHS_MAX_CONCURRENT_SESSIONS` | `1` | 同时打开的浏览器数，每个约 300–500MB |
| `XHS_ALLOW_SEMI_AUTO_HEADLESS` | `false` | 无头环境是否允许"填好等人点发布" |

docker-compose 片段（示意）：

```yaml
backend:
  environment:
    XHS_DATA_DIR: /data/xhs
    XHS_MAX_CONCURRENT_SESSIONS: "2"
  volumes:
    - xhs_data:/data/xhs
```

### 9.2 无头环境下的硬约束

服务器上没有窗口给人点「发布」，所以：

- 半自动（`auto_submit=false`）在无头环境会**明确失败**：
  `reason=semi_auto_requires_visible_browser`（不会假装 ready）；
- 服务端部署必须用 `auto_submit=true`，或者把浏览器画面投给用户
  （noVNC 之类，同时设 `XHS_ALLOW_SEMI_AUTO_HEADLESS=true`）；
- 或者改走"发布在用户自己的浏览器里完成"的本地发布器（见 9.3 方案 B）。

### 9.3 前台用户场景：两种架构（**需要选型后再实现**）

当前代码的登录态入口已经拆开（驱动支持 `storage_state` 直接传 dict、并发按用户串行、
`XHS_MAX_CONCURRENT_SESSIONS` 限流），但**多用户绑定/授权还没有实现**。

| | A. 服务端代发（每用户扫码绑定） | B. 本地发布器 / 浏览器扩展 |
|---|---|---|
| 用户操作 | 扫码绑定一次，之后「点一下就发」 | 装扩展/助手，在浏览器里完成发布 |
| 凭证在谁手里 | **服务器加密持有用户 cookie** | 只在用户浏览器，服务器零凭证 |
| 服务器成本 | 每并发一个 headless Chromium（300–500MB） | 几乎为零 |
| 合规与风控 | 代持账号凭证 + 自动化发布，风险最高；必须加密、可解绑、限频、明示 | 风险最低，等同于用户自己操作 |
| 移动端用户 | 可用（服务端跑） | 不可用（需桌面浏览器） |
| 工程量 | 中（绑定表 + 加密 + 二维码登录 + 状态机 + 轮换） | 中（扩展开发 + 分发 + 与平台任务对接） |

**A 的关键实现要点**（若选 A）：

1. 表 `xhs_bindings`：`user_id` 唯一、`state_ciphertext`、`status`、`bound_at`、`last_used_at`、`last_error`；
2. 二维码登录：`POST /xhs/bindings/login-session` → 返回二维码 PNG（base64）+ session id，
   `GET .../{id}` 轮询；用户在**自己手机**上扫码，服务端 `export_state()` 后加密入库；
3. 加密：Fernet（key 走 KMS/env `XHS_COOKIE_KEY`），**绝不明文落库/落盘**，日志与响应里不出现 cookie；
4. 解绑：`DELETE /xhs/bindings` 删除密文 + 失效会话；过期/被踢自动置 `expired` 并要求重绑；
5. 发布时：按 `user_id` 取密文解密 → `PlaywrightCreatorDriver(storage_state=state)` → 发布 → 更新 `last_used_at`；
6. 频控：单用户串行（已实现）+ 每日上限；异常时降级到 manual 通道。

> 提醒：A 方案代持用户账号凭证，属于高敏感数据处理，上线前需要法务看平台协议与个人信息保护口径。
