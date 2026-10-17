from typing import Any

from pydantic import BaseModel, Field


class BrowserStatusResponse(BaseModel):
    name: str
    is_running: bool
    cdp_url: str | None = Field(
        None, description="DevTools URL (http://127.0.0.1:PORT/json) when a CDP port is open"
    )


class RunningBrowsersResponse(BaseModel):
    running: list[str]
    count: int


class LaunchResponse(BaseModel):
    success: bool
    message: str


class LaunchManyRequest(BaseModel):
    names: list[str] = Field(..., min_length=1, max_length=20)
    layout: str = Field("auto", description="auto, 1x2, 2x2, 3x2, 3x3")


class LaunchManyResult(BaseModel):
    name: str
    ok: bool
    message: str


class LaunchManyResponse(BaseModel):
    results: list[LaunchManyResult]
    arranged: int = 0
    arrange_error: str | None = None


class ArrangeRequest(BaseModel):
    names: list[str] | None = Field(
        None, description="Arrange these running profiles; default = all running"
    )
    layout: str = Field("auto", description="auto, 1x2, 2x2, 3x2, 3x3")


class ArrangeResponse(BaseModel):
    arranged: int
    names: list[str]
    relaunched: bool = Field(
        False,
        description="True when windows were re-opened into the grid (no permission to move them live)",
    )
    note: str | None = None


class SyncRequest(BaseModel):
    names: list[str] = Field(..., min_length=1, max_length=20)
    action: str = Field(
        ...,
        description="navigate, back, keyboard_type, press, click_at or evaluate",
    )
    params: dict[str, Any] = Field(default_factory=dict)


class SyncResult(BaseModel):
    name: str
    ok: bool
    result: Any | None = None
    error: str | None = None


class SyncResponse(BaseModel):
    results: list[SyncResult]
    ok_count: int
    fail_count: int


class MirrorStartRequest(BaseModel):
    master: str = Field(..., description="Running profile to follow")
    followers: list[str] | None = Field(
        None, description="Profiles to mirror to; default = all other running"
    )


class MirrorStatusResponse(BaseModel):
    active: bool
    master: str | None = None
    followers: list[str] = Field(default_factory=list)
    events_in: int = 0
    events_dropped: int = 0


class MirrorEventRequest(BaseModel):
    events: list[dict[str, Any]] = Field(..., min_length=1, max_length=50)
