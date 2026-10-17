from dataclasses import asdict, dataclass, field

# Browser engines a profile can run on. A profile keeps its engine for life:
# the two keep incompatible browser data in the same directory.
ENGINES = ("camoufox", "chrome")

# How many extensions a profile may carry (Chrome --load-extension list).
MAX_EXTENSIONS = 10


@dataclass
class Profile:
    name: str
    proxy: str | None = None
    os_type: str = "windows"
    # None = follow the proxy's exit IP (Camoufox geoip); set to pin a value.
    timezone: str | None = None
    locale: str | None = None
    engine: str = "camoufox"
    # Unpacked extension directories, loaded at launch (Chrome engine only).
    extensions: list[str] = field(default_factory=list)
    # Chrome engine: also listen for DevTools Protocol on 127.0.0.1 so
    # automation/AI agents get full control (GPM-style). Nothing attaches
    # by itself, so the fingerprint is unaffected until something does.
    cdp: bool = True

    def to_dict(self) -> dict:
        return asdict(self)
