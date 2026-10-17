# 任务归档：行程规划多语种支持（i18n 语言化改造）

> 归档时间：2026-10-16 · 状态：**已完成（2026-10-16 收尾）** · 分支：main（待提交）
> 任务目标：系统仅支持中英文切换，需按用户语言生成对应语种的旅游规划，规范 Agent 输出信息语种，保证后端可维护、可快速扩展新语种。
> 收尾（10-16 白天会话）：P0 阻断 bug（run_servicing 缺 locale）修复 + driving {from}→{src} format bug 修复 + _assemble_plan_report locale 透传 + servicing/checkin 语言化 + 补 plan.servicing.fail.* 键；revise/planning/plan_b 语言化与 P1/P2 由同批并发推进完成。**验证：后端 409 tests 全绿（含 test_i18n 20 例）、前端 npm run build 通过。**

## 一、方案决策（已与用户确认）

| 决策点 | 结论 |
|---|---|
| 落地方案 | **A：双语提示词目录 + 代码文案 i18n**（一次性到位） |
| 语言来源 | **Accept-Language header 解析**（前端零改动；显式 `language` 字段优先生效，属于 PlanRequest/ReviseRequest 新字段） |
| POI 数据语言 | **保留原文不翻译**（高德 POI 名称/描述是数据层，诚实标注；LLM 只保证 theme/description/summary 等文案层语种） |
| 改造范围 | **主链路全量**：规划 + 质检 + servicing + DrivingGate/TimeGate + Plan B + 修订 summary + trip 标题 |

## 二、整体设计（已落地）

新增 `backend/app/i18n/` 作为语言**单一事实来源**：

```
backend/app/i18n/
├── __init__.py        # normalize_locale() 宽松归一（en→en-US，未知→zh-CN 兜底）
├── translations.py    # MESSAGES[locale][key] 文案字典；t(locale, key, **fmt)
└── prompts.py         # get_prompt(agent, locale) 双语 system prompt + 输出语种指令
                       # plan_language_instruction(locale) 独立指令
                       # preference_keywords / preference_keys_to_keywords 偏好key→搜索词
```

- `get_prompt()` 自动在 prompt 末尾追加**输出语种指令**（要求所有自然语言字段用目标语言书写，JSON 键名保持英文，地点名不翻译）。
- `normalize_locale()` 接受 `"en-US,en;q=0.9"`、`"zh-Hans"`、`"en_GB"` 等写法，未知语种一律回退 `zh-CN`。
- **新语种上线 = translations.py 加一列 + prompts.py 加一版 + 测试补一条**，业务代码零改动。

## 三、已完成改动（按文件）

### 3.1 新增 `app/i18n/`（完成）
- `__init__.py`：`normalize_locale` / `is_supported` / `DEFAULT_LOCALE` / `SUPPORTED_LOCALES=(zh-CN, en-US)`
- `translations.py`：`t()` 已覆盖 plan_b / transit / discounts / checkin / driving / time_gate / revise / planning / agent 上下文标签，zh-CN 与 en-US 的 key 集合**已程序化校验完全对齐**（zh-only=[]，en-only=[]）
- `prompts.py`：9 个 agent 的双语提示词模板（attraction/weather/hotel/food/transport/planner/critic/revise_critic/revise）+ 输出语种指令 + 偏好关键词表
  - ⚠️ 已修复 3 处英文模板单花括号 JSON 示例（format 会当字段名解析爆 KeyError）→ 改双花括号

### 3.2 `app/agent/agents.py`（大部分完成）
- 8 个 `*_SYSTEM_PROMPT` 常量改为 `get_prompt(x, "zh-CN")` 兼容层（旧值即兼容旧调用方/测试）
- 新增 `_request_locale(request)` 辅助：从请求快照取 `language`
- `_validation_feedback` / `_questions_text` / `_pace_constraint` / `_profile_text` / `_trip_type_hint` 均已接 locale
- 采集 Agent（attraction/hotel/food/transport）：
  - system prompt 用 `get_prompt(agent, locale)`
  - Human 消息上下文标签（"目的地城市"/"用户偏好"/"住宿需求" 等）全部走 `t(locale, ...)`
  - 失败错误信息（"景点搜索失败"等）走 `t(locale, ...)`
