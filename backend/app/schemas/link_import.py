"""链接导入 Schema：请求/响应的 Pydantic 模型。

独立成模块（不并入 schemas/__init__.py），避免与用户未提交的
schemas/__init__.py 改动混淆；API 层直接从本模块 import。

对外部抓取内容的防护（schema 层）：
- url 字段强校验（长度上限 + 服务层做 scheme/SSRF 检查）；
- 响应字段全部有长度上限，抓取到的内容只作为「数据」字段透出，
  绝不作为指令；站点候选复用 note-import 结构（敌意行已剥离）。
"""
from __future__ import annotations

from pydantic import BaseModel, Field

# 输入上限（字符）。公开分享链接通常 <1k，2048 足够；防超大粘贴。
MAX_URL_LENGTH = 2048
# 输出长度上限（抓取内容截断，防超大响应 / 防注入式超长字段）。
MAX_TITLE_LENGTH = 120
MAX_DESC_LENGTH = 300


class LinkImportRequest(BaseModel):
    """用户粘贴的公开分享链接（小红书/马蜂窝/携程/去哪儿等）。

    外部内容按敌意输入处理：服务层只提取 og:title/og:description 纯文本，
    输出经本 schema 强校验，绝不把抓取内容当指令执行。
    """

    url: str = Field(
        min_length=6,
        max_length=MAX_URL_LENGTH,
        description="公开分享链接（http/https，服务层再做 SSRF 与 scheme 校验）",
    )


class LinkImportResultOut(BaseModel):
    """链接导入结果：提取成功（extracted=true）或静默降级为链接收藏（extracted=false）。

    降级语义：链接合法但抓取/提取失败（网络受限、平台反爬、无 meta）
    → 仍返回 200，卡片化为「链接收藏」，不打断用户流程。
    """

    url: str = Field(max_length=MAX_URL_LENGTH)
    title: str = Field(max_length=MAX_TITLE_LENGTH, description="提取到的标题或平台默认标题")
    platform: str = Field(max_length=32, description="平台 slug：xiaohongshu/mafengwo/ctrip/qunar/dianping/tripadvisor/weibo/bilibili/generic")
    extracted: bool = Field(default=False, description="true=从页面提取到结构化信息；false=降级为链接收藏")
    description: str = Field(default="", max_length=MAX_DESC_LENGTH)
    # 从标题/描述启发出的站点候选（复用 note-import 结构，敌意行已剥离，可勾选并入行程）。
    candidates: list[dict] = Field(default_factory=list)