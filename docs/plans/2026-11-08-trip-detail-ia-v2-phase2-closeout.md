# 详情页 IA/Tab 阶段二收口方案（待评审，本轮不动代码）

**Date**: 2026-11-08  **Author**: Hermes（基于代码实证）
**依据**: `docs/prd/2026-10-29-trip-detail-refactor-spec.md` v0.2 §4/§6 · `docs/plans/2026-10-29-trip-detail-ia-v2-implementation.md`（下称「实施记录」）
**状态**: 方案 v1，待拍板 §8 三个问题后开工

---

## 0. 一句话结论

阶段二的**主路径/收纳/时机换血早已落地并真机验证**（commit `1326efe`，实施记录 §6 有截图证据），
`docs/nightly/checkpoint.json` 里「阶段二未做待 review」是**文档债，不是功能债**。
真正剩下的是四件事：**回滚口只到浏览器级**、**收纳层没有埋点**、**两处时机空白（finished / prep 发现性）**、**登记收口**。
建议按 A→D 四块，两晚完成；每块独立 commit、可单独 revert。

---

## 1. 现状核对（代码实证，避免重复设计）

| 能力 | 位置 | 状态 |
|---|---|---|
| 时机四态 planning/prep/live/finished | `frontend/src/utils/tripPhase.js:59` | ✅ prep 锚点 = 首个 hotel 站所在日 −48h（PRD §4 同源） |
| 面板白名单收纳 + `flat` 嵌卡 | `components/trip-detail/TripDetailToolbox.vue:52-57,69-76` | ✅ |
| 时机 tab + 徽标（问题数 / 预订 / 进度） | `views/TripDetailView.vue:196-226`、`TripDetailWorkspace.vue` | ✅ 实现，但见 §2-1 |
| 「全部工具」开关 + 导出自动全开 | `TripDetailView.vue:223-226,942` | ✅ |
| 规划工具（AI 修订 / 备选）提升到主路径 | `TripDetailPlanTools.vue` + `hoistedPlanKeys:236-238` + `planToolsVisible:236` | ✅ 常驻（任何时机），仅导出态卸载 |
| 逐日默认折叠（行中只开当天） | `TripDetailView.vue:257-304` | ✅ |
| Feature flag | `utils/flags.js`（URL → localStorage → 默认，默认 `true`） | ⚠️ 只到浏览器级，见 §2-3 |
| 意图埋点 4 事件 | `api/modules/analytics.js` + `backend/app/api/v1/analytics.py`（白名单、不落库、204） | ✅ 但无收纳层信号，见 §2-4 |
| checkpoint 登记 | `docs/nightly/checkpoint.json` → issues | ❌ 仍写「未做待 review」 |

> 开工前 5 分钟核对：`git log --oneline -3`、`grep -n "iaV2" frontend/src/views/TripDetailView.vue`、`cat docs/nightly/checkpoint.json | head -5`。若与上表不符，先更新本表再动手。

---

## 2. 真问题清单（7 条）

| # | 问题 | 证据 | 处置 |
|---|---|---|---|
| 1 | Tab 条在多数时机退化为「带标题的容器头」（每时机只 1 个 tab，`tabs.length > 1` 分支不成立） | `phaseTabs` 三个分支均为单元素；`TripDetailWorkspace.vue:35` | **接受**（收纳价值来自收纳，不来自切换）+ finished 补独立 tab（C1） |
| 2 | **flag off 时 tab 条仍可能出现，且点了不生效**：`wsTabs` 未判 `iaV2`，而 `wsKeys` 在 `!iaV2` 时返回 `null`（渲染全部面板） | `TripDetailView.vue:214-226` | **修**（A3，对照组一致性） |
| 3 | 回滚口只有客户端三级来源（URL / localStorage / 代码默认），全站回滚 = 改代码重新发布 | `utils/flags.js` | **修**（A1 分级 + A2 服务端 kill switch） |
| 4 | 收纳层无埋点：无法区分「没进工具区」与「进了但 tab 迷路 / 频繁逃到全部工具」 | analytics 白名单只有 4 个事件 | **修**（B） |
| 5 | finished 复用 live 分支，行程结束后 tab 标签仍叫「行中」 | `TripDetailView.vue:201-203` | **修**（C1） |
| 6 | prep 时机看不到质检 / 时间校验，需「更多 → 调整行程」两跳才到规划工具 | `WS_PREP_KEYS` 不含 `timegate`/`quality` | **修**（C2） |
| 7 | PRD §4 的 4 条实现期偏差（酒店双时机 / 非规划时机可改行程 / 未做 sticky / 折叠键升级）只在实施记录里，PRD 未回写 | 实施记录 §3 | **修**（D，文档债） |

---

## 3. 方案

### 3.0 目标结构

