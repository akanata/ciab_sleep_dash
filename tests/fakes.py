"""Stand-ins for the health service.

Hand-written rather than unittest.mock: these record what they were asked for, so
the calling contract is itself testable (that the TTL cache really does collapse two
page loads into one round trip, that the client is never built without credentials).
"""

import datetime as dt

import attrs
from health_data_service.sleep_types import SleepSession

from sleep_dash.health import ProviderInfo
from sleep_dash.health import Snapshot


def empty_snapshot(
    *,
    providers: tuple[ProviderInfo, ...] = (),
    discovery_empty: bool = False,
    fetched_at: dt.datetime | None = None,
) -> Snapshot:
    """A successful fetch that found no sleep sessions."""
    return Snapshot(
        sessions=(),
        providers=providers,
        fetched_at=fetched_at or dt.datetime(2026, 9, 10, 12, 0, tzinfo=dt.UTC),
        discovery_empty=discovery_empty,
    )


def snapshot_of(
    *sessions: SleepSession,
    providers: tuple[ProviderInfo, ...] = (),
    discovery_empty: bool = False,
    fetched_at: dt.datetime | None = None,
) -> Snapshot:
    """A successful fetch carrying the given sessions."""
    return Snapshot(
        sessions=sessions,
        providers=providers,
        fetched_at=fetched_at or dt.datetime(2026, 9, 10, 12, 0, tzinfo=dt.UTC),
        discovery_empty=discovery_empty,
    )


def running(app_name: str, app_id: str = "") -> ProviderInfo:
    return ProviderInfo(app_id=app_id or f"{app_name}-id", app_name=app_name, status="running")


@attrs.define
class FakeHealthGateway:
    """Returns a canned Snapshot, or raises a canned exception, and counts calls."""

    result: Snapshot | Exception
    calls: int = 0

    async def snapshot(self) -> Snapshot:
        self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result
