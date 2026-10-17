from __future__ import annotations

import os
import pathlib
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import PlainTextResponse

from ...core.config import DATA_DIR
from ...core.logging import get_logger
from ...models.profile import ENGINES, MAX_EXTENSIONS
from ...services.browser import chrome_prefetch, cookies, fingerprint
from ...services.browser.launcher import ProfileBusyError
from ...services.profile.extensions import (
    attached_ids,
    pin_extensions,
    save_upload,
    validate_ext_dir,
)
from ...services.proxy.geo_check import check_geo
from ...utils.validation import (
    validate_locale,
    validate_profile_name,
    validate_proxy_format,
    validate_timezone,
)
from ..dependencies import get_browser_launcher, get_event_bus, get_profile_manager
from ..helpers import build_profile_response, profile_response, require_profile
from ..schemas.common import ErrorResponse, SuccessResponse
from ..schemas.profiles import (
    CookieImportRequest,
    CookieImportResponse,
    DataDirResponse,
    DeviceResponse,
    DeviceUpdate,
    ExportRequest,
    ExportResponse,
    ExtensionAttachRequest,
    ExtensionAttachResponse,
    ExtensionBulkAttachRequest,
    ExtensionBulkAttachResponse,
    ExtensionBulkAttachResult,
    ExtensionListResponse,
    FingerprintResponse,
    ImportRequest,
    ImportResponse,
    ProfileCreate,
    ProfileListResponse,
    ProfileResponse,
    ProfileUpdate,
)
from ..schemas.proxy import GeoCheckResponse

if TYPE_CHECKING:
    from ...core.events import EventBus
    from ...interfaces import IBrowserLauncher, IProfileManager

logger = get_logger("api.profiles")

router = APIRouter(prefix="/profiles", tags=["profiles"])

_OS_TYPES = ("windows", "macos", "linux")


def _require_os(os_type: str) -> None:
    if os_type not in _OS_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"os_type must be one of: {', '.join(_OS_TYPES)}",
        )


def _require_engine(engine: str) -> None:
    if engine not in ENGINES:
        raise HTTPException(
            status_code=400,
            detail=f"engine must be one of: {', '.join(ENGINES)}",
        )
    if engine == "chrome" and (reason := chrome_prefetch.unsupported_reason()):
        raise HTTPException(status_code=400, detail=f"Chrome engine unavailable here: {reason}")


def _require_geo(timezone: str | None, locale: str | None) -> None:
    for validate, value in ((validate_timezone, timezone), (validate_locale, locale)):
        valid, msg = validate(value or "")
        if not valid:
            raise HTTPException(status_code=400, detail=msg)


def _require_extensions(paths: list[str] | None) -> None:
    if not paths:
        return
    if len(paths) > MAX_EXTENSIONS:
        raise HTTPException(
            status_code=400, detail=f"At most {MAX_EXTENSIONS} extensions per profile"
        )
    for p in paths:
        ok, err = validate_ext_dir(p)
        if not ok:
            raise HTTPException(status_code=400, detail=f"Bad extension dir {p!r}: {err}")


@router.get("", response_model=ProfileListResponse)
def list_profiles(
    pm: IProfileManager = Depends(get_profile_manager),
    bl: IBrowserLauncher = Depends(get_browser_launcher),
) -> ProfileListResponse:
    profiles = [profile_response(p, bl) for p in pm.list_profiles()]
    return ProfileListResponse(profiles=profiles, total=len(profiles))


