"""行程时间轴排程（schedule_service）测试：确定性排程器，零 LLM 零网络。

口径（见 openspec/changes/trip-detail-schedule-timeline/design.md D2）：
- 起点：首站显式 visit_start 优先，否则 DAY_START（与 TimeGate 同源，import 复用）；
- 游玩时段：逐站 start → start + estimated_duration_minutes；
- 段间交通：相邻站点均有坐标时用 haversine + 均速估算 gap，缺坐标跳过不编造；
- 住宿站：不按停留时长占时段（720 分钟是过夜语义），渲染为「到店时刻」；
- 跨夜钳制：end > 24:00 钳到 24:00 并置 overflow；全天跨度 > 720 分钟亦 overflow；
- 全部派生值（读取路径注入），不落数据库。
"""

import pytest

from app.services.schedule_service import schedule_day


def _stop(name, stop_type="attraction", **kw):
    return {"id": f"stop-{name}", "name": name, "stop_type": stop_type, **kw}


# ── 正常日：9:00 起点，逐站累加，gap 计算 ──
def test_normal_day_schedule():
    # 三站纵列（每站直线约 5km → gap ≈ 6min，非零可断言）
    stops = [
        _stop("甲", lat=31.0, lng=121.0, estimated_duration_minutes=60),
        _stop("乙", lat=31.05, lng=121.0, estimated_duration_minutes=90),
        _stop("丙", lat=31.1, lng=121.0, estimated_duration_minutes=30),
    ]
    result = schedule_day(stops)
    items = result["items"]
    assert [i["stop_id"] for i in items] == ["stop-甲", "stop-乙", "stop-丙"]
    assert items[0]["start"] == "09:00"
    assert items[0]["end"] == "10:00"
    # 段间 gap 非零、确定性与 prepare：乙 start = 甲 end + gap
    gap01 = items[0]["travel_to_next_minutes"]
    assert gap01 is not None and gap01 > 0
    assert items[1]["start"] == _plus(items[0]["end"], gap01)
    assert items[2]["start"] == _plus(items[1]["end"], items[1]["travel_to_next_minutes"])
    # 末站 travel=null
    assert items[-1]["travel_to_next_minutes"] is None
    # 日窗口：首站 start → 末站 end，无过载
    assert result["window"]["start"] == "09:00"
    assert result["window"]["overflow"] is False


def _plus(hhmm: str, minutes: int) -> str:
    h, m = map(int, hhmm.split(":"))
    total = h * 60 + m + minutes
    return f"{total // 60:02d}:{total % 60:02d}"


# ── 首站显式 visit_start 锚点优先于 9:00 ──
def test_explicit_start_anchor():
    stops = [
        _stop("首站", visit_start="14:00", lat=31.0, lng=121.0, estimated_duration_minutes=60),
        _stop("次站", lat=31.0, lng=121.0, estimated_duration_minutes=60),
    ]
    result = schedule_day(stops)
    assert result["items"][0]["start"] == "14:00"
    assert result["window"]["start"] == "14:00"


# ── 住宿站：不按停留时长占用时段，渲染为到店时刻 ──
def test_hotel_not_occupying_queue():
    stops = [
        _stop("景点", lat=31.0, lng=121.0, estimated_duration_minutes=120),
        _stop("酒店", stop_type="hotel", lat=31.01, lng=121.0, estimated_duration_minutes=720),
    ]
    result = schedule_day(stops)
    items = result["items"]
    hotel = items[1]
    # 酒店停留时长 720 分钟没有吃进时段队列（否则 end 会是次日）
    assert hotel["start"] is not None
    assert hotel["end"] != _plus(hotel["start"], 720)
    # 酒店后的站点从到店时刻顺延，而非「到店 + 720」
    stops2 = [
        _stop("景点", lat=31.0, lng=121.0, estimated_duration_minutes=120),
        _stop("酒店", stop_type="hotel", lat=31.01, lng=121.0, estimated_duration_minutes=720),
        _stop("夜宵", stop_type="food", lat=31.02, lng=121.0, estimated_duration_minutes=60),
    ]
    items2 = schedule_day(stops2)["items"]
    hotel2, late = items2[1], items2[2]
    assert late["start"] == _plus(hotel2["start"], hotel2["travel_to_next_minutes"] or 0)
    # 全天跨度不含 720 分钟（否则必 overflow）
    assert schedule_day(stops2)["window"]["overflow"] is False


