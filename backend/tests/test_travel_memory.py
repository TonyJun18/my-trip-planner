"""task-travel-memory-feedback（方案 B）：行程行为记忆 测试。

覆盖：
1. _record_behavior：无意义行为不写（noise 过滤：reorder/空变更/空摘要）
2. _record_behavior + _summarize_behaviors：行为累计汇总
3. profile_to_context：合并行为记忆段（来源标注 + 系统观察说明）
4. 触点回写：revise_trip 修订后写行为信号；update_stop 手动编辑后写行为信号
5. 行为记忆不进 ProfileIn/ProfileOut（用户声明与系统观察分离，手动 upsert 不覆盖）
"""
from __future__ import annotations

import json

from sqlalchemy import select

from app.models import User, UserProfile


async def _make_user_profile(db_session, user_id: str, **kwargs) -> UserProfile:
    """测试 helper：先建 User（满足外键）再建 UserProfile，返回 profile。"""
    db_session.add(User(id=user_id, email=f"{user_id}@test.com"))
    # 必须分两次 flush：同批 flush 时 UOW 按 mapper 注册顺序插入，
    # UserProfile 可能先于 User 落库而违反外键。
    await db_session.flush()
    profile = UserProfile(user_id=user_id, **kwargs)
    db_session.add(profile)
    return profile


# ── 1. _record_behavior：noise 过滤 ─────────────────────────────
class TestRecordBehavior:
    async def test_noise_actions_not_recorded(self, db_session):
        """reorder / 空 actions / 空 summary 都不该写入行为记忆。"""
        from app.services import profile_service

        profile = await _make_user_profile(db_session, "u-noise", favorite_cities=["杭州"])
        await db_session.flush()

        await profile_service._record_behavior(
            db_session, user_id="u-noise", signal_kind="revise",
            destination="杭州", actions=[{"op": "reorder"}], summary="仅调整顺序",
        )
        await db_session.commit()

        # 没产生任何有效行为信号 → 不落库、不创建行为记忆
        await db_session.refresh(profile)
        assert profile.behavior_memory_json is None

    async def test_meaningful_actions_recorded(self, db_session):
        """replace 一个 attraction 时长 → 记录一条修正信号。"""
        from app.services import profile_service

        profile = await _make_user_profile(db_session, "u-meaning", favorite_cities=["杭州"])
        await db_session.flush()

        await profile_service._record_behavior(
            db_session, user_id="u-meaning", signal_kind="revise",
            destination="杭州",
            actions=[{"op": "replace", "target": {"name": "西湖"}, "fields": {"estimated_duration_minutes": 90}}],
            summary="西湖只留半天",
        )
        await db_session.commit()

        await db_session.refresh(profile)
        mem = profile.behavior_memory_json
        assert mem is not None
        assert mem["signals"][0]["destination"] == "杭州"  # destination 存在 signal 内
        assert mem["signals"][0]["kind"] == "revise"
        assert mem["signals"][0]["summary"] == "西湖只留半天"

    async def test_upsert_profile_does_not_wipe_behavior(self, db_session):
        """用户 PUT 声明画像不应覆盖系统观察记忆（两者分离）。"""
        from app.schemas.profile import ProfileIn
        from app.services import profile_service

        profile = await _make_user_profile(db_session, "u-keep", favorite_cities=["上海"])
        await db_session.flush()
        await profile_service._record_behavior(
            db_session, user_id="u-keep", signal_kind="revise",
            destination="杭州", actions=[{"op": "replace", "target": {"name": "西湖"}, "fields": {}}],
            summary="改西湖",
        )
        await db_session.commit()

        await profile_service.upsert_profile(
            db_session, user_id="u-keep",
            data=ProfileIn(traveler_type="亲子", favorite_cities=["杭州"]),
        )
        await db_session.commit()

        await db_session.refresh(profile)
        assert profile.behavior_memory_json is not None, "手动 PUT 不应清掉行为记忆"
        assert profile.behavior_memory_json["signals"][0]["summary"] == "改西湖"


