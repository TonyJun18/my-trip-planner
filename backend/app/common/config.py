"""企业级配置管理。

支持多环境（dev / staging / prod），通过 ``ENV`` 环境变量切换。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import find_dotenv
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _env_file() -> str:
    """根据 ENV 变量加载对应 .env 文件。"""
    env = os.getenv("ENV", "dev")
    env_file = find_dotenv(f".env.{env}")
    if not env_file:
        env_file = find_dotenv(".env")
    return env_file or str(_PROJECT_ROOT / ".env")


class Settings(BaseSettings):
    """应用配置 —— 所有环境变量在此定义类型与默认值。"""

    model_config = SettingsConfigDict(
        env_file=_env_file(),
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
        validate_default=False,
    )

    # ── 应用 ────────────────────────────────────────────────
    APP_NAME: str = "my-trip-planner"
    ENV: str = "dev"
    DEBUG: bool = True
    DEV: bool = True

    # ── 服务 ────────────────────────────────────────────────
    HOST: str = "127.0.0.1"
    PORT: int = 8090

    SERPAPI_API_KEY: str | None = None
    TAVILY_API_KEY: str | None = None
    LLM_TIMEOUT: int = 60

    # ── 高德地图（POI 搜索 / 天气） ──────────────────────────
    AMAP_API_KEY: str | None = None
    """高德开放平台 Web 服务 key（https://lbs.amap.com）。配置后景点/酒店搜索与天气走高德，否则自动降级 Tavily / wttr.in。"""

    # ── 数据库 ──────────────────────────────────────────────
    DATABASE_URL: str | None = None

    EMBEDDING_MODEL: str | None = None

    CHROMA_PATH: str | None = None

    # ── AI Agent ────────────────────────────────────────────
    OPENAI_API_KEY: str | None = None
    OPENAI_BASE_URL: str | None = None
    OPENAI_MODEL: str = "gpt-4o-mini"

    # ── 认证 ────────────────────────────────────────────────
    JWT_SECRET: str | None = None
    """JWT 签名密钥。生产环境必须显式配置；未配置时用进程级随机（重启失效）。"""
    JWT_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 天
    AUTH_TOKEN_PREFIX: str = "Bearer"

    # ── Google OAuth（登录） ────────────────────────────────
    GOOGLE_CLIENT_ID: str | None = None
    """Google 控制台 Web 应用 OAuth Client ID（Google 登录：ID Token 校验 aud）。"""
    GOOGLE_CLIENT_SECRET: str | None = None
    """Google 控制台 Web 应用 OAuth Client Secret（当前 ID Token 流程可留空，预留给 code flow）。"""

    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "qwen2.5:7b"

    DEEPSEEK_API_KEY: str | None = None
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com/v1"
    DEEPSEEK_MODEL: str = "deepseek-chat"

    AGENT_MAX_ITERATIONS: int = 10
    AGENT_MAX_CORRECTIONS: int = 3
    """LLM 输出 schema 校验失败后，允许的最大自纠正次数。"""
    AGENT_MAX_REVIEW_ROUNDS: int = 2
    """行程质检（Evaluator-Optimizer）最大评审轮次：Planner 生成后由
    TravelCriticAgent 评审，不通过则带反馈重生成，最多评审该轮数后
    强制定稿（确保任务有界，不会无限循环）。"""
    DEFAULT_LLM_PROVIDER: str = "auto"

    # ── 任务可靠性（超时 / 恢复） ─────────────────────────────
    TASK_EXECUTION_TIMEOUT: int = 180
    """单个规划任务的最长执行秒数；超时标记 failed_timeout，避免卡死 worker 队列。"""
    TASK_STALE_RUNNING_SECONDS: int = 300
    """启动恢复扫描：running 超过该秒数视为进程崩溃遗留，标记为失败。"""
    ENABLE_PROVIDER_FALLBACK: bool = True
    """主 LLM provider 失败后是否自动切换兜底 provider（deepseek → openai → ollama）。"""

    # ── LLM 成本核算（USD） ──────────────────────────────────
    LLM_INPUT_PRICE_PER_1K: float | None = None
    """每 1K 输入 token 成本（美元）；配置后每次调用会估算 cost_usd。"""
    LLM_OUTPUT_PRICE_PER_1K: float | None = None
    """每 1K 输出 token 成本（美元）。"""

    # ── LLM 容错（重试 / 熔断） ─────────────────────────────
    LLM_MAX_RETRIES: int = 3
    """瞬时故障（网络/超时/限流/5xx）的最大重试次数（含首次）。"""
    LLM_RETRY_BASE_DELAY: float = 0.5
    """首次重试退避秒数（指数翻倍）。"""
    LLM_RETRY_MAX_DELAY: float = 8.0
    """重试退避等待上限（秒）。"""
    LLM_BREAKER_FAILURE_THRESHOLD: int = 3
    """LLM 熔断阈值：滚动窗口内系统性故障达到该次数 → 熔断。"""
    LLM_BREAKER_RECOVERY_TIMEOUT: float = 30.0
    """LLM 熔断冷却期（秒），之后进入 HALF-OPEN 试探。"""

    # ── CORS ────────────────────────────────────────────────
    # 使用 Union 类型使 pydantic-settings 的 JSON 解析失败时允许降级到 validator
    CORS_ORIGINS: list[str] | str = ["*"]

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: object) -> list[str]:
        """兼容 JSON 数组与纯字符串两种格式。

        当环境变量设爲 ``CORS_ORIGINS=*``（非 JSON）时，pydantic-settings
        的 JSON 解析会失败，通过 Union 类型的 allow_parse_failure 机制，
        原始字符串会传递到此 validator 进行手动解析。
        """
        if isinstance(v, str):
            v = v.strip()
            if not v:
                return ["*"]
            # 已经是 JSON 数组格式 → 直接解析
            if v.startswith("["):
                parsed = json.loads(v)
                if isinstance(parsed, list):
                    return parsed
            # 按逗号分割（兼容 ``CORS_ORIGINS=*`` 或 ``CORS_ORIGINS=a,b,c``）
            return [item.strip() for item in v.split(",") if item.strip()]
        return v if isinstance(v, list) else ["*"]

    # ── 日志 ────────────────────────────────────────────────
    LOG_LEVEL: str = "DEBUG"

    # ── 辅助属性 ────────────────────────────────────────────
    @property
    def is_dev(self) -> bool:
        return self.ENV == "dev"

    @property
    def is_prod(self) -> bool:
        return self.ENV == "prod"


# 模块级单例
settings = Settings()
