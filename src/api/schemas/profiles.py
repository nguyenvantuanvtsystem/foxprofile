from pydantic import BaseModel, Field


class ProfileCreate(BaseModel):
    name: str
    proxy: str | None = None
    os_type: str = "windows"
    timezone: str | None = Field(
        None, description="IANA timezone, e.g. Asia/Ho_Chi_Minh. Unset = follow the IP"
    )
    locale: str | None = Field(
        None, description="language-REGION, e.g. vi-VN. Unset = follow the IP"
    )
    engine: str = Field(
        "camoufox",
        description="camoufox (Firefox) or chrome (experimental, fingerprint-chromium). "
        "Fixed once the profile is created",
    )
    extensions: list[str] = Field(
        default_factory=list,
        description="Unpacked extension dirs (manifest.json), loaded at launch (Chrome engine)",
    )
    cdp: bool = Field(
        True,
        description="Chrome engine: listen for DevTools Protocol on loopback (agents/automation)",
    )


class ProfileUpdate(BaseModel):
    """All fields optional — only supplied fields are changed."""

    name: str | None = None
    proxy: str | None = None
    os_type: str | None = None
    timezone: str | None = Field(None, description='"" switches back to automatic')
    locale: str | None = Field(None, description='"" switches back to automatic')
    engine: str | None = Field(None, description="Cannot be changed; only the current value")
    extensions: list[str] | None = Field(
        None, description="Replace the whole extension list (Chrome engine)"
    )
    cdp: bool | None = Field(None, description="DevTools Protocol port on/off (Chrome engine)")


class ProfileResponse(BaseModel):
    name: str
    proxy: str | None
    os_type: str
    timezone: str | None = None
    locale: str | None = None
    engine: str = "camoufox"
    extensions: list[str] = Field(default_factory=list)
    cdp: bool = True
    data_dir: str
    is_running: bool


class ProfileListResponse(BaseModel):
    profiles: list[ProfileResponse]
    total: int


class DataDirResponse(BaseModel):
    name: str
    data_dir: str
    exists: bool


class ExportRequest(BaseModel):
    export_dir: str
    include_data: bool = True


class ExportResponse(BaseModel):
    success: bool
    zip_path: str | None = None
    error: str | None = None


class ImportRequest(BaseModel):
    zip_path: str
    overwrite: bool = False


class ImportResponse(BaseModel):
    success: bool
    profile_name: str | None = None
    error: str | None = None


class CookieImportRequest(BaseModel):
    """Cookies as JSON (Cookie-Editor / EditThisCookie / Playwright) or Netscape text."""

    content: str


class CookieImportResponse(BaseModel):
    success: bool
    imported: int = 0
    error: str | None = None


class FingerprintResponse(BaseModel):
    name: str
    exists: bool
    os: str | None = None
    platform: str | None = None
    screen: str | None = None
    hardware_concurrency: int | None = None


class ExtensionAttachRequest(BaseModel):
    """Attach an unpacked extension directory (must contain manifest.json)."""

    path: str


class ExtensionAttachResponse(BaseModel):
    success: bool
    path: str | None = None
    error: str | None = None


class ExtensionListResponse(BaseModel):
    name: str
    extensions: list[str]
    total: int


class ExtensionBulkAttachRequest(BaseModel):
    """Attach one unpacked extension dir to many profiles at once."""

    names: list[str] = Field(..., min_length=1, max_length=50)
    path: str


class ExtensionBulkAttachResult(BaseModel):
    name: str
    ok: bool
    path: str | None = None
    error: str | None = None


class ExtensionBulkAttachResponse(BaseModel):
    results: list[ExtensionBulkAttachResult]
    ok_count: int
    fail_count: int


class DeviceResponse(BaseModel):
    name: str
    engine: str
    seed: int | None = None
    platform: str | None = None
    platform_version: str | None = None
    brand: str | None = None
    hardware_concurrency: int | None = None
    timezone: str | None = None
    locale: str | None = None
    user_agent: str | None = None
    webrtc: str | None = None
    geo: str | None = None


class DeviceUpdate(BaseModel):
    """Only supplied fields change. Empty user_agent switches back to derived."""

    brand: str | None = None
    platform_version: str | None = None
    hardware_concurrency: int | None = None
    user_agent: str | None = None
    webrtc: str | None = None
    geo: str | None = None