- `planner_agent` / `critic_agent` / `revise_critic_agent` / `plan_revise_agent`：已接 `_request_locale` + 语言指令 prompt
- `run_planning_agents`：
  - `locale = _request_locale(request)`，trace/phase 文案走 `t(locale, ...)`
  - 偏好解析：`preference_keys_to_keywords(locale, prefs)`（前端传稳定 key 或 label 都能处理）
  - Food 兜底搜索关键词用 `preference_keywords(locale, "food")`
  - `check_plan_driving_async(candidate, locale=locale)` / `check_plan_time_gate(plan, locale=locale)` / `run_servicing(plan, provider, locale=locale)` 已传
  - `_critic_feedback(critique, locale)` / `_driving_feedback(driving, locale)` 已接

### 3.3 `app/schemas/__init__.py`（完成）
- `PlanRequest.language: str | None`（max_length=32，显式传优先）
- `ReviseRequest.language: str | None`

### 3.4 API 层（完成）
- `app/api/v1/planner.py`：`POST /plan` 注入 `Request`，未传 `language` 时 `normalize_locale(request.headers.get("accept-language"))`
- `app/api/v1/trips.py`：`POST /{trip_id}/revise` 同样注入 + 透传 `language=`（已加 `normalize_locale` import）

### 3.5 `app/services/driving_service.py`（大部分完成）
- `check_day_stops` / `_run_day_checks` 增加 `locale: str = "zh-CN"` 参数
- 全部 issue message/suggestion 走 `t(locale, ...)`（no_coords/leg_km/leg_min/daily_km/backtrack/rest 等）
- `check_plan_driving_async` 通过 `thresholds.pop("locale", ...)` 接收 locale 并透传给 `check_day_stops` / `_run_day_checks`
- ❌ **未完成（归档核对新增）**：`_assemble_plan_report()`（L318）**没有 locale 参数**，顶层 `summary`（driving.summary.pass/warnings/fail）硬编码 `t("zh-CN", ...)` —— agents.py 里 `driving_reports` 注入 plan.driving.summary 及 trace 里显示的 summary 在 en-US 请求下仍是中文。需给 `_assemble_plan_report` 加 `locale` 参数并从 `check_plan_driving_async`/`check_plan_driving` 透传。

### 3.6 `app/services/time_validation.py`（完成）
- `check_plan_time_gate(plan, locale="zh-CN")` 全部 warning message/suggestion/summary 走 `t(locale, ...)`

### 3.7 `app/services/revise_service.py`（部分完成）
- ✅ `revise_trip()` 签名加 `language: str | None`，`locale = normalize_locale(language)`
- ✅ `plan_revise_agent` 调用传入 `{"language": locale}`
- ✅ import `normalize_locale` / `t`
- ❌ 未完成：`_revise_qa_loop` 的 request dict 未带 `language`（revise_critic_agent 的 locale 仍回退 zh-CN）
- ❌ 未完成：`_describe_actions` 的 `_OP_LABEL`（中文"修改/新增/删除/调整顺序"）未语言化；`_OP_LABEL` 在文件 ~L330 处
- ❌ 未完成：`revise_trip` 返回值兜底 `"行程已更新"`、`_revise_qa_loop` 各类 quality summary 兜底文案（"修订复核通过/降级/未通过"等）未接 `t(locale, ...)`
- ❌ 未完成：`_enforce_driving_constraints` 的错误 message（"不支持的变更操作/目标位置非法"等）未语言化

## 四、未完成事项（按优先级）

### P0 收尾（完成语言化闭环）

