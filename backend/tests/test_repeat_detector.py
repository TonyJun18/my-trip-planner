"""重复站点查重（RepeatGate，task-repeat-stop-detector）测试。

确定性规则库，零外部依赖。对齐验收标准：
- 同天重复 / 相邻两天重复（覆盖研究 57% 主战场）
- 远端重复（仅长行程 ≥10 天提示，长行程放大）
- 同 POI 别名识别（归一化 + 子串）
- 酒店 / 交通占位 跳过
- 短行程远端重复静默（不误伤换城重游）
"""

from app.services.repeat_detector import check_plan_repeat_gate, normalize_stop_key


def _stop(name, **kw):
    return {"name": name, **kw}


def _day(day_number, *stops):
    return {"day_number": day_number, "stops": list(stops)}


# ── 正常路径：无重复（含同名不同地？不，同 POI 即命中；这里只放不同 POI）──
def test_passing_plan_no_issues():
    plan = {
        "days": [
            _day(1, _stop("西湖"), _stop("灵隐寺")),
            _day(2, _stop("乌镇")),
        ]
    }
    result = check_plan_repeat_gate(plan)
    assert result["passed"] is True
    assert result["issues"] == []


# ── 同天重复：同一天排两个相同景点 → warning ──
def test_same_day_repeat_hit():
    plan = {
        "days": [
            _day(1, _stop("西湖"), _stop("灵隐寺"), _stop("西湖")),
        ]
    }
    result = check_plan_repeat_gate(plan)
    assert result["passed"] is False
    assert result["warning_count"] == 1
    hit = result["issues"][0]
    assert "西湖" in hit["message"]
    assert hit["severity"] == "warning"
    assert hit["category"] == "schedule"
    assert hit["day_number"] == 1
    assert hit["basis"] == "rule_based"


# ── 相邻两天重复：Day1 + Day2 同景点 → warning（覆盖研究 57% 主战场）──
def test_adjacent_day_repeat_hit():
    plan = {
        "days": [
            _day(1, _stop("故宫博物院")),
            _day(2, _stop("故宫博物院")),
        ]
    }
    result = check_plan_repeat_gate(plan)
    assert result["passed"] is False
    hit = [i for i in result["issues"] if "故宫" in i["message"]]
    assert hit, "应命中相邻天重复"
    assert hit[0]["day_number"] == 1


# ── 远端重复（间隔 ≥2 天）：短行程静默 → 长行程（≥10 天）提示 ──
def test_far_repeat_silent_on_short_trip():
    # 5 天行程，Day1 与 Day5 同景点 → 静默（不误伤换城重游）
    plan = {
        "days": [
            _day(1, _stop("西湖")),
            _day(2, _stop("灵隐寺")),
            _day(3, _stop("乌镇")),
            _day(4, _stop("千岛湖")),
            _day(5, _stop("西湖")),
        ]
    }
    result = check_plan_repeat_gate(plan)
    assert result["passed"] is True
    assert result["issues"] == []


def test_far_repeat_hit_on_long_trip():
    # 10 天行程，Day1 与 Day9 同景点 → 提示（长行程放大）
    days = [_day(n, _stop(f"景点{n}")) for n in range(1, 11)]
    days[0] = _day(1, _stop("西湖"))
    days[8] = _day(9, _stop("西湖"))
    plan = {"days": days}
    result = check_plan_repeat_gate(plan)
    assert result["passed"] is False
    hit = [i for i in result["issues"] if "西湖" in i["message"]]
    assert hit, "长行程远端重复应提示"
    assert result["warning_count"] == 1


def test_long_trip_threshold_boundary():
    # 9 天行程 Day1+Day9 远端重复 → 静默；10 天 → 提示（阈值边界）
    def _trip(n_days, far=True):
        days = [_day(n, _stop(f"景点{n}")) for n in range(1, n_days + 1)]
        if far:
            days[0] = _day(1, _stop("西湖"))
            days[n_days - 1] = _day(n_days, _stop("西湖"))
        return {"days": days}

    assert check_plan_repeat_gate(_trip(9))["passed"] is True
    assert check_plan_repeat_gate(_trip(10))["passed"] is False


# ── 同 POI 别名识别：归一化（空白大小写）+ 子串（西湖 vs 西湖风景区）──
def test_alias_substring_recognized():
    plan = {
        "days": [
            _day(1, _stop(" 西湖 ")),
            _day(2, _stop("西湖风景区")),
        ]
    }
    result = check_plan_repeat_gate(plan)
    assert result["passed"] is False
    assert "西湖" in result["issues"][0]["message"]


def test_normalize_key_whitespace_case():
    assert normalize_stop_key(" 西湖 风景区 ") == "西湖风景区"
    assert normalize_stop_key("The Bund") == "thebund"


def test_short_alias_prefix_not_merged():
    # 单字公共前缀不合并（「一环」vs「二环路」不是同一 POI）
    plan = {
        "days": [
            _day(1, _stop("一环")),
            _day(2, _stop("二环路")),
        ]
    }
    assert check_plan_repeat_gate(plan)["passed"] is True


# ── 酒店 / 交通占位 / 空名 跳过（重复不误报）──
def test_hotel_and_transfer_skipped():
    plan = {
        "days": [
            _day(1, _stop("西湖"), _stop("杭州大酒店", stop_type="hotel")),
            _day(2, _stop("杭州大酒店", stop_type="hotel")),  # 连住正常
            _day(3, _stop("前往苏州（交通占位）", is_transfer=True), _stop("苏州博物馆")),
            _day(4, _stop("前往苏州（交通占位）", is_transfer=True)),
        ]
    }
    result = check_plan_repeat_gate(plan)
    assert result["passed"] is True
    assert result["issues"] == []


def test_empty_and_unknown_names_skipped():
    plan = {
        "days": [
            _day(1, _stop(""), _stop(None)),
            _day(2, _stop("")),
        ]
    }
    assert check_plan_repeat_gate(plan)["passed"] is True


# ── 三连排去重：同站点连排 3 次只报一次 ──
def test_triple_repeat_reports_once():
    plan = {
        "days": [
            _day(1, _stop("西湖"), _stop("灵隐寺")),
            _day(2, _stop("西湖")),
            _day(3, _stop("西湖")),
        ]
    }
    result = check_plan_repeat_gate(plan)
    assert result["warning_count"] == 1


# ── 混合：同天 + 相邻天 各报 ──
def test_multiple_repeat_pairs():
    plan = {
        "days": [
            _day(1, _stop("西湖"), _stop("西湖"), _stop("灵隐寺")),
            _day(2, _stop("灵隐寺")),
        ]
    }
    result = check_plan_repeat_gate(plan)
    assert result["warning_count"] == 2


# ── 无 day_number 兜底（day_number=0，不崩溃）──
def test_missing_day_number_handled():
    plan = {"days": [{"stops": [_stop("西湖"), _stop("西湖")]}]}
    result = check_plan_repeat_gate(plan)
    assert result["passed"] is False
    assert result["warning_count"] == 1