# ── 2. 行为累计汇总 ─────────────────────────────────────────────
class TestSummarizeBehaviors:
    async def test_summary_merges_and_counts(self, db_session):
        """多条信号按 destination 聚合：去过城市去重、节奏修正计数。"""
        from app.services import profile_service

        profile = await _make_user_profile(db_session, "u-sum", favorite_cities=[])
        await db_session.flush()

        for dest, actions, summary in [
            ("杭州", [{"op": "replace", "fields": {"estimated_duration_minutes": 90}}], "西湖半天"),
            ("杭州", [{"op": "remove", "target": {"name": "雷峰塔"}}], "删掉雷峰塔"),
            ("上海", [{"op": "add", "fields": {"name": "外滩"}}], "加外滩"),
        ]:
            await profile_service._record_behavior(
                db_session, user_id="u-sum", signal_kind="revise",
                destination=dest, actions=actions, summary=summary,
            )
        await db_session.commit()

        await db_session.refresh(profile)
        text = profile_service.profile_to_context(profile)
        assert "系统观察" in text  # 明确标注来源
        assert "杭州" in text
        assert "上海" in text


# ── 3. 画像上下文合并 ───────────────────────────────────────────
class TestProfileContextMerge:
    async def test_behavior_merged_after_declared(self, db_session):
        """行为记忆段出现在声明画像之后，标注系统观察。"""
        from app.services import profile_service

        profile = await _make_user_profile(db_session, "u-merge", traveler_type="亲子", pace="慢节奏",
            favorite_cities=["杭州"], behavior_memory_json={
                "signals": [{"kind": "revise", "destination": "杭州", "summary": "西湖留半天"}],
            })
        await db_session.flush()

        text = profile_service.profile_to_context(profile)
        assert text.index("跨会话用户画像") < text.index("系统观察"), "声明画像在前、系统观察在后"
        # 契约：行为记忆以「归纳摘要」形式注入（去过城市/节奏/删除信号），
        # 不透出原始 signal 全文（摘要器设计意图，见 _summarize_behaviors docstring）
        assert "近期规划/修订过的城市：杭州" in text


# ── 4. 触点回写（端到端，API → service → 行为记忆） ────────────────────
def _make_dummy_provider():
    """FakeProvider：让 PlanReviseAgent 走假的 _DummyReviseLLM（返回固定 revise diff）。"""
    import json as _json
    from langchain_core.messages import AIMessage

    class _DummyReviseLLM:
        _llm_type = "dummy-revise"

        def bind_tools(self, tools, **kwargs):
            return self

        async def ainvoke(self, messages):
            return AIMessage(content=_json.dumps({
                "actions": [
                    {"op": "replace", "day_number": 1,
                     "target": {"name": "西湖"},
                     "fields": {"description": "半日西湖"}},
                ],
                "summary": "西湖改为半天",
            }, ensure_ascii=False))

    class _DummyProvider:
        name = "deepseek"
        model_id = "dummy-revise-model"

        def __init__(self):
            self._llm = _DummyReviseLLM()

        def get_chat_model(self, temperature=0.2):
            return self._llm

    from app.agent.providers import PROVIDER_REGISTRY
    PROVIDER_REGISTRY["deepseek"] = _DummyProvider()  # type: ignore[assignment]
    return "deepseek"


async def _make_trip_v2(client, headers):
    """建杭州行程 + Day1 + 两个站点，返回 (trip_id, day_id, stop_ids)。"""
    from datetime import date

    today = date.today()
    resp = await client.post("/api/v1/trips", json={
        "title": "杭州之行", "destination": "杭州",
        "start_date": today.isoformat(), "end_date": today.isoformat(),
        "travelers": 1, "budget": 1000,
    }, headers=headers)
    assert resp.status_code == 201, resp.text
    trip_id = resp.json()["id"]
    resp = await client.post(f"/api/v1/trips/{trip_id}/days", json={"day_number": 1}, headers=headers)
    assert resp.status_code == 201, resp.text
    day_id = resp.json()["id"]
    stop_ids = []
    for i, name in enumerate(("西湖", "楼外楼"), start=1):
        r = await client.post(f"/api/v1/trips/days/{day_id}/stops", json={
            "name": name, "stop_type": "attraction" if i % 2 else "food",
            "estimated_cost": 50, "estimated_duration_minutes": 120,
        }, headers=headers)
        assert r.status_code == 201, r.text
        stop_ids.append(r.json()["id"])
    return trip_id, day_id, stop_ids


