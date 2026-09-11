"""The gateway to the health-data service.

This is the ONLY module that may import ``health_data_service.client``, touch httpx,
or read credentials. Everything downstream of it works on plain spec types and pure
functions, which is what lets the whole chart be unit-tested without HTTP.

Two transforms happen here and nowhere else, both defences against verified failure
modes in the spec's own client -- see ``_structure_stage`` and ``_aware``.
"""

import asyncio
import datetime as dt
import logging
from collections.abc import Callable
from typing import Protocol

import attrs
import httpx
from health_data_service.client import HealthDataClient
from health_data_service.client import converter
from health_data_service.request_types import SleepSessionsRequest
from health_data_service.sleep_types import SleepSession
from health_data_service.sleep_types import SleepStage

from sleep_dash.config import Settings

logger = logging.getLogger(__name__)


class HealthUnavailable(Exception):
    """There is no health service configured for this app to read. -> a 200 page."""


class HealthTransportError(Exception):
    """The router or a provider could not be reached. -> a 503 page."""


def _structure_stage(value: object, _: type) -> SleepStage:
    """Read an unrecognised stage as UNKNOWN rather than killing the whole response.

    Verified against the installed spec: ``converter.structure`` raises on an
    unknown enum value, and ``get_sleep_sessions_merged`` structures every
    provider's sessions in ONE call -- so a single bad sample from a single provider
    blanks the entire dashboard, including every other provider's good nights::

        value='deep' -> ok       value='core' -> IterableValidationError
        batch of 2 (1 good, 1 bad) -> IterableValidationError, ALL sessions lost

    Apple Health's "core", and any n1/n2/n3 polysomnography vocabulary, do exactly
    this. So does any stage the spec adds after this app is deployed.
    """
    try:
        return SleepStage(value)
    except ValueError:
        logger.warning("Unrecognised sleep stage %r from a provider; reading as unknown.", value)
        return SleepStage.UNKNOWN


# Registered at import, on the spec's module-level converter singleton. That is
# shared process-wide state, which is acceptable only because this app is the sole
# consumer of it in this process -- so the registration stays confined to this
# module, and test_health.py pins the behaviour.
converter.register_structure_hook(SleepStage, _structure_stage)


def _aware(timestamp: dt.datetime) -> dt.datetime:
    """A naive timestamp is a provider that forgot to say UTC, not local time.

    Verified: the spec's ``_to_params`` serialises datetimes with ``str(v)``, which
    renders a space separator rather than a T. A provider echoing that back produces
    naive datetimes that structure perfectly cleanly and then raise
    ``TypeError: can't subtract offset-naive and offset-aware datetimes`` hundreds of
    lines away, inside the geometry layer. Normalising at this boundary is the only
    place the cause is still visible.
    """
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=dt.UTC)
    return timestamp.astimezone(dt.UTC)


def _normalise(session: SleepSession) -> SleepSession:
    """Return ``session`` with every timestamp an aware UTC instant."""
    stages = session.stages
    if stages is not None:
        stages = attrs.evolve(
            stages,
            samples=[
                attrs.evolve(
                    sample,
                    timestamp=_aware(sample.timestamp),
                    end_timestamp=_aware(sample.end_timestamp),
                )
                for sample in stages.samples
            ],
        )
    heart_rate = session.heart_rate
    if heart_rate is not None:
        heart_rate = attrs.evolve(
            heart_rate,
            samples=[
                attrs.evolve(sample, timestamp=_aware(sample.timestamp))
                for sample in heart_rate.samples
            ],
        )
    return attrs.evolve(
        session,
        start=_aware(session.start),
        end=_aware(session.end),
        stages=stages,
        heart_rate=heart_rate,
    )


@attrs.frozen
class ProviderInfo:
    app_id: str
    app_name: str
    status: str

    @property
    def is_running(self) -> bool:
        return self.status == "running"


@attrs.frozen
class Snapshot:
    """One fetch of everything the dashboard needs."""

    sessions: tuple[SleepSession, ...]
    providers: tuple[ProviderInfo, ...]
    fetched_at: dt.datetime
    # discover_providers() returned nothing. NOT the same as "there are no
    # providers": _fan_out falls back to a single un-targeted call through the
    # router in that case, so data may still have arrived. The footer must not
    # report an outage it cannot actually see.
    discovery_empty: bool = False

    @property
    def running(self) -> tuple[ProviderInfo, ...]:
        return tuple(p for p in self.providers if p.is_running)

    @property
    def contributing(self) -> frozenset[str]:
        """The provider names that actually returned at least one session."""
        return frozenset(s.source for s in self.sessions if s.source)


class HealthGateway(Protocol):
    """What the routes need. Implemented for real below, and faked in tests."""

    async def snapshot(self) -> Snapshot: ...


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


@attrs.define
class RouterHealthGateway:
    """Reads sleep sessions through the Cloud in a Bottle router, with a TTL cache.

    The cache is single-flight behind a lock so that navigating between nights --
    which re-renders from the same snapshot -- costs no extra round trips, and a
    refresh cannot fan out to every provider again.
    """

    settings: Settings
    clock: Callable[[], dt.datetime] = _utcnow
    _cached: Snapshot | None = attrs.field(default=None, init=False)
    _lock: asyncio.Lock = attrs.field(factory=asyncio.Lock, init=False)

    async def snapshot(self) -> Snapshot:
        if not self.settings.connected:
            raise HealthUnavailable("No health data service is configured for this app.")
        async with self._lock:
            cached = self._cached
            if cached is not None:
                age = (self.clock() - cached.fetched_at).total_seconds()
                if age < self.settings.cache_ttl_seconds:
                    return cached
            fetched = await self._fetch()
            self._cached = fetched
            return fetched

    async def _fetch(self) -> Snapshot:
        try:
            async with HealthDataClient(
                router_url=self.settings.router_url,
                app_token=self.settings.app_token,
                shortname=self.settings.shortname,
            ) as client:
                raw_providers = await client.discover_providers()
                # Deliberately no start/end. The spec's _to_params renders datetimes
                # with str(v) -- a space separator, not a T -- and a provider parsing
                # strictly answers 400, which _fan_out reads as "this provider has
                # nothing". limit alone is the only call shape verified to work.
                sessions = await client.get_sleep_sessions_merged(
                    SleepSessionsRequest(limit=self.settings.session_limit)
                )
        except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPError) as exc:
            raise HealthTransportError(f"Could not reach the health service: {exc}") from exc

        providers = tuple(
            ProviderInfo(
                app_id=str(p.get("app_id", "")),
                app_name=str(p.get("app_name", "")),
                status=str(p.get("status", "")),
            )
            for p in raw_providers
        )
        return Snapshot(
            sessions=tuple(_normalise(s) for s in sessions),
            providers=providers,
            fetched_at=self.clock(),
            discovery_empty=not raw_providers,
        )
