"""task-trip-quality-report-a：质检五类只读聚合报告测试。

覆盖：
- 纯函数 build_quality_report：五类 gate 聚合 / 缺失 gate checked=false /
  issues 压缩 / 空 plan 全未检查 / 汇总统计；
- owner 端点：有 plan 返回五类 gate；无 plan 全 checked=false；
- share 端点：免登录只读 + 生命周期门禁（无效 token 404）+ 不含凭证。
"""
from __future__ import annotations

from datetime import date

from httpx import AsyncClient

from app.models import TripDay, TripPlan
from app.services.quality_report_service import GATE_KEYS, build_quality_report

# ── 纯函数 ─────────────────────────────────────────────────────
class TestBuildQualityReport:
    def test_gates_ordered_and_missing_checked_false(self):
        """五类 gate 顺序固定；缺失 gate → checked=false 且 passed=None。"""
        r = build_quality_report({"quality": {"passed": True, "issues": []}})
        assert [g["key"] for g in r["gates"]] == list(GATE_KEYS)
        assert r["checked_gates"] == 1
        assert r["passed_gates"] == 1
        assert r["total_issues"] == 0
        q = r["gates"][0]
        assert q["checked"] is True
        assert q["passed"] is True
        assert q["title_key"] == "qualityReport.gate.quality"
        # 缺失 gate 不编造通过
        for g in r["gates"][1:]:
            assert g["checked"] is False
            assert g["passed"] is None

    def test_counts_issues_across_gates(self):
        """跨 gate 汇总 issue 数；warning_count=issues 长度。"""
        r = build_quality_report({
            "time_gate": {"passed": False, "issues": [{"severity": "warning"}, {"severity": "warning"}]},
            "repeat_gate": {"passed": False, "issues": [{"severity": "warning"}]},
            "weather_gate": {"passed": True, "issues": []},
        })
        assert r["checked_gates"] == 3
        assert r["passed_gates"] == 1
        assert r["total_issues"] == 3
        by_key = {g["key"]: g for g in r["gates"]}
        assert by_key["time_gate"]["warning_count"] == 2
        assert by_key["repeat_gate"]["warning_count"] == 1

    def test_empty_plan_all_unchecked(self):
        """plan_data=None / {}（未规划）→ 全部 checked=false，绝不假装查过。"""
        for data in (None, {}):
            r = build_quality_report(data)
            assert r["checked_gates"] == 0
            assert r["passed_gates"] == 0
            assert r["total_issues"] == 0
            for g in r["gates"]:
                assert g["checked"] is False

    def test_issues_capped_and_summary_passthrough(self):
        """issues 上限 20；summary/basis/score 透传。"""
        issues = [{"severity": "warning", "message": f"i{i}"} for i in range(25)]
        r = build_quality_report({"quality": {
            "passed": False, "score": 55, "summary": "需修订",
            "basis": "llm", "issues": issues,
        }})
        q = r["gates"][0]
        assert len(q["issues"]) == 20
        assert q["score"] == 55
        assert q["summary"] == "需修订"
        assert q["basis"] == "llm"


# ── API 测试 ───────────────────────────────────────────────────
async def _make_planned_trip(client: AsyncClient, headers: dict, *, title: str) -> str:
    resp = await client.post("/api/v1/trips", headers=headers, json={
        "title": title, "destination": "杭州", "departure": "上海",
        "start_date": "2026-11-20", "end_date": "2026-11-21", "travelers": 1,
    })
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


class TestQualityReportApi:
    async def test_owner_report_with_plan(self, client: AsyncClient, auth_user, db_session):
        """有 plan → 返回五类 gate；quality/time_gate/repeat_gate 来自快照。"""
        _user, headers = auth_user
        trip_id = await _make_planned_trip(client, headers, title="质检报告")
        # 直接落一个 plan 快照（含五类 gate）——必须先 commit，client 的独立 session 才可见
        db_session.add(TripPlan(
            trip_id=trip_id,
            plan_data={
                "destination": "杭州",
                "days": [],
                "quality": {"score": 92, "passed": True, "issues": [], "basis": "llm"},
                "time_gate": {"passed": False, "issues": [{"severity": "warning", "message": "闭馆"}]},
                "repeat_gate": {"passed": True, "issues": []},
            },
            provider="deepseek", model="dummy",
        ))
        await db_session.commit()

        resp = await client.get(f"/api/v1/trips/{trip_id}/quality-report", headers=headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["checked_gates"] == 3
        assert body["total_issues"] == 1
        by_key = {g["key"]: g for g in body["gates"]}
        assert by_key["quality"]["score"] == 92
        assert by_key["repeat_gate"]["passed"] is True
        assert by_key["time_gate"]["issues"][0]["message"] == "闭馆"

    async def test_owner_report_without_plan(self, client: AsyncClient, auth_user):
        """无 plan → 全部 checked=false（未规划不假装查过）。"""
        _user, headers = auth_user
        trip_id = await _make_planned_trip(client, headers, title="无方案")
        resp = await client.get(f"/api/v1/trips/{trip_id}/quality-report", headers=headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["checked_gates"] == 0
        for g in body["gates"]:
            assert g["checked"] is False

    async def test_owner_isolated(self, client: AsyncClient, auth_user):
        """他人 token 查报告 → 404（行程不可见）。"""
        _user, headers = auth_user
        trip_id = await _make_planned_trip(client, headers, title="隔离")
        import uuid
        resp = await client.post(
            "/api/v1/auth/register",
            json={"email": f"other-{uuid.uuid4().hex[:8]}@test.com",
                  "password": "test1234", "display_name": "他人"},
        )
        other_headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
        resp = await client.get(f"/api/v1/trips/{trip_id}/quality-report", headers=other_headers)
        assert resp.status_code == 404, resp.text

    async def test_share_path_readonly(self, client: AsyncClient, auth_user, db_session):
        """分享路径：免登录只读五类 gate；不暴露任何凭证。"""
        _user, headers = auth_user
        trip_id = await _make_planned_trip(client, headers, title="分享质检")
        db_session.add(TripPlan(
            trip_id=trip_id,
            plan_data={
                "destination": "杭州",
                "days": [],
                "quality": {"passed": False, "issues": [{"severity": "critical", "message": "x"}]},
                "repeat_gate": {"passed": False, "issues": [{"severity": "warning", "message": "重复"}]},
            },
            provider="deepseek", model="dummy",
        ))
        await db_session.commit()

        resp = await client.post(f"/api/v1/trips/{trip_id}/share", headers=headers)
        token = resp.json()["share_token"]
        resp = await client.get(f"/api/v1/trips/share/{token}/quality-report")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["checked_gates"] == 2
        assert body["total_issues"] == 2
        # 序列化后绝不含凭证键
        raw = resp.text
        assert "credential" not in raw and "order_no" not in raw

    async def test_share_invalid_token_404(self, client: AsyncClient, auth_user):
        """无效分享令牌 → 404（生命周期门禁一致）。"""
        resp = await client.get("/api/v1/trips/share/bad-token/quality-report")
        assert resp.status_code == 404, resp.text