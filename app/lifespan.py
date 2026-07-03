"""Application lifespan: startup/shutdown hooks."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.container import ApplicationContainer
from config.env_loader import bootstrap_environment


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    bootstrap_environment()
    container = ApplicationContainer.create()
    await container.startup()
    container.bind_app_state(app)

    yield

    await container.shutdown()
