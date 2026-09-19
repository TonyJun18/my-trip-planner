"""开发服务器启动入口。"""

import asyncio
import sys

import uvicorn
from dotenv import load_dotenv

from app.common.config import settings

load_dotenv()


def main() -> None:
    """启动 uvicorn 开发服务器。"""
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.is_dev,
    )


if __name__ == "__main__":
    main()