# ── 跨夜钳制与 overflow 信号 ──
def test_overflow_crossing_midnight():
    stops = [
        _stop("A", lat=31.0, lng=121.0, estimated_duration_minutes=480),
        _stop("B", lat=31.0, lng=121.0, estimated_duration_minutes=600),
    ]
    result = schedule_day(stops)
    items = result["items"]
    # 9:00 + 480 + gap + 600 > 24:00 → 钳制到 24:00 且 overflow
    assert items[-1]["end"] == "24:00"
    assert result["window"]["overflow"] is True


def test_overflow_span_over_12h():
    # 未跨夜但全天跨度 > 720 分钟：9:00 开始连续游玩 13 小时（780 分钟）
    stops = [_stop("A", lat=31.0, lng=121.0, estimated_duration_minutes=780)]
    result = schedule_day(stops)
    assert result["window"]["overflow"] is True


def test_no_overflow_when_sane():
    stops = [_stop("A", lat=31.0, lng=121.0, estimated_duration_minutes=300)]
    result = schedule_day(stops)
    assert result["window"]["overflow"] is False


# ── 无坐标相邻对：gap 跳过不编造，时刻直接顺延 ──
def test_missing_coords_skips_gap():
    stops = [
        _stop("A", lat=31.0, lng=121.0, estimated_duration_minutes=60),   # end 10:00
        _stop("B", estimated_duration_minutes=60),                        # 无坐标
        _stop("C", lat=31.1, lng=121.0, estimated_duration_minutes=60),
    ]
    result = schedule_day(stops)
    items = result["items"]
    assert items[0]["travel_to_next_minutes"] is None  # 缺坐标不编造
    assert items[1]["start"] == items[0]["end"]
    # B → C：B 也无坐标 → 同样跳过（B 自身 travel 条目未知则 null）
    assert items[1]["travel_to_next_minutes"] is None
    assert items[2]["start"] == items[1]["end"]


# ── 交通占位站：details.is_transfer 与名称兜底两路径 ──
def test_transfer_by_details_flag():
    stops = [
        {"id": "t1", "name": "前往杭州（交通占位）", "stop_type": "attraction",
         "estimated_duration_minutes": 120, "details": {"is_transfer": True},
         "lat": 31.0, "lng": 121.0},
    ]
    result = schedule_day(stops)
    assert result["items"][0]["is_transfer"] is True


def test_transfer_detected_by_name_fallback():
    # 存量行程 details 无 is_transfer，按名称后缀兜底（multi_city 命名稳定出处）
    stops = [
        {"id": "t1", "name": "前往杭州（交通占位）", "stop_type": "attraction",
         "estimated_duration_minutes": 120, "lat": 31.0, "lng": 121.0},
        _stop("西湖", lat=30.9, lng=120.9, estimated_duration_minutes=120),
    ]
    result = schedule_day(stops)
    flags = [i["is_transfer"] for i in result["items"]]
    assert flags == [True, False]


def test_normal_stop_not_transfer():
    stops = [_stop("甲", lat=31.0, lng=121.0, estimated_duration_minutes=60)]
    result = schedule_day(stops)
    assert result["items"][0]["is_transfer"] is False


# ── 空日与缺时长兜底 ──
def test_empty_day():
    result = schedule_day([])
    assert result["items"] == []
    assert result["window"]["overflow"] is False
    assert result["window"]["start"] is None


def test_missing_duration_treated_as_zero():
    stops = [_stop("A", lat=31.0, lng=121.0), _stop("B", lat=31.0, lng=121.0)]
    result = schedule_day(stops)
    items = result["items"]
    # 语义：缺时长不编造游玩时间，start==end（零时长瞬时点）
    assert items[0]["start"] == items[0]["end"]
    assert items[1]["start"] == items[1]["end"]
