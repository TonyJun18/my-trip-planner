"""i18n 基础：语言归一化 + 文案字典访问。

方案 A（双语提示词目录 + 代码文案 i18n）的语言「单一事实来源」：

- 支持语种：``zh-CN``（默认）/ ``en-US``（``SUPPORTED_LOCALES``）
- 所有 Agent 自然语言输出与代码生成文案必须经由这里，
  不允许在业务代码里散落语言硬编码（新语种 = 这里加一列 + 测试补一条）
- 宽松解析：任何来源（Accept-Language / 请求字段 / 前端 i18n locale）
  先经 ``normalize_locale`` 归一，未知语种一律回退 ``DEFAULT_LOCALE``
"""
from __future__ import annotations

from typing import Any

DEFAULT_LOCALE = "zh-CN"
SUPPORTED_LOCALES = ("zh-CN", "en-US")

# 语种别名归一表（宽松匹配：大小写 / 下划线 / 区域后缀）
_LOCALE_ALIASES: dict[str, str] = {
    "zh": "zh-CN",
    "zh-cn": "zh-CN",
    "zh_cn": "zh-CN",
    "zh-hans": "zh-CN",
    "zh-hans-cn": "zh-CN",
    "zh-sg": "zh-CN",
    "zh-tw": "zh-CN",  # 尚未支持繁体，回退简体（不猜测新语种）
    "en": "en-US",
    "en-us": "en-US",
    "en_us": "en-US",
    "en-gb": "en-US",
    "en-au": "en-US",
    "en-ca": "en-US",
}


def normalize_locale(raw: str | None) -> str:
    """把任意语言来源归一为受支持语种；未知/空一律回退默认。

    - 接受 ``Accept-Language`` 头原文（``"en-US,en;q=0.9"``）→ 取第一个标签
    - 接受 ``"en"`` / ``"zh"`` / ``"zh-Hans"`` / ``"en_GB"`` 等常见写法
    """
    if not raw:
        return DEFAULT_LOCALE
    first = raw.split(",")[0].strip()
    if not first:
        return DEFAULT_LOCALE
    key = first.lower().replace("_", "-")
    if key in _LOCALE_ALIASES:
        return _LOCALE_ALIASES[key]
    # 区域后缀剥离：zh-CN / en-US 已覆盖；未知主语言直接回退
    base = key.split("-")[0]
    return _LOCALE_ALIASES.get(base, DEFAULT_LOCALE)


def is_supported(locale: str) -> bool:
    """语种是否在受支持列表内（判断是否需要「新语种上线」流程）。"""
    return locale in SUPPORTED_LOCALES