"""Bundled User-Agent store (GPM-style presets).

Real-world UA strings, no network needed. Keep the list short and current;
drop entries older than ~1 year during maintenance. Custom strings are still
accepted anywhere a UA can be set.
"""

# (label, os_key, ua) — os_key matches persona platforms plus android/ios
# for reference (pick the entry matching the profile's platform).
UA_ENTRIES: tuple[tuple[str, str, str], ...] = (
    (
        "Chrome 148 / Windows 11",
        "windows",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
    ),
    (
        "Chrome 141 / Windows 11",
        "windows",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
    ),
    (
        "Chrome 131 / Windows 10",
        "windows",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    ),
    (
        "Edge 141 / Windows 11",
        "windows",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36 Edg/141.0.0.0",
    ),
    (
        "Firefox 144 / Windows 11",
        "windows",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:144.0) Gecko/20100101 Firefox/144.0",
    ),
    (
        "Chrome 148 / macOS Sequoia",
        "macos",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
    ),
    (
        "Chrome 141 / macOS Sequoia",
        "macos",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
    ),
    (
        "Edge 141 / macOS",
        "macos",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36 Edg/141.0.0.0",
    ),
    (
        "Safari 18 / macOS Sequoia",
        "macos",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/18.4 Safari/605.1.15",
    ),
    (
        "Firefox 144 / macOS",
        "macos",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7; rv:144.0) Gecko/20100101 Firefox/144.0",
    ),
    (
        "Chrome 141 / Ubuntu",
        "linux",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
    ),
    (
        "Firefox 144 / Ubuntu",
        "linux",
        "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:144.0) Gecko/20100101 Firefox/144.0",
    ),
    (
        "Chrome 141 / Android 15",
        "android",
        "Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/141.0.0.0 Mobile Safari/537.36",
    ),
    (
        "Safari / iPhone iOS 18",
        "ios",
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_4 like Mac OS X) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/18.4 Mobile/15E148 Safari/604.1",
    ),
)


def list_uas(os_key: str | None = None) -> list[tuple[str, str]]:
    """[(label, ua)], optionally filtered to a persona platform."""
    if not os_key:
        return [(label, ua) for label, _, ua in UA_ENTRIES]
    return [(label, ua) for label, os, ua in UA_ENTRIES if os == os_key]


def find_ua(label: str) -> str | None:
    for entry_label, _, ua in UA_ENTRIES:
        if entry_label == label:
            return ua
    return None
