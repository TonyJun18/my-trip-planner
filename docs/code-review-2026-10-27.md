# my-trip-planner 代码质检报告（2026-10-27）

> 审查基准：工作区 = main HEAD `507978e` + 进行中 merge（`nightly/2026-10-24/2-task-social-collection-eval`，HEAD `4c6961b`）
> 事实来源：代码取证 + 实际跑测（main HEAD **475 passed, 1 skipped** 80s；social 分支 **13 passed** 专项）+ git 冲突状态核验
> 本文档结论均基于仓库实际代码与测试结果，非记忆推断。

---

## 一、结论摘要

**代码质量：✅ 高**——鉴权、注入防护、确定性计算、测试卫生在这个规模（~25K LOC）下均属上乘；上一轮项目复盘（10-21）指出的问题**几乎全部根治**，且修复方式是改根因而非打补丁。

**当前状态：⚠️ 仓库不可运行**——merge 中的 3 个冲突文件未解决，其中 `backend/app/api/v1/__init__.py` 残留冲突标记 → Python 语法错误 → 后端无法导入/启动/跑测试。这是唯一需要立即处理的阻塞项（解决方式为纯并集，无对抗）。

| 维度 | 结果 |
|---|---|
| 测试基线（main HEAD） | 475 passed, 1 skipped（80.35s） |
| 测试基线（social 分支专项） | 13 passed（1.79s） |
| 阻塞项（🔴） | 2（merge 冲突代码 + 冲突文档） |
| 建议项（🟡） | 2（social 前端未接线、.env 端口不匹配） |
| 上次复盘问题复检 | 9/9 确认已修复 |

---

## 二、🔴 阻塞项

### B1. Merge 冲突未解决，后端无法启动
**位置**：`backend/app/api/v1/__init__.py:6-10, 27-31`（冲突标记残留）

```python
<<<<<<< HEAD
from app.api.v1 import auth, ..., expenses, export, ..., trips, ws
=======
from app.api.v1 import auth, ..., social_import, ..., trips, ws
>>>>>>> nightly/2026-10-24/2-task-social-collection-eval
```

**根因**：HEAD（main）已含 expenses/export 两个新路由器；social 分支基于旧 main，也改了同一文件。`<<<<<<<` 是 Python 语法错误 → 任何 `import app.api.v1` 直接崩溃（实测 `SyntaxError: invalid syntax`）。

**为什么测试没抓到**：测试先 import 应用；冲突状态下 pytest 在收集阶段即 100% error。「475 绿」是 main HEAD 与 social 分支**各自**的状态，当前工作区是红的。

**解决（纯并集，双方路由都保留）**：
```python
from app.api.v1 import auth, email_import, expenses, export, health, inspiration, link_import, map_edit, note_import, plan_b, planner, profile, screenshot_import, social_import, trips, ws
...
api_router.include_router(export.router, prefix="/trips", tags=["trips"])
api_router.include_router(expenses.router, prefix="/trips", tags=["trips"])
api_router.include_router(social_import.router, tags=["trips"])
```
social 分支不含 expenses/export 后端文件（已 `git ls-tree` 核实），不会重复注册。

### B2. 文档冲突需按同一原则解决
- `docs/night-build-todo.md:65-69`：`task-social-collection-eval` HEAD 侧 `[ ]`（未完成）、social 侧 `[x]`（完成+登记）→ **取 `[x]` + 完整登记**。
- `docs/nightly/checkpoint.json:12-39`：HEAD completed=2/current_index=2，social 侧 completed=3/current_index=3 → 取并集 completed=3、current_index=3、branches 三分支全列。

---

## 三、🟡 建议项

### S1. social_import 前端未接线（功能对用户不可见）
**位置**：`frontend/src/api/index.js:214-226`（四通道封装无 social）；`frontend/src/components/ImportDialog.vue`（四 Tab：note/screenshot/email/link，无社交 Tab）

后端 `POST /trips/social/import` 已实现（13 例测试全绿）且设计优秀（纯规则零 LLM、URL 只识别不抓取、敌意输入剥离、登录必需、超长 422），但：
- `api/index.js` 无 `importSocial` 封装
- ImportDialog 仍是「四通道」，无「社交粘贴」第五通道
- i18n 无对应键

**影响**：功能入口只存在于 API 层，与 10-14 主线「四通道闭环」相比，社交通道是「后端完成、用户摸不到」的半个功能。建议补前端入口（api 封装 + Tab + i18n）或明确记为待办。

