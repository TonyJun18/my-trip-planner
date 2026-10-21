"""动态事实校验（task-dynamic-facts-eval）测试：日期特例规则表。

确定性规则库，零外部依赖；日期用固定样例：
- 2026-10-19 是周一（博物馆闭馆日命中）
- 2026-11-01 是第一个周日（免费开放日命中）
- 2026-10-25 是周日（非闭馆日，静默）
"""

from app.services.dynamic_facts import check_plan_dynamic_facts


def _stop(name, **kw):
    return {"name": name, **kw}


def _day(day_number, date=None, *stops):
    d = {"day_number": day_number, "stops": list(stops)}
    if date:
        d["date"] = date
    return d


# ── 正常路径：无规则命中（普通景点 + 无日期）→ 无提示 ──
def test_passing_plan_no_issues():
    plan = {
        "days": [
            _day(1, None, _stop("西湖"), _stop("灵隐寺")),
        ]
    }
    result = check_plan_dynamic_facts(plan)
    assert result["passed"] is True
    assert result["issues"] == []


# ── 周一闭馆命中：具体日期是周一 → warning（建议改期）──
def test_weekly_closed_hit_on_monday():
    plan = {
        "days": [
            _day(1, "2026-10-19", _stop("故宫博物院"), _stop("西湖")),
        ]
    }
    result = check_plan_dynamic_facts(plan)
    assert result["passed"] is False
    hit = [i for i in result["issues"] if "闭馆" in i["message"]]
    assert hit, "应命中周一闭馆规则"
    assert "故宫博物院" in hit[0]["message"]
    assert "2026-10-19" in hit[0]["message"]
    assert hit[0]["severity"] == "warning"
    assert hit[0]["category"] == "schedule"
    assert hit[0]["day_number"] == 1
    assert hit[0]["basis"] == "rule_based"
    # 西湖不命中
    assert all("西湖" not in i["message"] for i in result["issues"])


# ── 周一闭馆未命中：日期不是周一 → 静默 ──
def test_weekly_closed_no_hit_on_sunday():
    plan = {
        "days": [
            _day(1, "2026-10-25", _stop("故宫博物院")),
        ]
    }
    result = check_plan_dynamic_facts(plan)
    assert result["passed"] is True
    assert result["issues"] == []


# ── 无具体日期但站点通常周一闭馆 → 提示「通常…请核对」──
def test_weekly_closed_undated_hints():
    plan = {
        "days": [
            _day(1, None, _stop("国家博物馆")),
        ]
    }
    result = check_plan_dynamic_facts(plan)
    assert result["passed"] is False
    hint = [i for i in result["issues"] if "通常" in i["message"]]
    assert hint, "无日期时也应提示通常闭馆日"
    assert "国家博物馆" in hint[0]["message"]


# ── 显式 open_hours 已声明周一闭馆 → 不双报 ──
def test_explicit_open_hours_skips_weekly_rule():
    plan = {
        "days": [
            _day(
                1,
                "2026-10-19",
                _stop("某博物馆", open_hours="09:00-17:00 (周一闭馆)"),
            ),
        ]
    }
    result = check_plan_dynamic_facts(plan)
    # 明确声明了周一闭馆 → 规则库不应重复报警（用户已知晓）
    assert result["passed"] is True
    assert result["issues"] == []


# ── 每月第一个周日免费：命中 → 提示免费开放 ──
def test_monthly_free_day_hit():
    plan = {
        "days": [
            _day(1, "2026-11-01", _stop("省博物馆")),
        ]
    }
    result = check_plan_dynamic_facts(plan)
    free = [i for i in result["issues"] if "免费" in i["message"]]
    assert free, "应命中每月第一个周日免费规则"
    assert "2026-11-01" in free[0]["message"]
    assert "省博物馆" in free[0]["message"]


# ── 每月第一个周日免费：未命中（不是第一个周日）→ 静默 ──
def test_monthly_free_day_no_hit():
    plan = {
        "days": [
            _day(1, "2026-10-25", _stop("省博物馆")),
        ]
    }
    result = check_plan_dynamic_facts(plan)
    assert all("免费" not in i["message"] for i in result["issues"])


# ── 节假日窗口：国庆期间 → 提示开放时间可能调整 ──
def test_holiday_window_hit():
    plan = {
        "days": [
            _day(1, "2026-10-01", _stop("故宫博物院")),
        ]
    }
    result = check_plan_dynamic_facts(plan)
    holiday = [i for i in result["issues"] if "节假日" in i["message"]]
    assert holiday, "国庆假期应命中节假日规则"
    assert "2026-10-01" in holiday[0]["message"]


# ── 节假日窗口未命中（非假期）→ 静默 ──
def test_holiday_window_no_hit():
    plan = {
        "days": [
            _day(1, "2026-10-25", _stop("故宫博物院")),
        ]
    }
    result = check_plan_dynamic_facts(plan)
    assert all("节假日" not in i["message"] for i in result["issues"])


# ── 空行程 / 空 stops 不崩溃 ──
def test_empty_plan_ok():
    assert check_plan_dynamic_facts({})["passed"] is True
    assert check_plan_dynamic_facts({"days": []})["passed"] is True
    assert check_plan_dynamic_facts({"days": [_day(1)]})["passed"] is True


# ── 未知站点名不命中（保持沉默，绝不误伤）──
def test_unknown_stop_silent():
    plan = {
        "days": [
            _day(1, "2026-10-19", _stop("神秘体验馆")),
        ]
    }
    result = check_plan_dynamic_facts(plan)
    assert result["passed"] is True
    assert result["issues"] == []


# ── 结构兼容：与 CritiqueIssueSchema 契约对齐 ──
def test_issue_shape_matches_contract():
    plan = {
        "days": [
            _day(1, "2026-10-19", _stop("故宫博物院")),
        ]
    }
    result = check_plan_dynamic_facts(plan)
    assert result["issues"][0].keys() >= {
        "severity", "category", "message", "suggestion", "day_number",
    }
    assert result["issues"][0]["severity"] == "warning"
    assert result["summary"]


# ── en-US 语种回退（键存在则用英文文案）──
def test_en_locale():
    plan = {
        "days": [
            _day(1, "2026-10-19", _stop("故宫博物院")),
        ]
    }
    result = check_plan_dynamic_facts(plan, locale="en-US")
    assert result["issues"]
    assert "closed" in result["issues"][0]["message"].lower() or "故宫" in result["issues"][0]["message"]