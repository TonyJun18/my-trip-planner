"""confirmation-batch-import 测试（task-confirmation-batch-import-eval）。

覆盖（对齐 openspec/changes/2026-11-20-confirmation-batch-import/spec.md）：
1. parse_email_batch 分段解析（转发分隔符 / 无分隔符零破坏 / 空段容错）
2. 合并去重（有码同 kind+code / 无码同 kind+name+amount / 非重复保留）
3. source_segment 来源段标注
4. dropped_lines 扩展语义（去重丢弃计数）
5. batch 端点（batch=true 走分段 / batch=false 单条兼容）
"""
from __future__ import annotations

import pytest

from app.services.email_import import parse_email, parse_email_batch

# ── 1. 分段解析 ─────────────────────────────────────────────

_EMAIL_A = """航司确认：CA1234 北京→杭州 2026-12-01 08:00 预订成功
预订号：CA20261201 金额 ¥1200"""

_EMAIL_B = """酒店确认：西湖假日酒店 入住 2026-12-02 退房 2026-12-03
确认号：BK12345678 金额 ¥800"""


def test_batch_split_forwarded_dashed():
    """`--- Forwarded message ---` 分隔两封 → bookings 合并两封条目。"""
    text = (
        "--- Forwarded message ---\n" + _EMAIL_A + "\n"
        "--- Forwarded message ---\n" + _EMAIL_B
    )
    result = parse_email_batch(text)
    kinds = sorted(b.kind for b in result.bookings)
    assert kinds == ["flight", "hotel"]
    # 每段来源标注
    segs = sorted(b.source_segment for b in result.bookings)
    assert segs == [1, 2]


def test_batch_split_forwarded_underscored():
    """`---------- Forwarded message ----------` 变体。"""
    text = (
        "---------- Forwarded message ----------\n" + _EMAIL_B + "\n"
        "---------- Forwarded message ----------\n" + _EMAIL_A
    )
    result = parse_email_batch(text)
    assert len(result.bookings) == 2


def test_batch_no_separator_equals_single():
    """无分隔符 → 与 parse_email 等价（单段零破坏）。"""
    text = _EMAIL_A
    single = parse_email(text)
    batch = parse_email_batch(text)
    assert [b.name for b in batch.bookings] == [b.name for b in single.bookings]
    assert all(b.source_segment == 1 for b in batch.bookings)


def test_batch_empty_segments_tolerated():
    """空段/只有分隔符 → 不报错跳过。"""
    text = "--- Forwarded message ---\n\n--- Forwarded message ---\n" + _EMAIL_A
    result = parse_email_batch(text)
    assert len(result.bookings) == 1


# ── 2. 合并去重 ─────────────────────────────────────────────

def test_batch_dedup_same_code():
    """两封同 kind+code → 只保留一条 + dropped_lines=1。"""
    text = (
        "--- Forwarded message ---\n" + _EMAIL_B + "\n"
        "--- Forwarded message ---\n" + _EMAIL_B
    )
    result = parse_email_batch(text)
    assert len(result.bookings) == 1
    assert result.bookings[0].code == "BK12345678"
    assert result.dropped_lines == 1


def test_batch_dedup_no_code_same_name_amount():
    """无码同 kind+name+amount → 去重。"""
    a = "门票确认：西湖游船 2026-12-05 金额 ¥100"
    b = "门票确认：西湖游船 2026-12-05 金额 ¥100"
    text = f"--- Forwarded message ---\n{a}\n--- Forwarded message ---\n{b}"
    result = parse_email_batch(text)
    # 两封都无码（无确认号）→ name/amount 相同 → 去重留一条
    assert len(result.bookings) == 1
    assert result.dropped_lines == 1


def test_batch_dedup_keeps_different():
    """同 kind 不同 code → 保留两条（不误合）。"""
    b1 = "酒店确认：A酒店 确认号：BK111 金额 ¥800"
    b2 = "酒店确认：B酒店 确认号：BK222 金额 ¥900"
    text = f"--- Forwarded message ---\n{b1}\n--- Forwarded message ---\n{b2}"
    result = parse_email_batch(text)
    assert len(result.bookings) == 2


# ── 3. source_segment 标注 ──────────────────────────────────

def test_batch_source_segment_label():
    """三封 → 来源段 1/2/3。"""
    text = (
        f"--- Forwarded message ---\n{_EMAIL_A}\n"
        f"--- Forwarded message ---\n{_EMAIL_B}\n"
        f"--- Forwarded message ---\n{_EMAIL_B}"
    )
    result = parse_email_batch(text)
    segs = sorted(b.source_segment for b in result.bookings)
    # A 段 1；B 段 2（第三封重复被去重）
    assert segs == [1, 2]


# ── 4. API batch 端点 ───────────────────────────────────────

async def _create_trip(client, headers) -> str:
    resp = await client.post(
        "/api/v1/trips",
        json={
            "title": "批导入行程",
            "destination": "杭州",
            "start_date": "2026-12-01",
            "end_date": "2026-12-05",
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def test_api_batch_true_splits(client, auth_user):
    """batch=true 两封 → 200 合并去重候选 + source_segment。"""
    _, headers = auth_user
    text = f"--- Forwarded message ---\n{_EMAIL_A}\n--- Forwarded message ---\n{_EMAIL_B}"
    resp = await client.post(
        "/api/v1/trips/email/import",
        json={"text": text, "batch": True},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    kinds = sorted(b["kind"] for b in data["bookings"])
    assert kinds == ["flight", "hotel"]
    segs = sorted(b["source_segment"] for b in data["bookings"])
    assert segs == [1, 2]


async def test_api_batch_false_single(client, auth_user):
    """batch=false/缺省 → 与现状一致（无 source_segment 字段亦可）。"""
    _, headers = auth_user
    resp = await client.post(
        "/api/v1/trips/email/import",
        json={"text": _EMAIL_A},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert len(resp.json()["bookings"]) == 1


async def test_api_batch_dedup(client, auth_user):
    """batch=true 重复订单 → 去重 + dropped_lines 计数。"""
    _, headers = auth_user
    text = f"--- Forwarded message ---\n{_EMAIL_B}\n--- Forwarded message ---\n{_EMAIL_B}"
    resp = await client.post(
        "/api/v1/trips/email/import",
        json={"text": text, "batch": True},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert len(data["bookings"]) == 1
    assert data["dropped_lines"] == 1