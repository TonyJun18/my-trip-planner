"""进程内 WebSocket 广播中枢（pub/sub）。

设计：
- 以 ``key``（如 ``planner:{task_id}`` / ``collab:{trip_id}``）为维度维护订阅者队列。
- 发布方（Agent 执行器 / 协作 REST handler）调用 ``publish``，消息进入每个订阅者
  的 asyncio.Queue；端点层消费队列并 send 到各 WebSocket 连接。
- 断线由端点层负责 unsubscribe；订阅者集合为空时 publish 是廉价 no-op。
- 单进程内存实现：与当前「单 worker 执行器」同构，多实例部署时需换成 Redis
  pub/sub —— 但接口（publish/subscribe）保持兼容，不扩散到业务层。
"""
from __future__ import annotations

import asyncio
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)


class BroadcastHub:
    """进程内广播中枢：key → set[asyncio.Queue]."""

    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue]] = {}

    def subscribe(self, key: str) -> asyncio.Queue:
        """订阅一个 key，返回该连接专属的消息队列。"""
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers.setdefault(key, set()).add(queue)
        return queue

    def unsubscribe(self, key: str, queue: asyncio.Queue) -> None:
        """取消订阅；集合清空时移除 key。"""
        subs = self._subscribers.get(key)
        if subs is None:
            return
        subs.discard(queue)
        if not subs:
            self._subscribers.pop(key, None)

    async def publish(self, key: str, message: dict[str, Any]) -> None:
        """向 key 的所有订阅者投递一条 JSON 可序列化消息。"""
        subs = self._subscribers.get(key)
        if not subs:
            return
        for queue in list(subs):
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:  # 慢消费者：丢弃最旧消息，避免阻塞发布方
                try:
                    queue.get_nowait()
                    queue.put_nowait(message)
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    pass

    def subscriber_count(self, key: str) -> int:
        return len(self._subscribers.get(key, set()))


# ── 全局中枢（应用级单例） ─────────────────────────────────────
hub = BroadcastHub()