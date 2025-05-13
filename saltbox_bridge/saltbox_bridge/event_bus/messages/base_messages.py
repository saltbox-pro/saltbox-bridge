from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class AbstractMessage(BaseModel):
    master: str | None = None

    model_config = ConfigDict(extra='allow')


class BaseBroadcastMessage(BaseModel):
    master: str | None = None


class BaseMessage(BaseModel):
    master: str