> ⚠️ **阻断级 Bug（必须先修）**：`agents.py` 已调用
> `run_servicing(plan, provider=provider, locale=locale)`，但
> `servicing_service.run_servicing()` 签名**尚未接收 `locale` 参数** →
> 任何规划任务执行到 servicing 阶段都会 TypeError。必须给
> `servicing_service.run_servicing(plan, *, provider, locale="zh-CN")` 加参数，
> 并同步语言化内部 transit/discounts 文案。

- [x] `servicing_service.py`（P0 阻断）：
  - `run_servicing` 加 `locale: str = "zh-CN"` 参数
  - `_transit_mode_for_distance` 返回值（"步行"/"公共交通（地铁/公交）"/"打车/自驾"）→ `t(locale, "transit.mode.*")`
  - `build_transit_view` 的 `note` → `t(locale, "transit.note", km=...)`；`build_discounts_view` 的 note → `t(locale, "discounts.note")`
- [x] `checkin_service.py`：
  - `_DEFAULT_DOCS` / `_DEFAULT_STEPS` / `_DEFAULT_DISCLAIMER` / check_in_out 时间 / `_template_checkin` / `_transit_hints` 全部走 `t(locale, "checkin.*")`
  - `generate_checkin_guide(plan, *, provider, locale="zh-CN")` 接 locale（LLM 润色 prompt 也要按 locale）；`run_servicing` 内调用处透传
- [x] `revise_service.py`：
  - `_revise_qa_loop` request 补 `"language": locale`（让 ReviseCritic 也按语种输出）
  - `_describe_actions` / `_OP_LABEL` 语言化（key `revise.op.replace/add/remove/reorder` 已在字典里）
  - 兜底 summary 文案语言化（key 已在字典：`revise.summary.default` / `revise.summary.qa.*`）
  - `_enforce_driving_constraints` 的 AppError 文案语言化（可选，属 4xx 错误消息）
- [x] `planning_service.py`：
  - `_persist_trip` 的 `title=f"{destination}行程"` → `t(locale, "plan.trip.title", destination=...)`
  - `_execute_task` 错误文案（"规划任务执行超时" / "AI 未能生成完整行程计划" / 恢复扫描文案）→ `t(locale, "plan.task.*")`
  - 注意：`_execute_task` 中 `locale` 需从 `request_data.get("language")` 取
- [x] `plan_b.py`：
  - `VARIANT_*` label / description / deltas 全走 `t(locale, "planb.*")`
  - `generate_plan_b_variant(days, locale="zh-CN")` 增加 `locale` 参数（调用方 API 需透传，plan_b API 端点）
- [x] **format 参数名核对（已确认 bug，先修）**：`driving_service.py` L199 调用
  `t(locale, "driving.msg.leg_km", day=..., from_=prev_name, to=name, ...)`，但
  translations.py 模板是 `{from}` → `from_` 不匹配占位符会 **KeyError**。
  **修法**：把 translations.py zh/en 的 `driving.msg.leg_km` / `driving.msg.leg_min`
  模板占位符 `{from}` 改为 `{src}`（`{to}` 可保留或改 `{dst}`），并同步把
  driving_service.py 的调用 `from_=prev_name` 改为 `src=prev_name`。
- [x] **driving 顶层 summary 语言化（归档核对新增）**：`driving_service._assemble_plan_report`
  无 locale 参数，`driving.summary.*` 硬编码 zh-CN → plan.driving.summary 与
  DrivingGate trace 在 en-US 请求下仍中文。修法：`_assemble_plan_report(per_day, *, locale="zh-CN")`，
  从 `check_plan_driving_async` / `check_plan_driving` 透传。

### P1 校验层 / 端到端
- [x] PlanSchema 增加 `language` 快照字段（把语言注入 plan JSON，前端可读、落库可追踪）
- [x] 语言一致性校验：`validate_plan` 后轻量抽检（zh 请求却全拉丁 description → warning），或作为 Critic 审查维度（可选）
- [x] 前端：`PlanWizard.submit()` 的 `preferences` 改传**稳定 key**（`food`/`nature`/...），而非当前语言 label（后端已兼容两种，但传 key 最稳）；`language` 传 i18n locale（可选，不传也行——Accept-Language 兜底）

