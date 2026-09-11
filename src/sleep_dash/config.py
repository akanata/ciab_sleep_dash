"""Settings, read from the environment exactly once.

This module does no I/O beyond reading a mapping, and it never raises for a missing
router URL or app token. That is deliberate: the spec's ``HealthDataClient.__init__``
does an unguarded ``os.environ["OPENHOST_ROUTER_URL"]``, and letting that KeyError
escape during ``create_app()`` would mean ``/health`` never answers and the router
restart-loops the container. "Not connected to a health service" is a state this app
renders as a page, not a startup failure.
"""

import os
from collections.abc import Mapping

import attrs

DEFAULT_SHORTNAME = "health"

# A count, not a date range: the sleep-sessions request deliberately carries no
# start/end (see health.py), so this is the only bound on the payload. Each session
# brings a stage timeline plus intra-night heart rate and HRV, and the spec client's
# httpx timeout is hardcoded at 30s, so this has to stay modest.
DEFAULT_SESSION_LIMIT = 30

DEFAULT_CACHE_TTL_SECONDS = 300.0

# Below this a session is treated as a nap and kept out of the night list. Matches
# health-dashboard, which filters sessions under 30 minutes from its sleep panels.
DEFAULT_NAP_MINUTES = 30.0

# Consecutive heart-rate samples further apart than this are a gap, not a trend:
# the drawn line breaks and the per-minute readout reads as missing. Matches
# health-dashboard's GAP_THRESHOLD of 600 seconds.
DEFAULT_HR_GAP_SECONDS = 600.0


class ConfigError(Exception):
    """The environment does not describe a runnable configuration."""


@attrs.frozen
class Settings:
    """Everything this app reads from its environment."""

    router_url: str | None = None
    app_token: str | None = None
    shortname: str = DEFAULT_SHORTNAME
    session_limit: int = DEFAULT_SESSION_LIMIT
    cache_ttl_seconds: float = DEFAULT_CACHE_TTL_SECONDS
    nap_minutes: float = DEFAULT_NAP_MINUTES
    hr_gap_seconds: float = DEFAULT_HR_GAP_SECONDS

    @property
    def connected(self) -> bool:
        """Whether there is enough configuration to build a health client at all.

        Both halves are required: a URL with no token would send
        ``Authorization: Bearer None`` and be rejected by the router.
        """
        return bool(self.router_url and self.app_token)


def _str_from(env: Mapping[str, str], *names: str) -> str | None:
    """First non-empty value among ``names``, which are given newest-first.

    Cloud in a Bottle renamed OPENHOST_* to BOTTLE_*, but deployed apps still export
    only the old name and the spec's own client still reads it, so both are accepted
    with the new one winning.
    """
    for name in names:
        value = env.get(name, "").strip()
        if value:
            return value
    return None


def _int_from(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a whole number, got {raw!r}.") from None
    if value <= 0:
        raise ConfigError(f"{name} must be greater than zero, got {value}.")
    return value


def _float_from(env: Mapping[str, str], name: str, default: float) -> float:
    raw = env.get(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a number, got {raw!r}.") from None
    if value <= 0:
        raise ConfigError(f"{name} must be greater than zero, got {value}.")
    return value


def settings_from_env(env: Mapping[str, str] | None = None) -> Settings:
    """Build Settings from ``env``, defaulting to the process environment."""
    env = os.environ if env is None else env
    return Settings(
        router_url=_str_from(env, "BOTTLE_ROUTER_URL", "OPENHOST_ROUTER_URL"),
        app_token=_str_from(env, "BOTTLE_APP_TOKEN", "OPENHOST_APP_TOKEN"),
        shortname=_str_from(env, "SLEEP_DASH_SHORTNAME") or DEFAULT_SHORTNAME,
        session_limit=_int_from(env, "SLEEP_DASH_SESSION_LIMIT", DEFAULT_SESSION_LIMIT),
        cache_ttl_seconds=_float_from(
            env, "SLEEP_DASH_CACHE_TTL_SECONDS", DEFAULT_CACHE_TTL_SECONDS
        ),
        nap_minutes=_float_from(env, "SLEEP_DASH_NAP_MINUTES", DEFAULT_NAP_MINUTES),
        hr_gap_seconds=_float_from(env, "SLEEP_DASH_HR_GAP_SECONDS", DEFAULT_HR_GAP_SECONDS),
    )
