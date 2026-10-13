"""TimeGate 营业时间/游玩时长校验测试（确定性规则库，零外部依赖）。"""

from app.services.time_validation import (
    CLOSING_BUFFER_MINUTES,
    MAX_PLAY_MINUTES_PER_DAY,
    MAX_STOPS_PER_DAY,
    check_plan_time_gate,
)


def _stop(name, stop_type="attraction", **kw):
    return {"name": name, "stop_type": stop_type, **kw}


def _day(day_number, *stops):
    return {"day_number": day_number, "stops": list(stops)}


# ── 正常路径：松紧适中的一天不产生任何提示 ──
def test_passing_plan_no_issues():
    plan = {
        "days": [
            _day(
                1,
                _stop("故宫", visit_start="09:00", estimated_duration_minutes=180),
                _stop("景山公园", visit_start="12:30", estimated_duration_minutes=90),
                _stop("南锣鼓巷", stop_type="food", visit_start="14:30", estimated_duration_minutes=60),
            )
        ]
    }
    result = check_plan_time_gate(plan)
    assert result["passed"] is True
    assert result["issues"] == []
    assert result["critical_count"] == 0
    assert result["warning_count"] == 0


# ── 闭馆到达：到达时刻 ≥ 闭馆 - 缓冲 → warning（Culture basis 18:00 关门）──
def test_closing_time_visit_warns():
    plan = {
        "days": [
            _day(
                1,
                _stop("颐和园", visit_start="17:40", estimated_duration_minutes=120),
            )
        ]
    }
    result = check_plan_time_gate(plan)
    assert result["passed"] is False
    assert result["warning_count"] >= 1
    closing = [i for i in result["issues"] if "闭馆" in i["message"]]
    assert closing, "应产生闭馆到达提示"
    assert "颐和园" in closing[0]["message"]
    assert "18:00" in closing[0]["message"]
    assert closing[0]["severity"] == "warning"
    assert closing[0]["category"] == "schedule"
    assert closing[0]["day_number"] == 1


# ── 闭馆缓冲边界：到达 17:29 距闭馆 31 分钟 → 不告警 ──
def test_closing_buffer_boundary_no_warning():
    plan = {
        "days": [
            _day(1, _stop("颐和园", visit_start="17:29", estimated_duration_minutes=120))
        ]
    }
    result = check_plan_time_gate(plan)
    assert result["passed"] is True
    assert all("闭馆" not in i["message"] for i in result["issues"])


# ── 显式 open_hours 优先于规则库：夜市 17:00-23:00 晚到不告警 ──
def test_explicit_open_hours_overrides_basis():
    plan = {
        "days": [
            _day(
                1,
                _stop("夜市", stop_type="food", visit_start="21:00", open_hours="17:00-23:00"),
            )
        ]
    }
    result = check_plan_time_gate(plan)
    assert result["passed"] is True
    assert all("闭馆" not in i["message"] for i in result["issues"])


# ── 未知类目：规则库不编造时间，绝不误伤 ──
def test_unknown_type_silent():
    plan = {
        "days": [
            _day(1, _stop("神秘体验", stop_type="unknown_custom", visit_start="23:00"))
        ]
    }
    result = check_plan_time_gate(plan)
    assert result["passed"] is True
    assert result["issues"] == []


# ── 单日过饱和：站点数超限 → warning ──
def test_too_many_stops_warns():
    stops = [_stop(f"景点{i}", estimated_duration_minutes=60) for i in range(MAX_STOPS_PER_DAY + 1)]
    plan = {"days": [_day(1, *stops)]}
    result = check_plan_time_gate(plan)
    assert result["passed"] is False
    stops_issue = [i for i in result["issues"] if "超过建议上限" in i["message"]]
    assert stops_issue, "应产生单日站点数超限提示"
    assert str(MAX_STOPS_PER_DAY + 1) in stops_issue[0]["message"]


# ── 单日过饱和：游玩时长合计超限 → warning（8 小时红线）──
def test_play_minutes_over_limit_warns():
    plan = {
        "days": [
            _day(
                1,
                _stop("A", estimated_duration_minutes=240),
                _stop("B", estimated_duration_minutes=240),
                _stop("C", estimated_duration_minutes=240),  # 合计 720 > 480
            )
        ]
    }
    result = check_plan_time_gate(plan)
    assert result["passed"] is False
    minutes_issue = [i for i in result["issues"] if "游玩时长合计" in i["message"]]
    assert minutes_issue, "应产生单日游玩时长超限提示"
    assert f"{MAX_PLAY_MINUTES_PER_DAY}" in minutes_issue[0]["message"]


# ── 无 visit_start：按一天起点 09:00 推算（不误报）──
def test_default_day_start_no_false_positive():
    plan = {
        "days": [
            _day(
                1,
                _stop("故宫", estimated_duration_minutes=180),  # 09:00 到达
                _stop("颐和园", estimated_duration_minutes=120),  # 12:00 到达
            )
        ]
    }
    result = check_plan_time_gate(plan)
    assert result["passed"] is True


# ── 顺序推进：前一站游玩完才到下一站，连续晚段可命中闭馆 ──
def test_cursor_propagates_across_stops():
    plan = {
        "days": [
            _day(
                1,
                _stop("A", visit_start="09:00", estimated_duration_minutes=540),  # 09:00-18:00
                _stop("B", estimated_duration_minutes=60),  # 推算到达 18:00 → 闭馆命中
            )
        ]
    }
    result = check_plan_time_gate(plan)
    assert result["passed"] is False
    closing = [i for i in result["issues"] if "闭馆" in i["message"]]
    assert closing, "前一站推完应命中第二站闭馆"
    assert "B" in closing[0]["message"]


# ── 结构兼容：结果与 CritiqueIssueSchema 契约对齐（前端质检卡可直接消费）──
def test_issue_shape_matches_critique_contract():
    plan = {
        "days": [
            _day(1, _stop("颐和园", visit_start="17:50", estimated_duration_minutes=120))
        ]
    }
    result = check_plan_time_gate(plan)
    assert result["issues"][0].keys() >= {
        "severity", "category", "message", "suggestion", "day_number",
    }
    assert result["issues"][0]["severity"] == "warning"
    assert result["issues"][0]["category"] == "schedule"
    assert result["summary"]


# ── 边界：空行程 / 空 stops 不崩溃 ──
def test_empty_plan_ok():
    assert check_plan_time_gate({})["passed"] is True
    assert check_plan_time_gate({"days": []})["passed"] is True
    assert check_plan_time_gate({"days": [_day(1)]})["passed"] is True
    assert check_plan_time_gate({"days": [_day(1, _stop(""))]})["issues"] == []