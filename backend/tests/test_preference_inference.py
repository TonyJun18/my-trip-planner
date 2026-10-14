"""task-preference-inference：偏好推理（行为记忆 → 稳定偏好）测试。

覆盖：
1. infer_preferences 规则引擎：节奏提示（relaxed/compact）、回避清单、类型偏好、
   高频目的地、数据不足返回空
2. inferred_to_text：注入文本含「系统推断」标注、不上屏裸信号
3. ensure_inferred：懒计算 + 签名（行为记忆不变不重算，变化重算）
4. profile_for_request：声明画像 + 推断段合并注入；无画像/无信号时不注入
5. PlanRequest.pace 字段 + _pace_constraint 三档约束
"""
from __future__ import annotations

from datetime import date

import pytest

from app.models import User, UserProfile
from app.schemas import PlanRequest, PlanQuestion


def _mem(*signals: dict) -> dict:
    """构造行为记忆 JSON（带 updated_at 签名）。"""
    return {"signals": list(signals), "updated_at": "2026-10-14T00:00:00+00:00"}


def _sig(kind: str, dest: str, summary: str) -> dict:
    return {"kind": kind, "destination": dest, "summary": summary}


async def _make_user_profile(db_session, user_id: str, **kwargs) -> UserProfile:
    """测试 helper：先建 User（满足外键）再建 UserProfile。"""
    db_session.add(User(id=user_id, email=f"{user_id}@test.com"))
    await db_session.flush()
    profile = UserProfile(user_id=user_id, **kwargs)
    db_session.add(profile)
    return profile


# ── 1. 规则引擎 ────────────────────────────────────────────────
class TestInferPreferences:
    def test_relaxed_pace_from_repeated_shortening(self):
        from app.services.preference_service import infer_preferences

        result = infer_preferences(_mem(
            _sig("revise", "杭州", "西湖只留半天，太赶了"),
            _sig("revise", "杭州", "灵隐寺时间缩短"),
        ))
        assert result.get("pace_hint") == "relaxed"
        assert result.get("source") == "rule_based"

    def test_compact_pace_from_adding_more(self):
        from app.services.preference_service import infer_preferences

        result = infer_preferences(_mem(
            _sig("revise", "杭州", "再加两个景点，太松了"),
            _sig("revise", "杭州", "把晚上也排满"),
        ))
        assert result.get("pace_hint") == "compact"

    def test_single_signal_not_enough_for_pace(self):
        from app.services.preference_service import infer_preferences

        result = infer_preferences(_mem(
            _sig("revise", "杭州", "西湖只留半天"),
        ))
        assert "pace_hint" not in result  # 单次不泛化

    def test_avoid_from_removals(self):
        from app.services.preference_service import infer_preferences

        result = infer_preferences(_mem(
            _sig("manual_remove", "杭州", "删除 雷峰塔"),
            _sig("manual_remove", "杭州", "删掉 灵隐寺"),
        ))
        assert "雷峰塔" in result.get("avoid", [])
        assert "灵隐寺" in result.get("avoid", [])

    def test_type_preference_from_repeated_adds(self):
        from app.services.preference_service import infer_preferences

        result = infer_preferences(_mem(
            _sig("manual_add", "上海", "新增 楼外楼 餐厅"),
            _sig("manual_add", "上海", "加 知味观 美食"),
        ))
        types = [p["type"] for p in result.get("preferences", [])]
        assert "food" in types

    def test_favorite_cities_from_frequency(self):
        from app.services.preference_service import infer_preferences

        result = infer_preferences(_mem(
            _sig("revise", "杭州", "改西湖"),
            _sig("revise", "杭州", "删雷峰塔"),
            _sig("revise", "上海", "加外滩"),
        ))
        assert result.get("favorite_cities") == ["杭州"]  # ≥2 次才入选

    def test_empty_when_no_signals(self):
        from app.services.preference_service import infer_preferences

        assert infer_preferences(None) == {}
        assert infer_preferences({}) == {}
        assert infer_preferences({"signals": []}) == {}


# ── 2. 注入文本 ─────────────────────────────────────────────────
class TestInferredToText:
    def test_labels_as_system_inference(self):
        from app.services.preference_service import inferred_to_text

        text = inferred_to_text({
            "pace_hint": "relaxed",
            "preferences": [{"type": "food", "reason": "常添加餐厅"}],
            "avoid": ["雷峰塔"],
        })
        assert "系统推断" in text
        assert "松弛" in text
        assert "美食" in text
        assert "雷峰塔" in text

    def test_empty_for_no_inference(self):
        from app.services.preference_service import inferred_to_text

        assert inferred_to_text(None) == ""
        assert inferred_to_text({}) == ""