```
flag 解析优先级：URL ?flag= > localStorage > 服务端 GET /api/v1/flags > 内置默认
  └─ tripDetail.ia.v2                 总闸（关 = 完整 v1 三段式平铺）
       ├─ tripDetail.ia.v2.tabs       时机 tab 收纳（关 = 12 面板平铺，仍保留导出全开）
       ├─ tripDetail.ia.v2.hoist      AI 修订 / 备选 提升到主路径（关 = 回工具箱）
       └─ tripDetail.ia.v2.collapseDays 逐日默认折叠（关 = 全展开）
```

依赖规则：三个子开关**仅在总闸开启时生效**（避免「总闸关 + 子开关开」的半开状态产生第四种版面，无法验收）。

---

### 3.1 块 A：回滚口硬化（约 2.5h）

**A1 前端 flag 分级 + 响应式**

- `frontend/src/utils/flags.js`：内部状态改为 `reactive` 对象，新增 `useFlag(key)` 返回 `computed`；
  保留 `isFlagOn` / `setFlag` / `clearFlag` 作为同步兼容层（现有调用点只有一处，改造面很小）。
- `DEFAULTS` 增至 4 个 key；子 key 读取时若总闸为 false 直接返回 false（依赖规则）。
- `TripDetailView.vue:172`：`const iaV2 = useFlag('tripDetail.ia.v2')`，
  并把 `planToolsVisible` / `hoistedPlanKeys` / `wsKeys` 各自挂到对应子开关。
- 为什么必须响应式：服务端 kill switch 是**运行中到达**的，非响应式 `ref(isFlagOn(...))` 只在 setup 读一次，等于没有 kill switch。

```js
// 骨架（flags.js）
const state = reactive({ ...DEFAULTS })
export function useFlag(key) {
  return computed(() => (isChild(key) && state['tripDetail.ia.v2'] === false ? false : state[key] !== false))
}
export async function primeFlags() {
  const remote = await fetch(`${API_BASE}/flags`).then((r) => r.json()).catch(() => null)
  if (remote?.flags) Object.assign(state, remote.flags) // 失败静默，保留本地/默认值
}
```

**A2 服务端 kill switch（运维不用重新发布前端）**

- 新增 `backend/app/api/v1/flags.py`：`GET /flags` → `{"flags": {...}, "revision": "..."}`，
  `Cache-Control: public, max-age=60`；无鉴权（只回布尔，无敏感面）。
- `backend/app/common/config.py` 增 `FEATURE_FLAGS_JSON: str = "{}"`；
  `app/services/feature_flags.py` 解析（JSON 失败 → `{}` + `logger.warning`，**绝不阻断启动**——项目降级哲学 §4）。
- 注册：`app/api/v1/__init__.py` 加 `flags` 的 import 与 `include_router(..., prefix="/flags")`。
- 前端 `App.vue` `onMounted` 调一次 `primeFlags()`（`api/http.js` 之外用裸 fetch，同 analytics 的理由：不能触发 401 跳登录）。
- 回滚动作 = 改 env + 重启后端（约 30s）→ 前端 60s 缓存内自愈。
- **明确不做**：百分比灰度（20% → 100%）。理由：当前真实流量不足以形成统计显著，`percent` 字段只会制造「以为灰了其实没灰」的假象；G1 对照组改用设计伙伴 `?flag=` 抽样 + 前后时段对比，并在 PRD §6 写明这个降级决定。

**A3 对照组一致性修复**

- `wsTabs` 计算开头加 `if (!iaV2.value) return []`；`TripDetailWorkspace` 收到空 tabs 时只渲染「全部工具」头（不渲染 tab 条）。
- `openPlanTool()` 在 `!iaV2` 时滚到工具箱顶（不要设置一个不存在的 `wsTab`）。

**任务拆分**

| 步骤 | 文件 | 验证 |
|---|---|---|
| A1-1 写 `test_feature_flags.py`（3 例：空 env / 合法 JSON / 非法 JSON 降级） | `backend/tests/test_feature_flags.py` | `pytest tests/test_feature_flags.py -q` |
| A1-2 实现 `feature_flags.py` + `config.FEATURE_FLAGS_JSON` | `app/services/feature_flags.py`, `app/common/config.py` | 同上转绿 |
| A1-3 写 `test_flags_api.py`（GET 返回、Cache-Control） | `backend/tests/test_flags_api.py` | `pytest tests/test_flags_api.py -q` |
| A1-4 实现 `api/v1/flags.py` + 注册 | `app/api/v1/flags.py`, `app/api/v1/__init__.py` | `curl localhost:8090/api/v1/flags` |
| A1-5 flags.js 响应式化 + 分级 | `frontend/src/utils/flags.js` | `npm run build` |
| A1-6 TripDetailView 挂子开关 | `views/TripDetailView.vue` | 手测 4 组合 |
| A1-7 App.vue primeFlags | `App.vue` | 改 env 后无痕刷新验证 |
| A3-1 对照组一致性 | `TripDetailView.vue`, `TripDetailWorkspace.vue` | flag off 下点「更多→调整行程」无死 tab |

