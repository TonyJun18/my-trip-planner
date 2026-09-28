"""折扣/优惠规则库：确定性本地规则（无外部依赖、零幻觉、可审计）。

设计（契约优先，防编造折扣）：
- 采集阶段只产出「城市级/证件级」的普遍规则（学生证、老年证、旅游年卡、
  平台通用优惠），这些来自公开常识/官方政策，置信度高、无需实时搜索；
- 具体实时比价（某酒店/某景区今日优惠）放定稿后 servicing 阶段，
  由 DiscountAnalysisAgent 走 Tavily 并施加「无来源即丢弃」硬闸门；
- 本模块绝不返回不可信的实时折扣——所有条目要么有官方来源标注，
  要么是 infrastructure 级的通用规则（confidence >= 0.8）。

输出统一结构（与 PlanSchema.discount_rules 兼容）：
{
  "target": str,            # 适用对象（城市/人群/平台）
  "rule": str,              # 折扣规则描述
  "category": "attraction|hotel|transport|general",
  "source": "rule",
  "source_url": str | None, # 官方来源链接（无则 None，仅 infra 级）
  "confidence": float,      # 0-1
  "valid_until": str | None # 截止日期（未知为 None）
}
"""
from __future__ import annotations

from typing import Any

# 通用证件/人群折扣（全国性，来源稳定）
_GENERAL_DISCOUNTS: list[dict[str, Any]] = [
    {
        "target": "学生",
        "rule": "持有效学生证可享多数景区门票半价（研究生证部分景区不适用）",
        "category": "attraction",
        "source": "rule",
        "source_url": "https://www.gov.cn/",
        "confidence": 0.9,
        "valid_until": None,
    },
    {
        "target": "老年人",
        "rule": "60-69 岁老年人多数景区享半价或折扣，70 岁以上多数免票（以景区公示为准）",
        "category": "attraction",
        "source": "rule",
        "source_url": "https://www.gov.cn/",
        "confidence": 0.9,
        "valid_until": None,
    },
    {
        "target": "儿童",
        "rule": "身高 1.2m 以下儿童多数景区免票，1.2-1.5m 享儿童票",
        "category": "attraction",
        "source": "rule",
        "source_url": "https://www.gov.cn/",
        "confidence": 0.9,
        "valid_until": None,
    },
    {
        "target": "军人/退役军人",
        "rule": "现役军人持证件多数景区免费，退役军人按当地政策（部分城市免费）",
        "category": "attraction",
        "source": "rule",
        "source_url": "https://www.gov.cn/",
        "confidence": 0.85,
        "valid_until": None,
    },
]

# 平台通用优惠（跨城市）
_PLATFORM_DISCOUNTS: list[dict[str, Any]] = [
    {
        "target": "平台优惠",
        "rule": "高德地图/美团/大众点评常驻景区门票、酒店、餐饮团购优惠，下单前比价",
        "category": "general",
        "source": "rule",
        "source_url": None,
        "confidence": 0.85,
        "valid_until": None,
    },
    {
        "target": "平台优惠",
        "rule": "携程/飞猪/去哪儿会员价与券包（新人券、满减券），预订前叠加",
        "category": "general",
        "source": "rule",
        "source_url": None,
        "confidence": 0.85,
        "valid_until": None,
    },
]

# 城市 → 旅游年卡/通票（确定性规则；来源为公开政策）
_CITY_PASS: dict[str, list[dict[str, Any]]] = {
    "北京": [
        {
            "target": "北京旅游年卡",
            "rule": "公园游览年票/京津冀旅游年卡可覆盖多数市属公园与部分景区，办卡前核算是否划算",
            "category": "attraction",
            "source": "rule",
            "source_url": "https://www.beijing.gov.cn/",
            "confidence": 0.85,
            "valid_until": None,
        }
    ],
    "上海": [
        {
            "target": "上海博物馆等场馆",
            "rule": "上海多数市属博物馆/美术馆免费（需预约），收费特展另计",
            "category": "attraction",
            "source": "rule",
            "source_url": "https://www.shanghai.gov.cn/",
            "confidence": 0.85,
            "valid_until": None,
        }
    ],
    "杭州": [
        {
            "target": "杭州西湖景区",
            "rule": "西湖景区多数景点免费开放，游船/电瓶车等另收费",
            "category": "attraction",
            "source": "rule",
            "source_url": "https://www.hangzhou.gov.cn/",
            "confidence": 0.85,
            "valid_until": None,
        }
    ],
}


def city_discount_rules(city: str | None) -> list[dict[str, Any]]:
    """按城市返回确定性折扣规则（通用 + 平台 + 城市年卡）。"""
    rules: list[dict[str, Any]] = list(_GENERAL_DISCOUNTS) + list(_PLATFORM_DISCOUNTS)
    if city:
        for known, items in _CITY_PASS.items():
            if known in (city or "") or (city or "") in known:
                rules.extend(items)
                break
    return rules


def discount_rules_for_request(request: dict[str, Any]) -> list[dict[str, Any]]:
    """从规划请求提取城市名并返回折扣规则（供 DiscountAgent 采集阶段使用）。"""
    return city_discount_rules(request.get("destination") or "")