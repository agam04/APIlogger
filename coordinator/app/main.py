"""FastAPI application factory with lifespan management."""

import asyncio
import contextlib
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from app.api.deps import close_redis, init_redis
from app.api.v1 import auth, checks, health, incidents, services
from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.queue.consumer import run_result_consumer
from app.queue.producer import ensure_consumer_groups
from app.scheduler.scheduler import start_scheduler, stop_scheduler

configure_logging()
log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    log.info("coordinator_starting", env=settings.ENV)

    await init_redis()

    from app.api.deps import get_redis_pool

    redis = get_redis_pool()
    await ensure_consumer_groups(redis)

    await start_scheduler(redis)
    consumer_task = asyncio.create_task(run_result_consumer(redis), name="result-consumer")

    log.info("coordinator_ready")
    yield

    log.info("coordinator_stopping")
    consumer_task.cancel()
    with contextlib.suppress(TimeoutError, asyncio.CancelledError):
        await asyncio.wait_for(asyncio.shield(consumer_task), timeout=5)

    await stop_scheduler()
    await close_redis()
    log.info("coordinator_stopped")


def create_app() -> FastAPI:
    app = FastAPI(
        title="APILogger Coordinator",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # tighten in production
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    api_prefix = "/api/v1"
    app.include_router(auth.router, prefix=api_prefix)
    app.include_router(services.router, prefix=api_prefix)
    app.include_router(checks.router, prefix=api_prefix)
    app.include_router(incidents.router, prefix=api_prefix)
    app.include_router(health.router)

    # ---- SSE endpoint for live dashboard ----
    @app.get("/api/v1/events")
    async def event_stream(request: Request) -> StreamingResponse:
        """Server-Sent Events stream for real-time status updates."""
        from app.api.deps import get_redis_pool

        async def generator() -> AsyncGenerator[str, None]:
            redis = get_redis_pool()
            pubsub = redis.pubsub()
            await pubsub.subscribe(settings.EVENTS_CHANNEL)
            try:
                yield 'data: {"type": "connected"}\n\n'
                async for message in pubsub.listen():
                    if await request.is_disconnected():
                        break
                    if message["type"] == "message":
                        yield f"data: {message['data']}\n\n"
            finally:
                await pubsub.unsubscribe(settings.EVENTS_CHANNEL)
                await pubsub.aclose()

        return StreamingResponse(
            generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    return app


app = create_app()
