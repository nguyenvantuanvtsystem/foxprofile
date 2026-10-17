"""Per-profile browser extensions (Chrome engine).

Extensions are unpacked directories containing a manifest.json. They are
stored machine-locally: uploads land under DATA_DIR/extensions/<profile>/,
and absolute paths elsewhere on the machine are referenced as-is.
"""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import tempfile
import zipfile

from ...core.config import DATA_DIR
from ...core.logging import get_logger
from ...models.profile import MAX_EXTENSIONS

logger = get_logger("profile.extensions")


def validate_ext_dir(path: str) -> tuple[bool, str]:
    """An unpacked extension dir must exist and carry a readable manifest.json."""
    if not path or not isinstance(path, str):
        return False, "empty path"
    if not os.path.isdir(path):
        return False, f"not a directory: {path}"
    manifest = os.path.join(path, "manifest.json")
    if not os.path.isfile(manifest):
        return False, "missing manifest.json (need an unpacked extension folder)"
    try:
        data = json.loads(pathlib.Path(manifest).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return False, f"unreadable manifest.json: {e}"
    if not isinstance(data, dict) or "name" not in data:
        return False, "manifest.json has no extension name"
    return True, ""


def clean_extension_list(values: object) -> list[str]:
    """Loaded profiles.json / API input -> at most MAX_EXTENSIONS valid strings."""
    if not isinstance(values, list):
        return []
    return [v for v in values if isinstance(v, str) and v][:MAX_EXTENSIONS]


def attached_ids(profile_dir: str, paths: list[str]) -> dict[str, str]:
    """Map attached dir -> installed extension id, read from Secure Preferences.

    Unpacked IDs are derived from the install path, so after one launch the id
    is stable and can be pinned. Unknown paths map to "".
    """
    wanted = {os.path.normpath(p): "" for p in paths}
    for fname in ("Secure Preferences", "Preferences"):
        try:
            data = json.loads(
                pathlib.Path(profile_dir, "Default", fname).read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            continue
        settings = data.get("extensions", {}).get("settings", {})
        if not isinstance(settings, dict):
            continue
        for ext_id, info in settings.items():
            if not isinstance(info, dict):
                continue
            p = info.get("path")
            if isinstance(p, str) and os.path.normpath(p) in wanted:
                wanted[os.path.normpath(p)] = ext_id
    return wanted


def pin_extensions(profile_dir: str, ids: list[str]) -> tuple[bool, str]:
    """Pin extension IDs to the toolbar (Preferences, browser must be stopped).

    Chrome reads extensions.pinned_extensions at startup; editing while the
    browser runs is pointless (it rewrites the file on exit). Returns
    (True, pinned_count) or (False, error).
    """
    prefs = os.path.join(profile_dir, "Default", "Preferences")
    try:
        data = json.loads(pathlib.Path(prefs).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return False, f"cannot read Preferences (open the profile once first?): {e}"
    if not isinstance(data, dict):
        return False, "Preferences is not an object"
    ext = data.get("extensions")
    if not isinstance(ext, dict):
        ext = {}
        data["extensions"] = ext
    pinned = ext.get("pinned_extensions")
    if not isinstance(pinned, list):
        pinned = ext["pinned_extensions"] = []
    added = 0
    for ext_id in ids:
        if ext_id and ext_id not in pinned:
            pinned.append(ext_id)
            added += 1
    try:
        tmp = prefs + ".foxprofile-tmp"
        pathlib.Path(tmp).write_text(json.dumps(data), encoding="utf-8")
        os.replace(tmp, prefs)
    except OSError as e:
        return False, f"cannot write Preferences: {e}"
    return True, f"{added} pinned"


def _ext_root(profile_name: str) -> pathlib.Path:
    return pathlib.Path(DATA_DIR) / "extensions" / profile_name


def _safe_member(root: pathlib.Path, member: str) -> pathlib.Path | None:
    target = (root / member).resolve()
    try:
        if not target.is_relative_to(root.resolve()):
            return None
    except (OSError, ValueError):
        return None
    return target


def save_upload(profile_name: str, filename: str, data: bytes) -> tuple[bool, str]:
    """Store an uploaded .zip as an unpacked extension dir for a profile.

    Returns (True, dir_path) or (False, error). The zip must contain a
    manifest.json at its root (a single top-level folder is unwrapped).
    """
    if not filename.lower().endswith(".zip"):
        return False, "only .zip uploads are accepted"
    if len(data) > 100 * 1024 * 1024:
        return False, "file too large (100 MB max)"
    stem = "".join(
        c for c in os.path.splitext(os.path.basename(filename))[0] if c.isalnum() or c in "-_"
    )[:60]
    if not stem:
        return False, "bad file name"
    dest = _ext_root(profile_name) / stem
    if dest.exists():
        return False, f"extension '{stem}' already uploaded (remove it first)"
    try:
        dest.mkdir(parents=True, exist_ok=False)
        with tempfile.TemporaryDirectory() as tmp:
            zpath = os.path.join(tmp, "upload.zip")
            with open(zpath, "wb") as f:
                f.write(data)
            try:
                with zipfile.ZipFile(zpath) as zf:
                    names = [n for n in zf.namelist() if not n.endswith("/")]
                    if not names:
                        return False, "empty zip"
                    for n in names:
                        target = _safe_member(dest, n)
                        if target is None:
                            shutil.rmtree(dest, ignore_errors=True)
                            return False, f"unsafe path in zip: {n}"
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with zf.open(n) as src, open(target, "wb") as dst:
                            shutil.copyfileobj(src, dst)
            except zipfile.BadZipFile:
                shutil.rmtree(dest, ignore_errors=True)
                return False, "invalid zip file"
        # Unwrap a single top-level folder (GitHub "Download ZIP" layout).
        entries = [e for e in dest.iterdir()]
        if len(entries) == 1 and entries[0].is_dir() and not (dest / "manifest.json").exists():
            inner = entries[0]
            tmp_move = dest.parent / (dest.name + ".tmp")
            if tmp_move.exists():
                shutil.rmtree(tmp_move)
            inner.rename(tmp_move)
            shutil.rmtree(dest)
            tmp_move.rename(dest)
        ok, err = validate_ext_dir(str(dest))
        if not ok:
            shutil.rmtree(dest, ignore_errors=True)
            return False, err
        logger.info("Extension uploaded for %s: %s", profile_name, dest)
        return True, str(dest)
    except OSError as e:
        shutil.rmtree(dest, ignore_errors=True)
        return False, f"cannot store upload: {e}"
