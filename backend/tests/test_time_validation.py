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


# ── 体力负荷（task-exertion-check）───────────────────────────────
# 高强度：单日含登山/徒步（名称关键词 → 系数 ≥ 阈值）→ 提示「实际耗时显著上浮」
def test_high_intensity_stop_warns_spot():
    plan = {
        "days": [
            _day(
                1,
                _stop("华山", stop_type="attraction", estimated_duration_minutes=120),  # 名山后缀 2.2
                _stop("山下古镇", stop_type="attraction", estimated_duration_minutes=60),  # 排除词 → 0
            )
        ]
    }
    result = check_plan_time_gate(plan)
    assert result["passed"] is False
    spot = [i for i in result["issues"] if "高强度" in i["message"]]
    assert spot, "应产生高强度站点提示"
    assert "华山" in spot[0]["message"]
    assert "2.2" in spot[0]["message"]  # 山岳系数
    assert spot[0]["severity"] == "warning"

# 高强度：单日累计体力负荷超限 → 提示当日体能压力大
def test_exertion_total_over_limit_warns():
    plan = {
        "days": [
            _day(
                1,
                _stop("华山", stop_type="attraction", estimated_duration_minutes=240),  # 240×2.2=528
                _stop("玉龙雪山", stop_type="attraction", estimated_duration_minutes=120),  # 120×2.5=300 → 合计 828 > 720
            )
        ]
    }
    result = check_plan_time_gate(plan)
    assert result["passed"] is False
    heavy = [i for i in result["issues"] if "体力负荷" in i["message"]]
    assert heavy, "应产生单日体力负荷超限提示"
    assert "792" in heavy[0]["message"]  # 华山240×2.2 + 玉龙雪山120×2.2 = 792

# 常规：纯常规观光（低系数）→ 无体力提示
def test_regural_stops_no_exertion_warning():
    plan = {
        "days": [
            _day(
                1,
                _stop("西湖", stop_type="attraction", estimated_duration_minutes=120),
                _stop("中国美院", stop_type="museum", estimated_duration_minutes=90),
                _stop("湖滨银泰", stop_type="food", estimated_duration_minutes=60),
            )
        ]
    }
    result = check_plan_time_gate(plan)
    assert all("体力" not in i["message"] for i in result["issues"])
    # 且不应产生高强度站点提示
    assert not any("高强度" in i["message"] for i in result["issues"])

# 混合：含一个高强度但总负荷未超 → 只有 spot 提示，无 total 提示
def test_mixed_day_only_spot_warning():
    plan = {
        "days": [
            _day(
                1,
                _stop("灵隐飞来峰", stop_type="attraction", estimated_duration_minutes=90),  # 峰 → 2.2？检查关键词
                _stop("博物馆", stop_type="museum", estimated_duration_minutes=60),          # 0.8
                _stop("餐馆", stop_type="food", estimated_duration_minutes=60),              # 0.4
            )
        ]
    }
    result = check_plan_time_gate(plan)
    spot = [i for i in result["issues"] if "高强度" in i["message"]]
    heavy = [i for i in result["issues"] if "体力负荷" in i["message"]]
    assert spot, "混合日含高强度站点应产生 spot 提示"
    assert not heavy, "总负荷未超限不应产生 total 提示"

# 未知类目按常规基准（系数 1.0）→ 不触发高强度提示
def test_unknown_type_default_exertion():
    plan = {
        "days": [
            _day(1, _stop("神秘体验", stop_type="unknown_custom", estimated_duration_minutes=120))
        ]
    }
    result = check_plan_time_gate(plan)
    assert all("体力" not in i["message"] for i in result["issues"])

# 排除词：山下古镇/老山城火锅 含「山」但不误判为高强度
def test_exclude_keywords_not_high_exertion():
    plan = {
        "days": [
            _day(
                1,
                _stop("山下古镇", estimated_duration_minutes=90),
                _stop("老山城火锅", stop_type="food", estimated_duration_minutes=60),
            )
        ]
    }
    result = check_plan_time_gate(plan)
    assert all("高强度" not in i["message"] for i in result["issues"])
    assert all("体力负荷" not in i["message"] for i in result["issues"])