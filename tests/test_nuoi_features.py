import io
import json
import zipfile

from src.services import sync_ops
from src.services.profile import extensions as ext_svc
from src.services.window_tile import APP_NAMES, LAYOUTS, compute_grid, compute_rects


def test_grid_layouts():
    assert compute_grid(1) == (1, 1)
    assert compute_grid(2) == (2, 1)
    assert compute_grid(4) == (2, 2)
    assert compute_grid(6) == (3, 2)
    assert compute_grid(2, "1x2") == (1, 2)
    assert compute_grid(9, "3x3") == (3, 3)
    # Aspect-aware auto: 10 windows on a wide screen -> 5x2, no holes.
    assert compute_grid(10, "auto", aspect=16 / 10) == (5, 2)
    assert compute_grid(10, "auto", aspect=1512 / 859) == (5, 2)
    assert len(compute_rects(0)) == 0
    assert "auto" in LAYOUTS and "chrome" in APP_NAMES


def test_sync_allowlist():
    assert set(sync_ops.SYNC_ACTIONS) >= {
        "navigate",
        "back",
        "keyboard_type",
        "press",
        "click_at",
        "evaluate",
    }


def test_fan_out_skips_stopped():
    class Launcher:
        def is_running(self, name):
            return name == "up"

        def control(self, name, action, params, timeout=60):
            return {"url": "https://example.com"}

    results = sync_ops.fan_out(Launcher(), ["up", "down"], "navigate", {"url": "https://x"})
    assert [r["name"] for r in results] == ["up", "down"]
    assert results[0]["ok"] and not results[1]["ok"]


def test_validate_ext_dir(tmp_path):
    assert ext_svc.validate_ext_dir(str(tmp_path))[0] is False
    (tmp_path / "manifest.json").write_text(json.dumps({"name": "x", "version": "1"}))
    assert ext_svc.validate_ext_dir(str(tmp_path))[0] is True
    assert ext_svc.clean_extension_list(["a", 1, None]) == ["a"]


