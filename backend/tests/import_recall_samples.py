"""导入召回率评测基准样本（task-import-recall-benchmark）。

目的：把「导入可靠性」变成可比指标——Plotline 12 地点 TikTok 公开测试
全命中 vs Wanderlog 漏 2/12，我们五通道导入也应有统一召回基线。

样本设计（固定、公开、可回归）：
- NOTE_ZH：典型中文攻略（序号 + 地点 + 描述），10 个已知地点
- NOTE_EN：典型英文攻略（序号 + 地点 + 描述），10 个已知地点（英文地名识别为已知差距）
- SOCIAL_ZH：中文社交 caption（口语噪声 + emoji + 链接），6 个已知地点
- EMAIL_ZH：中文预订确认邮件（酒店 ×2 + 活动 ×1），3 个已知候选名

匹配口径：归一化（去空白 + 小写）后双向子串包含，长度容差 ±4 字，
避免「杭州西湖大酒店」误命中「西湖」这类偏颇。
"""
from __future__ import annotations

# ── 中文攻略样本（note_import 主通道） ─────────────────────────────
NOTE_ZH = """杭州三日游攻略：
1. 西湖，环湖绿道，必打卡，免费
2. 灵隐寺，门票 75 元，建议游玩 2 小时
3. 龙井村，茶园拍照
4. 楼外楼，人均 200 元，必吃东坡肉
5. 西溪湿地公园，半日游
6. 河坊街，小吃一条街
7. 南宋御街，逛老字号
8. 雷峰塔，门票 40 元
9. 杭州动物园，带孩子去
10. 千岛湖，一天环湖骑行"""

NOTE_ZH_GROUND_TRUTH = [
    "西湖", "灵隐寺", "龙井村", "楼外楼", "西溪湿地公园",
    "河坊街", "南宋御街", "雷峰塔", "杭州动物园", "千岛湖",
]

# ── 英文攻略样本（已知差距：规则引擎仅中文地名收尾词，2026-11-10 实测 0/10） ──
NOTE_EN = """Tokyo 3-day itinerary:
1. Sensoji Temple, must-see, 1 hour
2. Shibuya Crossing, free, 30 mins
3. Meiji Shrine, free, 1 hour
4. Tsukiji Outer Market, breakfast
5. Tokyo Skytree, ticket 2100 yen
6. Ueno Park, cherry blossoms
7. Shinjuku Gyoen Garden, 2 hours
8. Akihabara, anime shopping
9. Tokyo Tower, 900 yen
10. Ginza, luxury shopping"""

NOTE_EN_GROUND_TRUTH = [
    "Sensoji Temple", "Shibuya Crossing", "Meiji Shrine", "Tsukiji Outer Market",
    "Tokyo Skytree", "Ueno Park", "Shinjuku Gyoen Garden", "Akihabara",
    "Tokyo Tower", "Ginza",
]

# ── 中文社交 caption 样本（social_import 通道） ────────────────────
SOCIAL_ZH = """谁懂啊！这家店真的绝了！
📍西湖边的山外山菜馆 人均200，吃得心满意足
✨灵隐寺 一定要去，门票 75
🔥in77 商场 逛到腿软
杭州三日游：西湖、灵隐寺、河坊街、南宋御街 都去了
https://www.xiaohongshu.com/explore/abc"""

SOCIAL_ZH_GROUND_TRUTH = [
    "山外山菜馆", "灵隐寺", "in77 商场", "西湖", "河坊街", "南宋御街",
]

# ── 中文预订确认邮件样本（email_import 通道候选） ──────────────────
EMAIL_ZH = """【预订确认】杭州西湖大酒店
预订编号：HZ20261101
入住日期：2026-11-20 至 2026-11-22
房型：豪华大床房
金额：¥1280.00

【预订确认】灵隐寺门票
门票已确认：灵隐寺
日期：2026-11-21
金额：¥75

【预订确认】西溪宾馆
订单号：XX9988
入住日期：2026-11-23
金额：¥680"""

EMAIL_ZH_GROUND_TRUTH = [
    "杭州西湖大酒店", "灵隐寺", "西溪宾馆",
]


def recall_at(candidates, ground_truth):
    """计算召回率：ground truth 中至少被一个候选名命中的比例（0.0~1.0）。

    匹配：归一化后相等 / 双向子串包含（长度容差 ±4，防「杭州西湖大酒店」
    误命中「西湖」）；返回 (recall, hits, missed)。
    """
    cand_names = [c.name.replace(" ", "").replace("　", "").lower() for c in candidates]
    hits: list[str] = []
    missed: list[str] = []
    for g in ground_truth:
        key = g.replace(" ", "").replace("　", "").lower()
        ok = any(
            cn == key
            or (key in cn and len(cn) <= len(key) + 4)
            or (cn in key and len(key) <= len(cn) + 4)
            for cn in cand_names
        )
        (hits if ok else missed).append(g)
    return len(hits) / len(ground_truth), hits, missed