---

### 3.2 块 B：收纳层埋点（约 1.5h）

新增 2 个事件（**只加 2 个**，其余交给 TripEvent 事实流）：

| 事件 | 触发 | 专有载荷 |
|---|---|---|
| `workspace_tab_switch` | 点击工作台 tab | `tab`（plan/prep/live/review）、`from`（切换前 tab，首次为空） |
| `workspace_all_toggle` | 点击「全部工具」 | `on`: bool |

**为什么是这两个**：G1「工具因收纳而流失」只有两种失败形态 —— ①根本没进工具区；②进了但 tab 里迷路（表现为反复切换却不开面板）或频繁逃到「全部工具」。`from→to` 分布与 `all_toggle` 频次正好是这两形态的直接代理指标，而面板点击已有 `planning_tool_open` 覆盖（含分母：`workspace_tab_switch` 总量）。

- 后端：`app/schemas/analytics.py` 扩展 `AnalyticsEventName` Literal + `TabName = Literal["plan","prep","live","review"]`；
  `api/v1/analytics.py` 的 `_EVENT_LABELS` 与 log 行补 `tab` / `from_tab` / `on`。
- 前端：`TripDetailWorkspace.vue` 在 `select()` 里 `emit('tab-switch', { tab, from })`；
  `TripDetailView.vue` 的 `onWsTabChange` / `toggleWsAll` 里 `trackEvent(...)`。
- 测试：`backend/tests/test_analytics.py` 增 3 例（合法 204 / 非法 tab 422 / 新事件标签）。

---

### 3.3 块 C：时机收纳空白（约 1.5h）

**C1 finished 拆出独立「回顾」tab**

```js
const WS_FINISHED_KEYS = ['journey', 'passport', 'story', 'events']
// phaseTabs：
if (p === 'live') return [{ key: 'live', label: t('tripDetail.tabs.live'), keys: WS_LIVE_KEYS, badge: journeyProgress }]
if (p === 'finished') return [{ key: 'review', label: t('tripDetail.tabs.review'), keys: WS_FINISHED_KEYS, badge: journeyProgress }]
```
- i18n 增 `tripDetail.tabs.review`：zh `回顾` / en `Recap`（zh-CN.js:413 / en-US.js:413）。
- 动机：行程已结束，页面却挂「行中」标签；且 `events`（事件流）在回顾时有价值，行中时是噪音。

**C2 prep 增「规划」tab（默认仍停在「行前」）**

```js
if (p === 'prep') return [
  { key: 'prep', label: ..., keys: WS_PREP_KEYS, badge: bookingBadge },
  planTab.value,   // 质检问题数徽标 = 有几件事没处理完
]
```
- `watch(phase)` 已取 `phaseTabs[0]` → 默认仍停在「行前」，不改变首屏行为。
- 副作用：`wsPlanExtra` 在 prep 变冗余（逻辑保留无害）；「更多 → 调整行程」仍能滚到主路径的 PlanTools。

---

### 3.4 块 D：登记与文档收口（约 0.5h）

1. 实施记录补 `§11 收口记录（2026-11）`：A/B/C 三块 + flag 矩阵实测结果 + 埋点实测截图路径。
2. `docs/nightly/checkpoint.json` issues：把「阶段二未做待 review」改写为「阶段二已实现（1326efe）+ 2026-11 收口」。
3. `docs/night-build-todo.md` 对应行补状态说明（原勾选行追加收口结论）。
4. PRD 增 `§4.1 实现期偏差登记`：原 4 条 + 本轮 2 条（finished 独立回顾 tab、prep 双 tab）+「百分比灰度降级」决定。
5. 技能 `my-trip-planner-dev` 的「续工」段更新一行（下一步不再是阶段二）。

---

## 4. 最终分组矩阵（提案）

| 时机 | tab（左→右） | 面板 | 徽标 | 首屏 |
|---|---|---|---|---|
| planning | 规划 | timegate / quality / hotel（+ revise/planb 在主路径） | 问题数 | 单 tab 头，D1 展开 |
| prep | **行前** · 规划 | 行前：booking / hotel / servicing / packing / events；规划：timegate / quality | 预订状态 / 问题数 | 停「行前」，booking 展开 |
| live | 行中 | journey / passport / story | 完成度 n/m | journey 展开 |
| finished | **回顾** | journey / passport / story / events | 完成度 n/m | 全部收起，评分卡在工作台外 |

`revise` / `planb` 在 `hoist` 开时不进工具箱（同屏避免两份）；`hoist` 关时回工具箱内。

---

## 5. 验证方案

