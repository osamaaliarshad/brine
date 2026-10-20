from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.runtime import Runtime


def get_runtime(request: Request) -> Runtime:
    runtime: Runtime = request.app.state.runtime
    return runtime


async def get_session(
    runtime: Annotated[Runtime, Depends(get_runtime)],
) -> AsyncIterator[AsyncSession]:
    async with runtime.sessions() as session:
        yield session


RuntimeDep = Annotated[Runtime, Depends(get_runtime)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]