@router.post(
    "",
    response_model=ProfileResponse,
    status_code=201,
    responses={400: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def create_profile(
    body: ProfileCreate,
    pm: IProfileManager = Depends(get_profile_manager),
    bl: IBrowserLauncher = Depends(get_browser_launcher),
    bus: EventBus = Depends(get_event_bus),
) -> ProfileResponse:
    valid, msg = validate_profile_name(body.name)
    if not valid:
        raise HTTPException(status_code=400, detail=msg)
    _require_os(body.os_type)
    _require_engine(body.engine)
    _require_geo(body.timezone, body.locale)

    if body.proxy:
        valid, msg = validate_proxy_format(body.proxy)
        if not valid:
            raise HTTPException(status_code=400, detail=msg)
    _require_extensions(body.extensions)

    if not pm.add_profile(
        body.name,
        body.proxy or "",
        body.os_type,
        body.timezone or None,
        body.locale or None,
        body.engine,
        body.extensions,
        body.cdp,
    ):
        raise HTTPException(status_code=409, detail="Profile already exists")

    logger.info("API created profile: %s", body.name)
    if body.engine == "chrome":
        chrome_prefetch.start()
    bus.emit()
    return build_profile_response(body.name, pm, bl)


@router.post(
    "/extensions/attach-many",
    response_model=ExtensionBulkAttachResponse,
    responses={400: {"model": ErrorResponse}},
)
def bulk_attach_extension(
    body: ExtensionBulkAttachRequest,
    pm: IProfileManager = Depends(get_profile_manager),
    bus: EventBus = Depends(get_event_bus),
) -> ExtensionBulkAttachResponse:
    """Attach one unpacked extension dir to many profiles.

    Safe on running profiles (takes effect on next launch); only the
    toolbar pin needs a stopped browser.
    """
    ok, err = validate_ext_dir(body.path)
    if not ok:
        raise HTTPException(status_code=400, detail=f"Bad extension dir: {err}")
    results = []
    for name in body.names:
        require_profile(name, pm)
        good, msg = pm.attach_extension(name, body.path)
        results.append(
            ExtensionBulkAttachResult(
                name=name, ok=good, path=msg if good else None, error=None if good else msg
            )
        )
    bus.emit()
    ok_count = sum(1 for r in results if r.ok)
    return ExtensionBulkAttachResponse(
        results=results, ok_count=ok_count, fail_count=len(results) - ok_count
    )


@router.get(
    "/{name}",
    response_model=ProfileResponse,
    responses={404: {"model": ErrorResponse}},
)
def get_profile(
    name: str,
    pm: IProfileManager = Depends(get_profile_manager),
    bl: IBrowserLauncher = Depends(get_browser_launcher),
) -> ProfileResponse:
    require_profile(name, pm)
    return build_profile_response(name, pm, bl)


@router.patch(
    "/{name}",
    response_model=ProfileResponse,
    responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def update_profile(
    name: str,
    body: ProfileUpdate,
    pm: IProfileManager = Depends(get_profile_manager),
    bl: IBrowserLauncher = Depends(get_browser_launcher),
    bus: EventBus = Depends(get_event_bus),
) -> ProfileResponse:
    profile = require_profile(name, pm)
    supplied = body.model_dump(exclude_unset=True)

    new_name = supplied.get("name", name)
    new_proxy = supplied.get("proxy", profile.proxy)
    new_os = supplied.get("os_type", profile.os_type)
    new_timezone = supplied.get("timezone", profile.timezone)
    new_locale = supplied.get("locale", profile.locale)

    if "name" in supplied:
        valid, msg = validate_profile_name(new_name)
        if not valid:
            raise HTTPException(status_code=400, detail=msg)
        if new_name != name and bl.is_running(name):
            raise HTTPException(
                status_code=409,
                detail="Stop the browser before renaming",
            )

    if supplied.get("engine") not in (None, profile.engine):
        raise HTTPException(
            status_code=400,
            detail="A profile's engine cannot be changed; create a new profile instead",
        )
    if "os_type" in supplied:
        _require_os(new_os)
    _require_geo(supplied.get("timezone"), supplied.get("locale"))

    if "proxy" in supplied and new_proxy:
        valid, msg = validate_proxy_format(new_proxy)
        if not valid:
            raise HTTPException(status_code=400, detail=msg)
    new_extensions = supplied.get("extensions", profile.extensions)
    if "extensions" in supplied:
        _require_extensions(new_extensions)

    if not pm.update_profile(
        name,
        new_name,
        new_proxy or "",
        new_os,
        new_timezone or None,
        new_locale or None,
        new_extensions if "extensions" in supplied else None,
        supplied.get("cdp"),
    ):
        raise HTTPException(status_code=409, detail="Update failed (name conflict?)")

    logger.info("API updated profile: %s -> %s", name, new_name)
    bus.emit()
    return build_profile_response(new_name, pm, bl)


@router.delete(
    "/{name}",
    response_model=SuccessResponse,
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def delete_profile(
    name: str,
    pm: IProfileManager = Depends(get_profile_manager),
    bl: IBrowserLauncher = Depends(get_browser_launcher),
    bus: EventBus = Depends(get_event_bus),
) -> SuccessResponse:
    require_profile(name, pm)
    if bl.is_running(name):
        raise HTTPException(
            status_code=409,
            detail="Stop the browser before deleting",
        )
    pm.delete_profile(name)
    logger.info("API deleted profile: %s", name)
    bus.emit()
    return SuccessResponse(message=f"Profile '{name}' deleted")


@router.get(
    "/{name}/data-dir",
    response_model=DataDirResponse,
    responses={404: {"model": ErrorResponse}},
)
def get_data_dir(
    name: str,
    pm: IProfileManager = Depends(get_profile_manager),
) -> DataDirResponse:
    require_profile(name, pm)
    data_dir = os.path.join(os.getcwd(), DATA_DIR, name)
    return DataDirResponse(
        name=name,
        data_dir=data_dir,
        exists=pathlib.Path(data_dir).exists(),
    )


@router.post(
    "/{name}/export",
    response_model=ExportResponse,
    responses={404: {"model": ErrorResponse}},
)
def export_profile(
    name: str,
    body: ExportRequest,
    pm: IProfileManager = Depends(get_profile_manager),
) -> ExportResponse:
    require_profile(name, pm)
    if not pathlib.Path(body.export_dir).is_dir():
        raise HTTPException(status_code=400, detail="export_dir is not a directory")

    success, result = pm.export_profile(name, body.export_dir, body.include_data)
    if success:
        logger.info("API exported profile: %s -> %s", name, result)
        return ExportResponse(success=True, zip_path=result)
    return ExportResponse(success=False, error=result)


@router.post(
    "/import",
    response_model=ImportResponse,
    responses={400: {"model": ErrorResponse}},
)
def import_profile(
    body: ImportRequest,
    pm: IProfileManager = Depends(get_profile_manager),
    bus: EventBus = Depends(get_event_bus),
) -> ImportResponse:
    if not pathlib.Path(body.zip_path).is_file():
        raise HTTPException(status_code=400, detail="zip_path is not a file")

    success, result = pm.import_profile(body.zip_path, body.overwrite)
    if success:
        logger.info("API imported profile: %s", result)
        bus.emit()
        return ImportResponse(success=True, profile_name=result)
    return ImportResponse(success=False, error=result)


def _require_stopped(name: str, bl: IBrowserLauncher, action: str) -> None:
    if bl.is_running(name):
        raise HTTPException(status_code=409, detail=f"Stop the browser before {action}")


_BUSY_DETAIL = "Profile is running or busy with another operation"


@router.get(
    "/{name}/cookies",
    response_class=PlainTextResponse,
    responses={
        200: {"content": {"text/plain": {}, "application/json": {}}},
        400: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
)
def export_cookies(
    name: str,
    format: str = Query("json", pattern="^(json|netscape)$"),
    pm: IProfileManager = Depends(get_profile_manager),
    bl: IBrowserLauncher = Depends(get_browser_launcher),
) -> PlainTextResponse:
    """Export cookies as Cookie-Editor JSON or Netscape cookies.txt."""
    profile = require_profile(name, pm)
    _require_stopped(name, bl, "exporting cookies")
    try:
        with bl.exclusive(name):
            text, count = cookies.export_cookies(name, profile.os_type, format, profile.engine)
    except ProfileBusyError as e:
        raise HTTPException(status_code=409, detail=_BUSY_DETAIL) from e
    except cookies.CookieError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    media = "application/json" if format == "json" else "text/plain"
    return PlainTextResponse(text, media_type=media, headers={"X-Cookie-Count": str(count)})


@router.post(
    "/{name}/cookies",
    response_model=CookieImportResponse,
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def import_cookies(
    name: str,
    body: CookieImportRequest,
    pm: IProfileManager = Depends(get_profile_manager),
    bl: IBrowserLauncher = Depends(get_browser_launcher),
) -> CookieImportResponse:
    """Import cookies from JSON or Netscape text into a stopped profile."""
    profile = require_profile(name, pm)
    _require_stopped(name, bl, "importing cookies")
    try:
        with bl.exclusive(name):
            count = cookies.import_cookies(name, profile.os_type, body.content, profile.engine)
    except ProfileBusyError as e:
        raise HTTPException(status_code=409, detail=_BUSY_DETAIL) from e
    except cookies.CookieError as e:
        return CookieImportResponse(success=False, error=str(e))
    logger.info("API imported %d cookies into %s", count, name)
    return CookieImportResponse(success=True, imported=count)


@router.get(
    "/{name}/fingerprint",
    response_model=FingerprintResponse,
    responses={404: {"model": ErrorResponse}},
)
def get_fingerprint(
    name: str,
    pm: IProfileManager = Depends(get_profile_manager),
) -> FingerprintResponse:
    """Show the fingerprint the profile presents on every launch."""
    require_profile(name, pm)
    info = fingerprint.summary(os.path.join(DATA_DIR, name))
    if info is None:
        return FingerprintResponse(name=name, exists=False)
    return FingerprintResponse(name=name, exists=True, **info)


@router.delete(
    "/{name}/fingerprint",
    response_model=SuccessResponse,
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def reset_fingerprint(
    name: str,
    pm: IProfileManager = Depends(get_profile_manager),
    bl: IBrowserLauncher = Depends(get_browser_launcher),
) -> SuccessResponse:
    """Discard the saved fingerprint; the next launch generates a new device."""
    require_profile(name, pm)
    _require_stopped(name, bl, "resetting the fingerprint")
    removed = fingerprint.reset(os.path.join(DATA_DIR, name))
    logger.info("API reset fingerprint for %s (existed=%s)", name, removed)
    return SuccessResponse(message=f"Fingerprint reset for '{name}'")


@router.get(
    "/{name}/ip-check",
    response_model=GeoCheckResponse,
    responses={404: {"model": ErrorResponse}},
)
def check_profile_ip(
    name: str,
    pm: IProfileManager = Depends(get_profile_manager),
) -> GeoCheckResponse:
    """Where GeoIP sources place the profile's exit IP vs. the timezone/locale it presents.

    Goes out through the profile's proxy to Cloudflare, ipinfo and ip-api (~10s).
    """
    profile = require_profile(name, pm)
    return GeoCheckResponse.from_result(check_geo(profile.proxy, profile.timezone, profile.locale))


@router.get(
    "/{name}/extensions",
    response_model=ExtensionListResponse,
    responses={404: {"model": ErrorResponse}},
)
def list_extensions(
    name: str,
    pm: IProfileManager = Depends(get_profile_manager),
) -> ExtensionListResponse:
    """Unpacked extension dirs attached to a profile (loaded at launch, Chrome engine)."""
    profile = require_profile(name, pm)
    return ExtensionListResponse(
        name=name, extensions=list(profile.extensions), total=len(profile.extensions)
    )


@router.post(
    "/{name}/extensions",
    response_model=ExtensionAttachResponse,
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def attach_extension(
    name: str,
    body: ExtensionAttachRequest,
    pm: IProfileManager = Depends(get_profile_manager),
    bl: IBrowserLauncher = Depends(get_browser_launcher),
    bus: EventBus = Depends(get_event_bus),
) -> ExtensionAttachResponse:
    """Attach an unpacked extension dir (takes effect on the next launch)."""
    require_profile(name, pm)
    _require_stopped(name, bl, "changing extensions")
    ok, msg = pm.attach_extension(name, body.path)
    if not ok:
        return ExtensionAttachResponse(success=False, error=msg)
    bus.emit()
    return ExtensionAttachResponse(success=True, path=msg)


@router.delete(
    "/{name}/extensions",
    response_model=SuccessResponse,
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def detach_extension(
    name: str,
    path: str = Query(..., description="Attached extension dir to remove"),
    pm: IProfileManager = Depends(get_profile_manager),
    bl: IBrowserLauncher = Depends(get_browser_launcher),
    bus: EventBus = Depends(get_event_bus),
) -> SuccessResponse:
    require_profile(name, pm)
    _require_stopped(name, bl, "changing extensions")
    if not pm.detach_extension(name, path):
        raise HTTPException(status_code=404, detail="Extension not attached to this profile")
    bus.emit()
    return SuccessResponse(message=f"Extension detached from '{name}'")


@router.post(
    "/{name}/extensions/upload",
    response_model=ExtensionAttachResponse,
    responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def upload_extension(
    name: str,
    file: UploadFile = File(...),
    pm: IProfileManager = Depends(get_profile_manager),
    bl: IBrowserLauncher = Depends(get_browser_launcher),
    bus: EventBus = Depends(get_event_bus),
) -> ExtensionAttachResponse:
    """Upload a .zip of an unpacked extension, store it, and attach it to a profile."""
    require_profile(name, pm)
    _require_stopped(name, bl, "changing extensions")
    data = await file.read()
    ok, result = save_upload(name, file.filename or "upload.zip", data)
    if not ok:
        return ExtensionAttachResponse(success=False, error=result)
    attached, msg = pm.attach_extension(name, result)
    if not attached:
        return ExtensionAttachResponse(success=False, error=msg)
    bus.emit()
    return ExtensionAttachResponse(success=True, path=msg)


@router.post(
    "/{name}/extensions/pin",
    response_model=SuccessResponse,
    responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def pin_profile_extensions(
    name: str,
    pm: IProfileManager = Depends(get_profile_manager),
    bl: IBrowserLauncher = Depends(get_browser_launcher),
) -> SuccessResponse:
    """Pin attached extensions to the toolbar. Browser must be stopped.

    Resolves install IDs from a previous launch, then writes them into
    extensions.pinned_extensions so the icons show on the next start.
    """
    profile = require_profile(name, pm)
    _require_stopped(name, bl, "pinning extensions")
    if profile.engine != "chrome":
        raise HTTPException(status_code=400, detail="Extensions load only on the Chrome engine")
    if not profile.extensions:
        raise HTTPException(status_code=400, detail="No extensions attached to this profile")
    profile_dir = os.path.join(os.getcwd(), DATA_DIR, name)
    ids = attached_ids(profile_dir, profile.extensions)
    missing = [p for p, i in ids.items() if not i]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Open the profile once first so Chrome registers: {missing[0]}",
        )
    ok, msg = pin_extensions(profile_dir, list(ids.values()))
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return SuccessResponse(message=f"Pinned {len(ids)} extension(s) on '{name}'")


def _require_chrome_device(name: str, pm: IProfileManager):
    """The saved Chrome persona, or an HTTP error explaining why not."""
    from chrome_engine import persona as chrome_persona

    profile = require_profile(name, pm)
    if profile.engine != "chrome":
        raise HTTPException(status_code=400, detail="Advanced device is Chrome-engine only")
    profile_dir = os.path.join(os.getcwd(), DATA_DIR, name)
    persona = chrome_persona.load(profile_dir)
    if persona is None:
        raise HTTPException(status_code=400, detail="Open the profile once first")
    return persona, profile_dir


@router.get(
    "/{name}/device",
    response_model=DeviceResponse,
    responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def get_device(
    name: str,
    pm: IProfileManager = Depends(get_profile_manager),
) -> DeviceResponse:
    """The stable device this profile presents (seed, brand, UA, WebRTC, geo...)."""
    profile = require_profile(name, pm)
    persona, _ = _require_chrome_device(name, pm)
    return DeviceResponse(
        name=name,
        engine=profile.engine,
        seed=persona.seed,
        platform=persona.platform,
        platform_version=persona.platform_version,
        brand=persona.brand,
        hardware_concurrency=persona.hardware_concurrency,
        timezone=persona.timezone,
        locale=persona.locale,
        user_agent=persona.user_agent,
        webrtc=persona.webrtc,
        geo=persona.geo,
    )


@router.patch(
    "/{name}/device",
    response_model=DeviceResponse,
    responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def update_device(
    name: str,
    body: DeviceUpdate,
    pm: IProfileManager = Depends(get_profile_manager),
    bl: IBrowserLauncher = Depends(get_browser_launcher),
    bus: EventBus = Depends(get_event_bus),
) -> DeviceResponse:
    """Change device fields (takes effect on next launch)."""
    from chrome_engine import persona as chrome_persona

    require_profile(name, pm)
    _require_stopped(name, bl, "changing the device")
    _, profile_dir = _require_chrome_device(name, pm)
    supplied = body.model_dump(exclude_unset=True)
    if "hardware_concurrency" in supplied and supplied["hardware_concurrency"] is not None:
        try:
            supplied["hardware_concurrency"] = int(supplied["hardware_concurrency"])
        except (TypeError, ValueError) as e:
            raise HTTPException(status_code=400, detail="hardware_concurrency must be 1..64") from e
    try:
        chrome_persona.update_fields(profile_dir, **supplied)
    except chrome_persona.PersonaError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    bus.emit()
    return get_device(name, pm)


@router.post(
    "/{name}/device/regenerate",
    response_model=DeviceResponse,
    responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def regenerate_device(
    name: str,
    pm: IProfileManager = Depends(get_profile_manager),
    bl: IBrowserLauncher = Depends(get_browser_launcher),
    bus: EventBus = Depends(get_event_bus),
) -> DeviceResponse:
    """New random device seed (sites see a different machine; expect re-logins)."""
    from chrome_engine import persona as chrome_persona

    require_profile(name, pm)
    _require_stopped(name, bl, "changing the device")
    _, profile_dir = _require_chrome_device(name, pm)
    try:
        chrome_persona.regenerate_seed(profile_dir)
    except chrome_persona.PersonaError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    bus.emit()
    return get_device(name, pm)
