from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """No ambient BOTTLE_/OPENHOST_ vars leaking in from the developer's shell.

    Without this, a developer who exports a real router URL to poke at the app by
    hand gets a different test result than CI does, and the "not connected"
    degraded path -- the one the router sees first on every fresh deploy -- would
    never be exercised locally.
    """
    for name in (
        "BOTTLE_ROUTER_URL",
        "OPENHOST_ROUTER_URL",
        "BOTTLE_APP_TOKEN",
        "OPENHOST_APP_TOKEN",
        "SLEEP_DASH_SHORTNAME",
        "SLEEP_DASH_SESSION_LIMIT",
        "SLEEP_DASH_CACHE_TTL_SECONDS",
        "SLEEP_DASH_NAP_MINUTES",
        "SLEEP_DASH_HR_GAP_SECONDS",
    ):
        monkeypatch.delenv(name, raising=False)
    yield
