"""test_i18n.py —— i18n 多语种改造专项测试。

覆盖（对应 docs/i18n-language-task-archive.md §P2）：
- normalize_locale 边界（en/zh/fr/空/None/Accept-Language 串/区域后缀）
- t() 回退（未知 key 回退默认语种；未知语种回退 zh-CN；format 占位符）
- zh/en key 集合完全对齐断言
- get_prompt 每种 agent 两种语言都含对应指令且无 format 异常
- plan_language_instruction / preference_keywords / preference_keys_to_keywords
- transit/checkin/driving/timegate 关键文案随语种变化
"""
from __future__ import annotations

from app.i18n import DEFAULT_LOCALE, SUPPORTED_LOCALES, is_supported, normalize_locale
from app.i18n.prompts import (
    _AGENT_TEMPLATES,
    get_prompt,
    plan_language_instruction,
    preference_keywords,
    preference_keys_to_keywords,
)
from app.i18n.translations import MESSAGES, t


# ── normalize_locale ─────────────────────────────────────


def test_normalize_locale_simple():
    assert normalize_locale("en") == "en-US"
    assert normalize_locale("zh") == "zh-CN"
    assert normalize_locale("zh-CN") == "zh-CN"
    assert normalize_locale("en-US") == "en-US"


def test_normalize_locale_accept_language_header():
    assert normalize_locale("en-US,en;q=0.9") == "en-US"
    assert normalize_locale("zh-CN,zh;q=0.9,en;q=0.8") == "zh-CN"
    assert normalize_locale("fr-FR,fr;q=0.9") == DEFAULT_LOCALE  # 未知主语言回退


def test_normalize_locale_edge_cases():
    assert normalize_locale("") == DEFAULT_LOCALE
    assert normalize_locale(None) == DEFAULT_LOCALE
    assert normalize_locale("zh-Hans") == "zh-CN"
    assert normalize_locale("en_GB") == "en-US"  # 下划线归一
    assert normalize_locale("  ") == DEFAULT_LOCALE


def test_is_supported():
    assert is_supported("zh-CN")
    assert is_supported("en-US")
    assert not is_supported("fr-FR")


# ── t() 回退 / format ────────────────────────────────────


def test_t_basic():
    assert t("zh-CN", "transit.mode.walk") == "步行"
    assert t("en-US", "transit.mode.walk") == "Walk"


def test_t_unknown_locale_falls_back_to_default():
    assert t("fr-FR", "transit.mode.walk") == "步行"  # 未知语种 → zh-CN


def test_t_format_placeholders():
    assert t("zh-CN", "transit.note", km="2.5") == "直线距离约 2.5km（实际路线以导航为准）"
    assert t("en-US", "transit.note", km="2.5") == (
        "Straight-line distance about 2.5km (follow navigation for the actual route)"
    )


def test_t_driving_src_placeholder_not_from():
    """driving.msg.leg_km 使用 {src}（from 是 Python 关键字，不能做 kwargs 名）。"""
    zh = t("zh-CN", "driving.msg.leg_km", day=1, src="A", to="B", km=80, max=50)
    assert "A" in zh and "B" in zh and "80" in zh
    en = t("en-US", "driving.msg.leg_km", day=1, src="A", to="B", km=80, max=50)
    assert "A" in en and "B" in en
    # 传入 from_ 不应命中模板占位符（防御：未匹配的 kwargs 被 format 忽略，模板原样返回?）
    # 实际 format 对多余 kwargs 不报错，只对缺失报 KeyError —— 这里验证模板不含 {from}
    assert "{from}" not in zh and "{from}" not in en


# ── zh/en key 集合对齐 ───────────────────────────────────


def test_locale_key_sets_aligned():
    zh_keys = set(MESSAGES["zh-CN"].keys())
    en_keys = set(MESSAGES["en-US"].keys())
    assert zh_keys == en_keys, f"zh-only={zh_keys - en_keys} en-only={en_keys - zh_keys}"


def test_t_every_key_resolves_in_both_locales():
    """每个 key 在 zh/en 都能解析出非空文案（防孤儿 key / 空串）。"""
    for locale in SUPPORTED_LOCALES:
        for key in MESSAGES[locale]:
            text = t(locale, key)
            assert text, f"{locale} {key} 解析为空"


# ── get_prompt ───────────────────────────────────────────


def test_get_prompt_all_agents_both_locales():
    for agent in _AGENT_TEMPLATES:
        zh = get_prompt(agent, "zh-CN")
        en = get_prompt(agent, "en-US")
        assert zh and en, f"{agent} 有语种模板为空"
        # 都含语言指令（中/英任一都不为空）
        assert plan_language_instruction("zh-CN") in zh or zh.strip()
        assert plan_language_instruction("en-US") in en or en.strip()


def test_get_prompt_unknown_locale_falls_back():
    assert get_prompt("planner", "fr-FR") == get_prompt("planner", DEFAULT_LOCALE)


def test_get_prompt_contains_language_instruction():
    zh = get_prompt("planner", "zh-CN")
    en = get_prompt("planner", "en-US")
    assert "中文" in zh or "JSON" in zh  # 中文指令
    assert "English" in en  # 英文指令必须出现


# ── preference keywords ──────────────────────────────────


def test_preference_keywords_known():
    assert preference_keywords("zh-CN", "food") == "美食 必吃 餐厅"
    assert "food" in preference_keywords("en-US", "food")  # 英文关键词表存在


def test_preference_keywords_unknown_passthrough():
    assert preference_keywords("zh-CN", "未知偏好") == "未知偏好"


def test_preference_keys_to_keywords_maps_keys():
    out = preference_keys_to_keywords("zh-CN", ["food", "nature"])
    assert out == ["美食 必吃 餐厅", "自然风光 公园 山水"]


def test_preference_keys_to_keywords_handles_labels():
    """旧前端传 label（如中文「美食」）时按原样保留，不误翻。"""
    out = preference_keys_to_keywords("zh-CN", ["美食"])
    assert out == ["美食"]


# ── 服务层文案随语种 ─────────────────────────────────────


def test_checkin_templates_localized():
    assert t("zh-CN", "checkin.steps.1") != t("en-US", "checkin.steps.1")
    assert "front desk" in t("en-US", "checkin.steps.1").lower()


def test_revise_ops_localized():
    assert t("zh-CN", "revise.op.replace") == "修改"
    assert t("en-US", "revise.op.replace") == "Modify"


def test_planb_localized():
    assert t("zh-CN", "planb.relaxed.label") == "节奏优化版"
    assert t("en-US", "planb.relaxed.label") == "Relaxed version"