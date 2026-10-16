from dataclasses import dataclass,field
from pathlib import Path
from typing import Literal

@dataclass(frozen=True)
class AppSettings:
    data_root: Path
    api_token: str = field(repr=False)
    provider_mode: Literal["fake", "real"]
    startup_recovery: bool

    def __post_init__(self):
        if self.provider_mode not in ("fake", "real") or not isinstance(self.startup_recovery, bool):
            raise ValueError("INVALID_APP_SETTINGS")
        minimum=12 if self.provider_mode=='fake' else 32
        if not isinstance(self.api_token, str) or len(self.api_token) < minimum:
            raise ValueError("LOCAL_API_TOKEN_REQUIRED")
        object.__setattr__(self, "data_root", Path(self.data_root).resolve())