async def _make_profile(client, auth_user, db_session):
    """注册用户并创建画像（_record_behavior 只在已有画像时写），返回 (user_info, headers)。"""
    from app.models import UserProfile

    user_info, headers = auth_user
    db_session.add(UserProfile(user_id=user_info["id"], favorite_cities=[]))
    await db_session.commit()
    return user_info, headers


async def test_revise_records_behavior(client, auth_user, db_session, monkeypatch):
    """修订成功 → 用户画像行为记忆出现 revise 信号（成功路径端到端）。"""
    from app.agent import agents as agents_mod
    from app.models import UserProfile

    user_info, headers = await _make_profile(client, auth_user, db_session)
    trip_id, _, _ = await _make_trip_v2(client, headers)

    provider_name = _make_dummy_provider()

    async def _pass_critic(request, plan, *, provider="auto", max_corrections=2):
        return {"status": "completed", "critique": {"score": 92, "passed": True, "issues": [], "summary": "ok"}, "corrections": 0}

    monkeypatch.setattr(agents_mod, "revise_critic_agent", _pass_critic)

    resp = await client.post(
        f"/api/v1/trips/{trip_id}/revise",
        json={"message": "西湖只留半天", "provider": provider_name},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text

    profile = (await db_session.execute(
        select(UserProfile).where(UserProfile.user_id == user_info["id"])
    )).scalar_one()
    mem = profile.behavior_memory_json
    assert mem and mem["signals"], "修订成功后应写入行为记忆"
    sig = mem["signals"][-1]
    assert sig["kind"] == "revise"
    assert sig["destination"] == "杭州"
    assert "西湖" in sig["summary"]


async def test_manual_stop_edits_record_behavior(client, auth_user, db_session):
    """add / update / delete 站点 → 行为记忆出现对应 manual 信号；reorder 不写。"""
    from app.models import UserProfile

    user_info, headers = await _make_profile(client, auth_user, db_session)
    _, day_id, (stop_a, stop_b) = await _make_trip_v2(client, headers)

    # add（捕获 id，供后续 reorder 全量校验用）
    r = await client.post(f"/api/v1/trips/days/{day_id}/stops",
                          json={"name": "灵隐寺", "stop_type": "attraction"}, headers=headers)
    assert r.status_code == 201, r.text
    stop_c = r.json()["id"]

    # update（改时长）
    r = await client.patch(f"/api/v1/trips/days/{day_id}/stops/{stop_a}",
                           json={"estimated_duration_minutes": 60}, headers=headers)
    assert r.status_code == 200, r.text

    # delete 楼外楼
    r = await client.delete(f"/api/v1/trips/days/{day_id}/stops/{stop_b}", headers=headers)
    assert r.status_code == 204, r.text

    # reorder（此时站点=西湖 stop_a、灵隐寺 stop_c 共 2 个，全量顺序 → noise，不应写信号）
    r = await client.put(f"/api/v1/trips/days/{day_id}/stops/order",
                         json={"order": [stop_a, stop_c]}, headers=headers)
    assert r.status_code == 200, r.text

    profile = (await db_session.execute(
        select(UserProfile).where(UserProfile.user_id == user_info["id"])
    )).scalar_one()
    signals = (profile.behavior_memory_json or {}).get("signals") or []
    kinds = [s["kind"] for s in signals]
    # 触点语义：新增/编辑/删除都会记录；建行程时的初始站点也是 add（合理）。
    # 断言关键信号存在，且 reorder 不产生任何信号（noise 过滤）。
    assert "manual_add" in kinds, kinds
    assert "manual_edit" in kinds, kinds
    assert "manual_remove" in kinds, kinds
    assert "manual_reorder" not in kinds, kinds
    summaries = [s["summary"] for s in signals]
    assert any("灵隐寺" in s and "新增" in s for s in summaries), summaries
    assert any("西湖" in s and "编辑" in s for s in summaries), summaries
    assert any("楼外楼" in s and "删除" in s for s in summaries), summaries


# ── 5. 行为记忆不进 ProfileIn/Out ───────────────────────────────
def test_behavior_not_in_profile_schema():
    from app.schemas.profile import ProfileIn, ProfileOut

    assert "behavior_memory_json" not in ProfileIn.model_fields
    assert "behavior_memory_json" not in ProfileOut.model_fields