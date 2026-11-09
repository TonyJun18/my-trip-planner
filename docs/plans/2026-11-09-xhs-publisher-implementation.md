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

## 6. 首次真机校准（唯一未完成项）

选择器集中在 `playwright_creator.py` 的 `SELECTORS`（多候选 + 文本兜底），
`SELECTOR_SET_VERSION="2026-11-09.unverified"` 明确标注未校准。

校准步骤：

1. `XHS_RPA_HEADLESS=false` 起后端，前端点「发布到小红书」；
2. 若 job 变 `failed/selector_miss`，看 `backend/var/xhs-screenshots/` 最新截图；
3. 用开发者工具确认新的选择器，补进 `SELECTORS` 对应候选**列表头部**；
4. 改 `SELECTOR_SET_VERSION` 为当天日期 + `calibrated`；
5. 重跑 `pytest tests/test_xhs_publishers.py`（选择器不影响单测，只影响真机）。

失败排查顺序（与 `xiaohongshu-mcp` 的 Q&A 一致）：截图 → 是否被风控限制网页端发布 → 图片大小/命名（必须 ASCII）→ 登录态 → 页面改版。

### 已实测确认（2026-11-09，headless Chromium 真机）

| 观察 | 结论 |
|---|---|
| 未登录访问 `creator.xiaohongshu.com/publish/publish?source=official` | 302 到 `/login?source=official&redirectReason=401&lastUrl=...` → `is_logged_in()` 走 URL 判定即可靠 |
| 登录页形态 | 「短信登录」：手机号 + 验证码 + 登录按钮；卡片右上角有二维码图标可切换扫码 |
| 驱动 → 策略 → 服务 链路 | `RpaPublisher` 真实调用 → `PublishError(login_required)`，**未登录不会假装填表成功** |
| 截图 | 首屏是 SPA，只等 `domcontentloaded` 会截到白屏 → 已改为等 `networkidle`（超时忽略） |
| 发布页表单选择器 | **仍需登录后校准**（当前 `SELECTOR_SET_VERSION=2026-11-09.login-calibrated:publish-unverified`） |

登录页截图留证：`backend/var/xhs-screenshots/`（gitignore）。

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
| 后端全量测试 | `872 passed`（含新增 40 个小红书用例） |
| ruff（本次改动文件） | All checks passed |
| 前端 `npm run build` | ✓ built |
| i18n 自检 | 1058 keys × 2 语言，无缺失/重复 |
| 真实浏览器链路 | 驱动启动/登录态判定/截图 已真机验证；`RpaPublisher` 真实调用得到 `login_required`；发布页表单选择器待登录后校准（默认 manual，不影响线上） |