### S2. 本地开发环境端口不匹配
**位置**：`backend/.env` 的 `DATABASE_URL` 指向 `127.0.0.1:5432`，本机 5432 无监听；docker db（`docker-compose.yml:23`）暴露在 **5433**。

**影响**：本地直启后端连不上库；本次测试靠显式覆盖 `DATABASE_URL=...:5433` 才跑通。建议 `.env` 端口对齐 5433，或启动脚本显式覆盖。

---

## 四、✅ 上次复盘问题复检（9/9 修复）

| 10-21 复盘问题 | 本次核验位置 | 状态 |
|---|---|---|
| `delete_day`/`delete_stop` 缺 owner 校验（IDOR） | `trip_service.py:247-259` 已改用 `_load_day_for_owner` | ✅ 修复 |
| TripMap.vue popup HTML 注入（stored XSS） | `TripMap.vue:56-102` 全部 `createElement` + `textContent` | ✅ 修复 |
| PlanWizard `toISOString().slice(0,10)` UTC 时区 bug | `PlanWizard.vue:180-194` 本地日期格式化 | ✅ 修复 |
| Nominatim 限速只在失败路径 | `tools.py:167-168` 成功路径 `sleep(1.1)` + `Semaphore(1)` | ✅ 修复 |
| StopIn lat/lng 无范围校验 | `plan.py:22-23` `ge=-90/le=90`、`ge=-180/le=180` | ✅ 修复 |
| health 依赖注入故障 500 | `health.py` 独立连接 + 3s 超时 + 返回 degraded | ✅ 修复 |
| 注册并发 IntegrityError 500 | `auth_service.py:82` catch IntegrityError | ✅ 修复 |
| `ENABLE_PROVIDER_FALLBACK` 未接线 | `providers.py:242-299` 惰性兜底链真实生效 | ✅ 修复 |
| `TASK_STALE_RUNNING_SECONDS` 等死配置 | `planning_service.py:150-156,209-212` 恢复扫描/超时实际使用 | ✅ 修复 |
| google_auth 返回类型 tuple→str 导致 aud 取首字符 | `google_auth.py:33` `-> str` | ✅ 修复 |

---

## 五、✅ 值得肯定的设计（本轮新功能的质检结论）

- **social_import.py**：纯规则、零 LLM、零外部依赖；「外部内容当敌意源」落实彻底（`_INJECTION_RE` 复用 + flagged_lines 剥离 + Pydantic 强校验 + 登录必需 + 20k 上限）
- **expense_service.py**：append-only 记账（金额不可原地改）、payer 空串计入 total 不参与分摊、travelers<1 防除零、四舍五入到分——诚实口径
- **export_service.py**：owner/share 双路径共用构建函数、零令牌零凭证输出、schema_version 语义化
- **share_lifecycle.py**：旧数据零迁移兼容 + 过期 410 / 吊销 403 / last_used 审计尽力而为不阻断
- **collab_service.py**：匿名投票 key 哈希化（不暴露 IP/UA）、跨行程投票校验、共识阈值不假设全员响应
- 测试卫生：FakeLLM 零 token、session 级测试库隔离、475+ 测试 80s 跑完

---

## 六、修复优先级

| 优先级 | 项 | 工作量 | 影响 |
|---|---|---|---|
| 🔴 立即 | 解决 3 个冲突文件（并集合并） | ~10 分钟 | 后端无法启动、全仓库红 |
| 🔴 立即 | 合并后跑 pytest 验证 ≥488 绿 | 2 分钟 | 确认无回归 |
| 🟡 下次 | 前端 social 入口接线 | 0.5-1 天 | 功能对用户可见 |
| 🟡 近期 | `.env` DATABASE_URL 端口对齐 5433 | 1 分钟 | 本地启动顺畅 |

---

## 七、健康度结论

- **工程化程度**：极高（475 测试全绿、鉴权分层完整、容错完备、诚实标注体系）——远超普通 demo 水平，且修复记录显示「发现问题 → 根治 → 测试覆盖」的闭环真实运转
- **当前最大风险**：不是代码缺陷，而是**进行中的 merge 停在半路**——冲突是并集型（双方都新增了独立功能），解决它即可恢复全绿
- **资产沉淀**：本次质检报告本身纳入 `docs/`，与 10-21 复盘构成连续的质量基线记录