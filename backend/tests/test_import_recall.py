"""task-import-recall-benchmark：导入召回率（recall）回归基准测试。

背景（docs/night-build-todo.md 2026-11-10 竞品分析追加）：
- Plotline 12 地点 TikTok 公开测试把「导入可靠性」变成可比指标
  （Wanderlog 漏 2/12 vs Plotline 全命中）；
- 我们五通道导入（note / social / email / link / screenshot）各有功能测试，
  但无统一的召回基线。

本基准：
- 固定样本（tests/import_recall_samples.py）：中文攻略 10 地点、英文攻略
  10 地点、中文社交 caption 6 地点、中文预订邮件 3 候选；
- 断言：中文通道召回阈值（防回归），英文通道上限断言（防候选爆炸
  式虚假召回；英文地点规则是已知差距，见评估记录）；
- 零凭证、纯规则、确定性：同一输入永远同一输出。

2026-11-10 首建基线：NOTE_ZH=1.0 / NOTE_EN=0.0（已知差距）/
SOCIAL_ZH=1.0 / EMAIL_ZH=1.0。
"""
from __future__ import annotations

from app.services.email_import import parse_email
from app.services.note_import import parse_note
from app.services.social_import import parse_social
from tests.import_recall_samples import (
    EMAIL_ZH,
    EMAIL_ZH_GROUND_TRUTH,
    NOTE_EN,
    NOTE_EN_GROUND_TRUTH,
    NOTE_ZH,
    NOTE_ZH_GROUND_TRUTH,
    SOCIAL_ZH,
    SOCIAL_ZH_GROUND_TRUTH,
    recall_at,
)


class TestNoteRecall:
    def test_note_zh_recall_above_threshold(self):
        """中文攻略 10 地点：召回 ≥ 0.9（防回归；2026-11-10 实测 1.0）。"""
        r = parse_note(NOTE_ZH)
        recall, hits, missed = recall_at(r.candidates, NOTE_ZH_GROUND_TRUTH)
        assert recall >= 0.9, f"中文攻略召回 {recall:.2f}，漏检：{missed}"

    def test_note_zh_metadata_extracted(self):
        """中文攻略样本的元数据（价格/时长）同样不回归。"""
        r = parse_note(NOTE_ZH)
        by_name = {c.name: c for c in r.candidates}
        assert by_name["灵隐寺"].estimated_cost == 75.0
        assert by_name["灵隐寺"].estimated_duration_minutes == 120
        assert by_name["千岛湖"].estimated_duration_minutes == 480

    def test_note_en_recall_upper_bound(self):
        """英文攻略 10 地点：召回 ≤ 0.3（已知差距：规则引擎仅中文地名收尾词）。

        2026-11-10 实测 0/10——诚实记录，不作为「通过」指标；上限断言防
        未来规则退化导致候选爆炸、误命中英文地名造成虚假召回。
        英文地点规则落地后，把本断言升级为下限阈值。
        """
        r = parse_note(NOTE_EN)
        recall, hits, missed = recall_at(r.candidates, NOTE_EN_GROUND_TRUTH)
        assert recall <= 0.3, (
            f"英文攻略召回异常升高 {recall:.2f}（命中 {hits}）——"
            "当前英文地名规则未实现，高召回意味着候选爆炸，请核查"
        )


class TestSocialRecall:
    def test_social_zh_recall_above_threshold(self):
        """中文社交 caption 6 地点：召回 ≥ 0.9（防回归；2026-11-10 实测 1.0）。"""
        r = parse_social(SOCIAL_ZH)
        recall, hits, missed = recall_at(r.candidates, SOCIAL_ZH_GROUND_TRUTH)
        assert recall >= 0.9, f"社交 caption 召回 {recall:.2f}，漏检：{missed}"

    def test_social_zh_no_url_candidates(self):
        """链接不产生候选（仅识别平台）。"""
        r = parse_social(SOCIAL_ZH)
        assert not any("xiaohongshu" in c.name for c in r.candidates)
        assert r.source_platform == "xiaohongshu"


class TestEmailRecall:
    def test_email_zh_recall_above_threshold(self):
        """中文预订确认邮件 3 候选：召回 ≥ 0.9（防回归；2026-11-10 实测 1.0）。"""
        r = parse_email(EMAIL_ZH)
        recall, hits, missed = recall_at(r.candidates, EMAIL_ZH_GROUND_TRUTH)
        assert recall >= 0.9, f"邮件候选召回 {recall:.2f}，漏检：{missed}"

    def test_email_zh_bookings_structured(self):
        """预订条目结构化字段不回归（候选之外的条目主链路）。"""
        r = parse_email(EMAIL_ZH)
        hotels = [b for b in r.bookings if b.kind == "hotel"]
        names = [b.name for b in hotels]
        assert "杭州西湖大酒店" in names
        assert "西溪宾馆" in names
        hz = next(b for b in hotels if b.name == "杭州西湖大酒店")
        assert hz.code == "HZ20261101"
        assert hz.amount == 1280.0
        assert hz.currency == "CNY"
        assert hz.datetime == "2026-11-20"