# ── 3. ensure_inferred 懒计算 + 签名 ────────────────────────────
class TestEnsureInferred:
    async def test_recomputes_on_memory_change(self, db_session):
        from app.services.preference_service import ensure_inferred

        profile = await _make_user_profile(db_session, "u-inf-1",
            behavior_memory_json=_mem(_sig("revise", "杭州", "西湖留半天，太赶了")))
        await db_session.flush()

        first = ensure_inferred(db_session, profile)
        assert first.get("pace_hint") is None  # 单信号不足

        # 行为记忆变化（新增信号 + updated_at 变化）→ 重算
        profile.behavior_memory_json = _mem(
            _sig("revise", "杭州", "西湖留半天，太赶了"),
            _sig("revise", "杭州", "灵隐寺缩短"),
            _sig("manual_remove", "杭州", "删除 雷峰塔"),
        )
        second = ensure_inferred(db_session, profile)
        assert second.get("pace_hint") == "relaxed"
        assert "雷峰塔" in second.get("avoid", [])

    async def test_keeps_result_when_signature_unchanged(self, db_session):
        from app.services.preference_service import ensure_inferred

        profile = await _make_user_profile(db_session, "u-inf-2",
            behavior_memory_json=_mem(
                _sig("revise", "杭州", "西湖留半天，太赶了"),
                _sig("revise", "杭州", "灵隐寺缩短"),
            ))
        await db_session.flush()

        first = ensure_inferred(db_session, profile)
        assert first.get("pace_hint") == "relaxed"
        # 同一签名再次调用 → 不重算（直接复用）
        second = ensure_inferred(db_session, profile)
        assert second is first

    async def test_no_profile_no_inference(self, db_session):
        from app.services.preference_service import ensure_inferred

        profile = await _make_user_profile(db_session, "u-inf-3")
        await db_session.flush()
        assert ensure_inferred(db_session, profile) == {}


# ── 4. profile_for_request 注入 ────────────────────────────────
class TestProfileForRequestInjection:
    async def test_merges_declared_and_inferred(self, db_session):
        from app.services import profile_service, preference_service

        profile = await _make_user_profile(db_session, "u-prf-1",
            traveler_type="情侣", pace="慢节奏",
            behavior_memory_json=_mem(
                _sig("revise", "杭州", "西湖留半天，太赶了"),
                _sig("revise", "杭州", "灵隐寺缩短"),
            ))
        await db_session.flush()

        ctx = await profile_service.profile_for_request(db_session, user_id="u-prf-1")
        assert "情侣" in ctx["profile_text"]
        assert "系统推断" in ctx["profile_text"]
        assert "松弛" in ctx["profile_text"]
        # 声明段在推断段之前
        assert ctx["profile_text"].index("跨会话用户画像") < ctx["profile_text"].index("系统推断")

    async def test_empty_without_profile(self, db_session):
        from app.services import profile_service

        ctx = await profile_service.profile_for_request(db_session, user_id="u-prf-none")
        assert ctx["profile_text"] == ""

    async def test_only_declared_when_no_signals(self, db_session):
        from app.services import profile_service

        profile = await _make_user_profile(db_session, "u-prf-2", traveler_type="亲子")
        await db_session.flush()

        ctx = await profile_service.profile_for_request(db_session, user_id="u-prf-2")
        assert "亲子" in ctx["profile_text"]
        assert "系统推断" not in ctx["profile_text"]


# ── 5. PlanRequest.pace + _pace_constraint ──────────────────────
class TestPaceFieldAndConstraint:
    def test_pace_field_parses(self):
        req = PlanRequest(
            destination="杭州",
            start_date=date(2026, 10, 1),
            end_date=date(2026, 10, 3),
            pace="relaxed",
        )
        assert req.pace == "relaxed"

    def test_pace_optional_default_none(self):
        req = PlanRequest(destination="杭州", start_date=date(2026, 10, 1), end_date=date(2026, 10, 3))
        assert req.pace is None

    def test_pace_invalid_rejected(self):
        with pytest.raises(Exception):
            PlanRequest(
                destination="杭州",
                start_date=date(2026, 10, 1),
                end_date=date(2026, 10, 3),
                **{"pace": "insane"},
            )

    def test_questions_with_pace(self):
        req = PlanRequest(
            destination="杭州",
            start_date=date(2026, 10, 1),
            end_date=date(2026, 10, 3),
            pace="compact",
            questions=[PlanQuestion(question="人群？", answer="情侣")],
        )
        assert req.questions[0].answer == "情侣"

    def test_constraint_texts(self):
        from app.agent.agents import _pace_constraint

        assert "4-5 个站点" in _pace_constraint("compact")
        assert "480 分钟" in _pace_constraint("compact")
        assert "2-3 个" in _pace_constraint("relaxed")
        assert "留白" in _pace_constraint("relaxed")
        assert _pace_constraint("balanced") == ""  # 默认档不注入噪音
        assert _pace_constraint(None) == ""

    def test_pace_injected_into_planner_context(self):
        from app.agent import agents

        text = agents._planner_user_text({"destination": "杭州", "pace": "relaxed"}, {})
        assert "【节奏档约束】" in text
        assert "松弛" in text

    def test_no_pace_no_constraint(self):
        from app.agent import agents

        text = agents._planner_user_text({"destination": "杭州"}, {})
        assert "节奏档约束" not in text