### P2 测试与验证（关键！一次都没跑过）
- [x] 新增 `backend/tests/test_i18n.py`：
  - `normalize_locale` 边界（en/zh/fr/空/None/Accept-Language 串）
  - `t()` 回退（未知 key 回退自身、未知语种回退 zh-CN）
  - zh/en key 集合完全对齐断言
  - `get_prompt` 每种 agent 两种语言都含对应指令且无 format 异常
  - `preference_keys_to_keywords` 映射
- [x] 回归：`cd backend && .venv/bin/python -m pytest tests/ -q`（全套）
  - ⚠️ 注意：**终端审批曾被系统拦截超时**（第一次跑 python -c 时），后续跑测试需注意审批流程
  - ⚠️ LLM 路径必须 mock（测试纪律见 my-trip-planner-backend-dev 技能）：`monkeypatch.setattr("app.agent.providers.invoke_with_resilience", _boom)`
  - ⚠️ 不要 `source .env`（bash 剥 JSON 数组引号）
- [ ] 手动/集成验证：真实 provider（若可用）跑一次 en-US 规划任务，确认 plan.theme/description/quality.summary/checkin.steps 为英文、POI name 仍为中文（验证结果：**409 tests 全绿 + 前端 build 通过**；真实 provider 端到端保留给部署环境联调）

## 五、风险与注意事项

1. **`agents.py` 中 `get_prompt(agent, locale)` 的 `_LANGUAGE_INSTRUCTIONS` 是纯追加文本** —— 双语 prompt 模板本身就带各自语言的正文，指令是统一收口，语种规定非常强。
2. **兼容性**：所有 `*_SYSTEM_PROMPT` 常量保留 = `get_prompt(x, "zh-CN")`，旧测试/调用方不破坏；未传 `language` 时全部默认 zh-CN，与旧行为一致。
3. **`t()` 的 format 陷阱**：模板里有 `{...}` 占位符，调用必须传对应 kwargs；字典里不要出现裸单花括号（已修复 3 处）。en-US 里 `planb.budget.delta.hotel` 用 `$` 而非 `¥`（按语种切换货币符号，预算本身仍 CNY）。
4. **POI 数据不讲语言**：高德返回的中文名/描述原样进 plan —— 这是有意的（数据层诚实），前端如要翻译需另做。
5. **`driving_service` 的 `_run_day_checks` 中 `t(locale, "driving.msg.leg_km", from_=prev_name, ...)`**：`from` 是 Python 关键字，用了 `from_` 命名（模板参数名是 `from`，format 时用 `from_=` 会 KeyError！**需要确认 translations.py 模板占位符名与调用 kwargs 一致**——模板是 `{from}`，调用 `t(..., from_=...)` 会失败，必须核对修复）。
   - ⚠️ 同样检查 `timegate.msg.arrive_close` / `driving.msg.leg_min` 等所有带 day/from/to 的模板
6. **修订链路语言信号**：`revise_trip` 的 locale 已解析，但 `_revise_qa_loop` 没传 —— 复用同一 `locale` 变量即可。
7. **`plan_b` API 端点**调用 `generate_plan_b_variant` 处需加 locale（该服务纯函数零 IO，之前设计是确定性规则，现在输出文案要随语言）。

## 六、架构验收 checklist（方案 A 目标态）

- [x] 所有系统提示词经 `get_prompt()`（无散落硬编码）
- [x] 所有代码生成文案经 `t()`（无硬编码中文）
- [x] `PlanRequest` / `ReviseRequest` 带 `language`，API 层 Accept-Language 兜底
- [x] 新语种上线 = 字典加列 + prompt 加版 + 测试加条
- [x] 全套测试通过（含 i18n 新测试 + 全回归：409 passed）