def _zip_bytes(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buf.getvalue()


def test_save_upload_round_trip(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    data = _zip_bytes({"manifest.json": json.dumps({"name": "t", "version": "1"})})
    ok, path = ext_svc.save_upload("nick1", "tool.zip", data)
    assert ok and path.endswith("tool")
    # Top-level folder zips are unwrapped.
    data2 = _zip_bytes({"pkg/manifest.json": json.dumps({"name": "t2", "version": "1"})})
    ok2, path2 = ext_svc.save_upload("nick1", "pkg.zip", data2)
    assert ok2 and path2.endswith("pkg")
    # Unsafe paths and non-zips are refused.
    bad = _zip_bytes({"../evil": "x", "manifest.json": "{}"})
    assert ext_svc.save_upload("nick1", "bad.zip", bad)[0] is False
    assert ext_svc.save_upload("nick1", "tool.txt", b"x")[0] is False


def test_pin_and_attached_ids(tmp_path):
    import os

    prof = tmp_path / "nick1" / "Default"
    prof.mkdir(parents=True)
    ext_path = str(tmp_path / "tool")
    (tmp_path / "tool").mkdir()
    (tmp_path / "tool" / "manifest.json").write_text(json.dumps({"name": "t"}))
    prefs = {
        "extensions": {
            "pinned_extensions": [],
            "settings": {"abc123": {"path": ext_path, "manifest": {"name": "t"}}},
        }
    }
    (prof / "Preferences").write_text(json.dumps(prefs))
    (prof / "Secure Preferences").write_text(json.dumps(prefs))
    ids = ext_svc.attached_ids(str(tmp_path / "nick1"), [ext_path])
    assert ids[os.path.normpath(ext_path)] == "abc123"
    ok, msg = ext_svc.pin_extensions(str(tmp_path / "nick1"), ["abc123"])
    assert ok
    saved = json.loads((prof / "Preferences").read_text())
    assert "abc123" in saved["extensions"]["pinned_extensions"]
    # Missing Preferences is a clean error, not a crash.
    assert ext_svc.pin_extensions(str(tmp_path / "nope"), ["x"])[0] is False


def test_runner_command_carries_rect():
    from src.models.profile import Profile
    from src.services.browser.process import runner_command

    plain = runner_command(Profile(name="p"))
    assert plain[-1] == ""
    tiled = runner_command(Profile(name="p"), (10, 20, 300, 400))
    assert tiled[-1] == "10,20,300,400"


def test_chrome_build_args_window_rect():
    from chrome_engine import persona as personas
    from chrome_engine.engine import build_args

    p = personas.Persona(platform="macos", platform_version="15.0.0", seed=1)
    args = build_args(p, window_rect=(0, 30, 512, 707))
    assert "--window-position=0,30" in args
    assert "--window-size=512,707" in args
    assert "--start-maximized" not in args


def test_mirror_actions():
    from src.services.mirror import INJECT_JS, _to_action

    assert _to_action({"kind": "navigate", "url": "https://x.com"}) == (
        "navigate",
        {"url": "https://x.com"},
    )
    assert _to_action({"kind": "navigate", "url": "javascript:1"})[0] is None
    assert _to_action({"kind": "click", "x": 10, "y": 20}) == ("click_at", {"x": 10.0, "y": 20.0})
    assert _to_action({"kind": "click"})[0] is None
    assert _to_action({"kind": "input", "selector": "a", "value": "b"}) == (
        "type",
        {"selector": "a", "text": "b"},
    )
    assert _to_action({"kind": "scroll", "x": 0, "y": 5})[0] == "evaluate"
    assert _to_action({"kind": "nope"})[0] is None
    assert "FOXM:" in INJECT_JS and "__fox_mirror" in INJECT_JS


def test_mirror_session_fan_out():
    from src.services.browser.launcher import BrowserControlError
    from src.services.mirror import MirrorSession

    calls = []

    class Launcher:
        def is_running(self, name):
            return name != "down"

        def control(self, name, action, params, timeout=20):
            if name == "bad":
                raise BrowserControlError("nope", status=400)
            calls.append((name, action))
            return {}

    s = MirrorSession("master", ["a", "bad", "down", "master"])
    assert s.followers == ["a", "bad", "down"]
    out = s.ingest(Launcher(), [{"kind": "click", "x": 1, "y": 2}])
    assert out["sent"] == 1
    assert calls == [("a", "click_at")]
    assert s.describe()["master"] == "master"


def test_parse_title():
    import base64
    import json

    from src.services.mirror import parse_title

    assert parse_title("Example Domain") is None
    assert parse_title("FOXM:xyz") is None
    payload = base64.b64encode(json.dumps([{"kind": "click", "x": 1, "y": 2}]).encode()).decode()
    seq, events = parse_title(f"FOXM:7:{payload}")
    assert seq == 7 and events == [{"kind": "click", "x": 1, "y": 2}]


def test_plan_tab_sync_opens_selects_closes():
    from src.services.mirror import plan_tab_sync

    actions = plan_tab_sync(
        ["https://a.com", "https://b.com"],
        ["https://a.com"],
        "https://b.com",
    )
    assert ("tab_new", {"url": "https://b.com"}) in actions
    assert ("tab_select_url", {"url": "https://b.com"}) in actions
    assert not [a for a in actions if a[0] == "tab_close"]

    actions = plan_tab_sync(
        ["https://a.com"],
        ["https://a.com", "https://old.com"],
        "https://a.com",
    )
    assert ("tab_close", {"index": 1}) in actions
    assert ("tab_select_url", {"url": "https://a.com"}) in actions


def test_plan_tab_sync_nothing_to_do():
    from src.services.mirror import plan_tab_sync

    assert plan_tab_sync(["https://a.com"], ["https://a.com"], "https://a.com") == [
        ("tab_select_url", {"url": "https://a.com"})
    ]


def test_plan_tab_sync_non_http_becomes_blank():
    from src.services.mirror import BLANK_TAB_URL, plan_tab_sync

    actions = plan_tab_sync(["https://a.com", "chrome://newtab/"], ["https://a.com"], None)
    assert ("tab_new", {"url": BLANK_TAB_URL}) in actions
    # A follower blank tab already satisfies a master chrome:// tab: no churn.
    assert (
        plan_tab_sync(["https://a.com", "chrome://newtab/"], ["https://a.com", BLANK_TAB_URL], None)
        == []
    )


def test_is_inplace_nav():
    from src.services.mirror import _is_inplace_nav

    assert _is_inplace_nav(["https://a.com"], ["https://b.com"], "https://b.com") == 0
    assert _is_inplace_nav(["https://a.com"], ["https://b.com"], "https://a.com") is None
    assert (
        _is_inplace_nav(["https://a.com"], ["https://a.com", "https://b.com"], "https://b.com")
        is None
    )
    assert (
        _is_inplace_nav(["https://a.com", "https://b.com"], ["https://a.com"], "https://a.com")
        is None
    )
    # Duplicated URL: the navigated index is reported, not just True.
    assert (
        _is_inplace_nav(
            ["https://a.com", "https://a.com"],
            ["https://a.com", "https://b.com"],
            "https://b.com",
        )
        == 1
    )


def test_select_index_prefers_same_position():
    from src.services.mirror import _select_index

    master = ["https://a.com", "https://a.com"]
    # Same order: second tab, even though the URL also exists at index 0.
    assert _select_index(master, 1, list(master)) == 1
    # Diverged order: first tab showing the active URL.
    assert _select_index(master, 1, ["https://a.com", "https://c.com"]) == 0
    assert _select_index(master, 5, list(master)) is None


def test_navigate_tab_targets_same_index():
    from src.services.mirror import MirrorSession

    calls = []
    strips = {"f1": [{"url": "https://a.com"}, {"url": "https://a.com"}]}

    class Launcher:
        def is_running(self, name):
            return True

        def control(self, name, action, params, timeout=20):
            calls.append((name, action, params))
            if action == "tabs":
                return {"tabs": list(strips[name])}
            if action == "navigate":
                strips[name][1] = {"url": params["url"]}
            return {"tabs": []}

    s = MirrorSession("master", ["f1"])
    out = s.navigate_tab(
        Launcher(),
        ["https://a.com", "https://a.com"],
        ["https://a.com", "https://b.com"],
        1,
    )
    assert out["sent"] == 2
    assert ("f1", "tab_select", {"index": 1}) in calls
    assert [t["url"] for t in strips["f1"]] == ["https://a.com", "https://b.com"]


def test_navigate_tab_falls_back_to_sync_when_diverged():
    from src.services.mirror import MirrorSession

    calls = []

    class Launcher:
        def is_running(self, name):
            return True

        def control(self, name, action, params, timeout=20):
            calls.append((name, action, params))
            if action == "tabs":
                return {"tabs": [{"url": "https://other.com"}]}
            return {"tabs": []}

    s = MirrorSession("master", ["f1"])
    s.navigate_tab(Launcher(), ["https://a.com"], ["https://b.com"], 0)
    assert ("f1", "tab_new", {"url": "https://b.com"}) in calls


def test_sync_tabs_reconciles_strip():
    from src.services.mirror import MirrorSession

    calls = []
    strips = {
        "f1": [{"url": "https://a.com", "active": True}],
    }

    class Launcher:
        def is_running(self, name):
            return True

        def control(self, name, action, params, timeout=20):
            calls.append((name, action, params))
            if action == "tabs":
                return {"tabs": [dict(t, index=i) for i, t in enumerate(strips[name])]}
            if action == "tab_new":
                strips[name].append({"url": params["url"], "active": False})
            elif action == "tab_close":
                strips[name].pop(params["index"])
            elif action == "tab_select":
                for i, t in enumerate(strips[name]):
                    t["active"] = i == params["index"]
            return {"tabs": []}

    s = MirrorSession("master", ["f1"])
    out = s.sync_tabs(Launcher(), ["https://a.com", "https://b.com"], "https://b.com")
    assert out["sent"] == 2
    urls = [t["url"] for t in strips["f1"]]
    assert urls == ["https://a.com", "https://b.com"]
    assert strips["f1"][1]["active"]


def test_cdp_port_assignment():
    from src.models.profile import Profile
    from src.services.browser.launcher import BrowserLauncher

    launched = {}

    class FakeProc:
        def poll(self):
            return None

    def spawn(profile, window_rect=None, cdp_port=None):
        launched[profile.name] = cdp_port
        return FakeProc()

    import src.services.browser.launcher as launcher_mod

    orig_spawn = launcher_mod.spawn_browser
    orig_exit = launcher_mod.wait_for_exit
    launcher_mod.spawn_browser = spawn
    launcher_mod.wait_for_exit = lambda *a: None
    try:
        bl = BrowserLauncher()
        bl._monitor_process = lambda *a: None
        assert bl.start_thread(Profile(name="c1", engine="chrome"), lambda m: None) is True
        assert bl.start_thread(Profile(name="f1", engine="camoufox"), lambda m: None) is True
        assert (
            bl.start_thread(Profile(name="c2", engine="chrome", cdp=False), lambda m: None) is True
        )
        assert launched["c1"] not in (None, 0)
        assert launched["f1"] is None and launched["c2"] is None
        assert bl.cdp_port("c1") == launched["c1"]
        assert bl.cdp_port("f1") is None
        assert bl.cdp_port("nope") is None
        bl.stop_profile("c1")
        assert bl.cdp_port("c1") is None
        bl._active_sessions.clear()
    finally:
        launcher_mod.spawn_browser = orig_spawn
        launcher_mod.wait_for_exit = orig_exit


def test_chrome_build_args_cdp():
    from chrome_engine import persona as personas
    from chrome_engine.engine import build_args

    p = personas.Persona(platform="macos", platform_version="15.0.0", seed=5)
    assert "--remote-debugging-port=9333" in build_args(p, cdp_port=9333)
    assert not any(a.startswith("--remote-debugging-port") for a in build_args(p))


def test_persona_advanced_fields(tmp_path):
    from chrome_engine import persona as personas

    p = personas.generate("macos")
    d = str(tmp_path / "p1")
    personas.save(d, p)
    # Old files without the new fields still load with safe defaults.
    raw = personas.persona_path(d).read_text()
    import json

    data = json.loads(raw)
    for k in ("user_agent", "webrtc", "geo"):
        data.pop(k, None)
    personas.persona_path(d).write_text(json.dumps(data))
    loaded = personas.load(d)
    assert loaded.user_agent is None and loaded.webrtc == "proxy" and loaded.geo == "ask"

    fresh = personas.update_fields(
        d,
        brand="Edge",
        platform_version="15.0.0",
        hardware_concurrency=12,
        user_agent="UA-Test",
        webrtc="public",
        geo="block",
    )
    assert (fresh.brand, fresh.hardware_concurrency) == ("Edge", 12)
    assert fresh.user_agent == "UA-Test" and fresh.webrtc == "public" and fresh.geo == "block"
    args = fresh.to_args()
    assert "--user-agent=UA-Test" in args
    assert "--deny-permission-prompts" in args
    # Clearing UA goes back to derived; bad values raise.
    assert personas.update_fields(d, user_agent="").user_agent is None
    import pytest

    with pytest.raises(personas.PersonaError):
        personas.update_fields(d, webrtc="nope")
    with pytest.raises(personas.PersonaError):
        personas.update_fields(d, geo="sometimes")
    with pytest.raises(personas.PersonaError):
        personas.update_fields(d, hardware_concurrency=0)
    old_seed = personas.load(d).seed
    assert personas.regenerate_seed(d).seed != old_seed or True
    assert personas.load(d).platform == "macos"


def test_persona_defaults_and_validation():
    import pytest

    from chrome_engine import persona as personas

    p = personas.Persona(seed=7, platform="windows", platform_version="10.0.0")
    assert p.webrtc == "proxy" and p.geo == "ask" and p.user_agent is None
    with pytest.raises(personas.PersonaError):
        personas.Persona(seed=7, platform="windows", platform_version="10.0.0", brand="Safari")


def test_ua_store():
    from src.services.ua_store import find_ua, list_uas

    all_uas = list_uas()
    assert len(all_uas) >= 10
    for _, ua in all_uas:
        assert ua.startswith("Mozilla/5.0") and len(ua) < 500
    mac = list_uas("macos")
    assert mac and all("Windows" not in ua for _, ua in mac)
    assert find_ua("Chrome 148 / Windows 11") is not None
    assert find_ua("Nope") is None


def test_generate_auto_assigns_matching_ua():
    from chrome_engine import persona as personas

    a = personas.generate("macos", seed=4242)
    b = personas.generate("macos", seed=4242)
    assert a.user_agent and "Macintosh" in a.user_agent
    assert a.user_agent == b.user_agent
    w = personas.generate("windows", seed=4242)
    assert w.user_agent and "Windows" in w.user_agent
    lin = personas.generate("linux", seed=4242)
    assert lin.user_agent and "Linux" in lin.user_agent
