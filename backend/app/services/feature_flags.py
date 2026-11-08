"""Feature flag 下发（服务端 kill switch）。

背景（``docs/plans/2026-11-08-trip-detail-ia-v2-phase2-closeout.md`` §3.1 A2）：
详情页 IA v2 的回滚口原先只有浏览器级（URL 参数 / localStorage），全站回滚 =
改代码重新发布前端。这里把开关做成后端 env 下发的 JSON，运维改 env + 重启后端即可
让全站回到旧版面，前端 ``Cache-Control: max-age=60`` 内自愈——**不需要重新发布前端**。

设计取舍：

- **开关来源只有一处**：env ``FEATURE_FLAGS_JSON``（JSON 对象），不落库、不做后台。
  开关是运维面配置而非业务数据；env 变更天然有审计（谁在什么时候改的）。
- **只放行 ``tripDetail.`` 前缀**：这是给公开端点（无鉴权）用的，白名单前缀防止
  以后有人把敏感配置当开关塞进来下发。
- **值支持两种写法**：``true/false`` 与 ``{"on": bool}``；其它形态忽略并 warning。
  dict 形态留了口子（未来要加 ``percent`` 之类无需改解析），但当前**不实现**百分比灰度。
- **解析失败绝不阻断**：非法 JSON / 非对象 → 空开关 + warning（项目「降级不阻断」哲学）。
- **revision**：原始串的短哈希，运维据此确认「我改的那一次到底下发到前端了没」。

为什么不做百分比灰度（PRD §6 的 20% → 100%）：当前真实流量不足以形成统计显著，
``percent`` 只会制造「以为灰了其实没灰」的假象；G1 对照组改用设计伙伴 ``?flag=`` 抽样
+ 前后时段对比。这条降级决定已写进方案文档与 PRD §4.1。
"""

from __future__ import annotations

import hashlib
import json
import logging

from app.common.config import settings

logger = logging.getLogger(__name__)

# 允许下发的 key 前缀（公开端点白名单）
ALLOWED_PREFIX = "tripDetail."


def parse_flags(raw: str | None) -> dict[str, bool]:
    """把 env 里的 JSON 串解析成 ``{flag: bool}``（纯函数，可单测）。

    非法输入一律降级为空字典：开关坏掉只应该「回到默认版面」，不该让服务起不来。
    """
    if not raw or not raw.strip():
        return {}

    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        logger.warning("FEATURE_FLAGS_JSON 不是合法 JSON，按空开关处理: %r", raw[:200])
        return {}

    if not isinstance(data, dict):
        logger.warning(
            "FEATURE_FLAGS_JSON 必须是 JSON 对象，收到 %s，按空开关处理",
            type(data).__name__,
        )
        return {}

    flags: dict[str, bool] = {}
    for key, value in data.items():
        name = str(key)
        if not name.startswith(ALLOWED_PREFIX):
            logger.warning("FEATURE_FLAGS_JSON 忽略非 %s* 键: %s", ALLOWED_PREFIX, name)
            continue
        if isinstance(value, bool):
            flags[name] = value
        elif isinstance(value, dict) and isinstance(value.get("on"), bool):
            flags[name] = bool(value["on"])
        else:
            logger.warning("FEATURE_FLAGS_JSON 忽略形态非法的值: %s=%r", name, value)
    return flags


def revision_of(flags: dict[str, bool]) -> str:
    """开关快照的短哈希（规范化后计算：键序 / 空白不影响结果）。

    没配置任何开关时返回空串——运维看到 ``revision: ""`` 就知道「服务端没下发任何开关」，
    而不是「改了个空对象」。改 env 后 revision 变化 = 新配置确实生效了。
    """
    if not flags:
        return ""
    canonical = json.dumps(flags, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:8]


def flags_revision(raw: str | None = None) -> str:
    """按 env 原始串计算 revision（测试 / 排查用）。"""
    if raw is None:
        raw = settings.FEATURE_FLAGS_JSON
    return revision_of(parse_flags(raw))


def current_flags() -> dict[str, bool]:
    """当前生效的服务端开关。

    每次调用都读 ``settings``（不做进程内缓存）：开关变更走「改 env + 重启」，
    重启后新值立即生效；60s 的 HTTP 缓存由端点负责。
    """
    return parse_flags(settings.FEATURE_FLAGS_JSON)
