"""Load local MT5 settings with an explicit demo/live profile."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Final

from dotenv import dotenv_values, load_dotenv

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
VALID_PROFILES: Final[set[str]] = {"demo", "live"}

# Load the selector and shared non-secret settings first.
load_dotenv(PROJECT_ROOT / ".env")
PROFILE = os.getenv("MT5_PROFILE", "demo").strip().lower()
if PROFILE not in VALID_PROFILES:
    raise ValueError(
        f"Invalid MT5_PROFILE={PROFILE!r}; expected one of {sorted(VALID_PROFILES)}"
    )

# Profile files override shared values and are intentionally git-ignored.
PROFILE_FILE = PROJECT_ROOT / f".env.{PROFILE}"
for key, value in dotenv_values(PROFILE_FILE).items():
    if value:
        os.environ[key] = value

ACCOUNT_TYPE = os.getenv("ACCOUNT_TYPE", PROFILE).strip().lower()
if ACCOUNT_TYPE != PROFILE:
    raise ValueError(
        f"ACCOUNT_TYPE={ACCOUNT_TYPE!r} must match selected MT5_PROFILE={PROFILE!r}"
    )


def get_setting(name: str, default: str | None = None) -> str | None:
    """Return a loaded setting without exposing its value in logs."""
    return os.getenv(name, default)