**自动化**
```bash
cd backend && .venv/bin/python -m pytest tests/test_feature_flags.py tests/test_flags_api.py tests/test_analytics.py -q
cd backend && .venv/bin/python -m pytest tests/ -q          # 全量回归（当前基线 781+）
cd frontend && npm run build                                 # 目标 ≤5s 无 warning
cd frontend && npm run check:i18n                            # zh/en 键数一致，新增 2 键
```

**flag 矩阵手测（6 组，必测项）**

| # | 总闸 | 子开关 | 期望 |
|---|---|---|---|
| 1 | on | 全 on | 目标版面（§4 矩阵） |
| 2 | on | tabs off | 工作台 12 面板平铺，主路径仍有 PlanTools |
| 3 | on | hoist off | PlanTools 消失，revise/planb 回工具箱（G1 对照组） |
| 4 | on | collapseDays off | 逐日全展开，「展开/收起全部」文案正确 |
| 5 | off | — | 完整 v1：三组虚线分组平铺、无 tab 条、无 PlanTools |
| 6 | off + 点「更多→调整行程」 | — | 滚到工具箱顶，**不出现死 tab** |

**服务端 kill switch 实测**：`FEATURE_FLAGS_JSON='{"tripDetail.ia.v2":false}'` 重启 → 无痕窗口打开详情页（不带 `?flag=`）→ 60s 内版面回 v1；再改回 `true` 重启 → 回 v2。

**真机四时机**（现成测试行程：大理 10-27~10-29 = live / 厦门 prep / 厦门 planning，任一过期行程 = finished）+ 375×812 移动端无横向溢出 + 导出 PDF 抓全文（`exportAll` 强制展开仍生效）。

**埋点实测**：DevTools Network 看 `POST /api/v1/analytics/events` 的 `name` 与 `payload.tab/from/on`；后端日志 grep `analytics_event` 行含新字段。

---

## 6. 回滚预案（按生效时间排序）

| 级 | 操作 | 范围 | 生效 |
|---|---|---|---|
| 1 | 链接加 `?flag=tripDetail.ia.v2=off` | 单会话 | 刷新即生效（`isFlagOn` 只读一次 → **必须刷新**） |
| 2 | `localStorage.setItem('mtp.flag.tripDetail.ia.v2','0')` | 单浏览器 | 刷新即生效 |
| 3 | 后端 env `FEATURE_FLAGS_JSON='{"tripDetail.ia.v2":false}'` + 重启 | **全站** | ~30s + 前端 60s 缓存；**无需重新发布前端** |
| 4 | `git revert <A/B/C 各自 commit>` | 代码级 | 发布后生效（5–10 min） |

> 已知限制（写进 PRD §4.1）：`?flag=` 覆盖不持久、且会随复制的链接传播——仅限验收/内部使用，不作为对用户的分流手段。

---

## 7. 风险与取舍

1. **响应式 flag 在运行中翻转会重建整块 DOM** → 正在输入的修订文本可能丢失。缓解：只在 `iaV2` 变化时重置 `wsTab/wsShowAll`，不重建页面级状态；接受「运维切开关时可能丢一次输入」。
2. **prep 多一个 tab = 工具可能在两个地方**的认知成本。用徽标（待处理问题数）指路，而不是靠用户自己翻。
3. **服务端 flags 端点**是新增公开面。风险极低（只回布尔、无 trip/user 维度），仍加 60s 缓存与白名单 key（只允许 `tripDetail.*`，防止未来有人把敏感配置塞进来）。
4. **不引 Playwright/测试框架**：项目前端目前只有 `build` + `check:i18n` 作为门禁，本轮不为此新增依赖；flag 矩阵靠人工清单 + 截图存 `docs/nightly/worklog/`。
5. **A2 若被否**：回滚只能到浏览器级（级 1/2），全站回滚需重新发布——这是唯一的实质取舍点，见 §8-Q3。

---

## 8. 需要拍板的 3 个问题

- **Q1** finished 的 tab 标签用「回顾」（默认）/「行程回顾」/ 继续复用「行中」？
- **Q2** prep 是否给「规划」tab（默认给，默认选中仍在「行前」）？
- **Q3** 服务端 kill switch（A2，约 1h）做不做？不做则全站回滚 = 重新发布前端。

未答复时按默认值执行（Q1=回顾、Q2=给、Q3=做）。

---

## 9. 排期建议

| 晚 | 内容 | 交付 |
|---|---|---|
| 第 1 晚 | A（A1→A3）+ B | 两个 commit；flag 矩阵 6 组实测；kill switch 实测 |
| 第 2 晚 | C + D | 两个 commit；四时机真机截图；埋点实测；登记收口 |

每块独立 commit（`feat(detail-ia): …`），可单独 revert；不新增数据库迁移，无数据回滚面。
