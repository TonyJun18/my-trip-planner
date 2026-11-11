"""planning_service 落库 details 白名单测试（task: trip-detail-schedule-timeline）。

口径（openspec specs trip-schedule-timeline：交通占位站识别）：
- multi_city 占位站 plan JSON 的 is_transfer 随落库持久化到 Stop.details，
  读取路径（schedule_service）据此识别交通占位语义；
- 既有白名单键（source/source_url/address/geo/rating）不变。
"""

from app.services.planning_service import _stop_details


def test_details_whitelist_keeps_transfer_flag():
    stop = {"is_transfer": True, "rating": 4.5, "source": "amap"}
    assert _stop_details(stop) == {"is_transfer": True, "rating": 4.5, "source": "amap"}


def test_details_whitelist_ignores_unknown_keys():
    stop = {"is_transfer": True, "hack_field": "x", "duration_minutes": 120}
    assert "hack_field" not in _stop_details(stop)
    assert "duration_minutes" not in _stop_details(stop)


def test_details_none_when_nothing_persistable():
    assert _stop_details({"duration_minutes": 60}) is None
