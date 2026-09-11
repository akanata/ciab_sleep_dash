"""The gateway, and the two defences it exists to hold.

Both of these were verified against the installed spec before being written, and
both are silent until they are catastrophic: one blanks the dashboard, the other
raises a TypeError hundreds of lines from its cause.
"""

import datetime as dt

import pytest
from health_data_service.client import converter
from health_data_service.data_types import IntervalSample
from health_data_service.sleep_types import SleepSession
from health_data_service.sleep_types import SleepStage

from sleep_dash.config import Settings
from sleep_dash.health import HealthUnavailable
from sleep_dash.health import RouterHealthGateway
from sleep_dash.health import Snapshot
from sleep_dash.health import _normalise

T0 = dt.datetime(2026, 6, 15, 5, 0, tzinfo=dt.UTC)
T1 = T0 + dt.timedelta(hours=1)


def payload(stage_value: str, session_id: str = "n1", timestamp: str | None = None) -> dict:
    start = timestamp or T0.isoformat()
    end = (T1).isoformat() if timestamp is None else "2026-06-15 06:00:00"
    return {
        "start": start,
        "end": end,
        "id": session_id,
        "stages": {
            "metric_id": "sleep_stages",
            "display_name": "Sleep Stages",
            "unit": None,
            "source": "garmin",
            "samples": [{"timestamp": start, "end_timestamp": end, "value": stage_value}],
        },
        "source": "garmin",
    }


class TestLenientStageDecoding:
    """One unrecognised stage string from one provider would otherwise blank the
    entire dashboard, including every other provider's good nights, because the
    merged call structures them all in a single converter.structure()."""

    def test_a_known_stage_still_decodes_to_its_enum_member(self) -> None:
        session = converter.structure([payload("deep")], list[SleepSession])[0]
        assert session.stages is not None
        assert session.stages.samples[0].value is SleepStage.DEEP

    @pytest.mark.parametrize("value", ["core", "asleepCore", "n1", "n2", "n3", "spicy"])
    def test_an_unrecognised_stage_becomes_unknown_instead_of_raising(self, value: str) -> None:
        session = converter.structure([payload(value)], list[SleepSession])[0]
        assert session.stages is not None
        assert session.stages.samples[0].value is SleepStage.UNKNOWN

    def test_one_bad_sample_does_not_take_down_the_other_sessions(self) -> None:
        """This is the whole point: the batch is structured in one call."""
        sessions = converter.structure(
            [payload("deep", "good"), payload("core", "bad")], list[SleepSession]
        )
        assert [s.id for s in sessions] == ["good", "bad"]
        assert sessions[0].stages is not None
        assert sessions[0].stages.samples[0].value is SleepStage.DEEP

    def test_the_interval_end_survives_the_session_path(self) -> None:
        """The reason stages are read from sleep-sessions and never from
        /v1/time-series, where the spec's Sample hook silently drops it."""
        session = converter.structure([payload("deep")], list[SleepSession])[0]
        assert session.stages is not None
        sample = session.stages.samples[0]
        assert isinstance(sample, IntervalSample)
        assert sample.end_timestamp == T1


class TestTimestampNormalisation:
    def test_a_naive_timestamp_is_read_as_utc_before_it_reaches_the_geometry(self) -> None:
        """A naive value structures perfectly cleanly and then raises
        `TypeError: can't subtract offset-naive and offset-aware datetimes` deep
        inside the chart code. The space separator here is exactly what the spec's
        own _to_params emits."""
        raw = converter.structure(
            [payload("deep", timestamp="2026-06-15 05:00:00")], list[SleepSession]
        )[0]
        assert raw.start.tzinfo is None, "precondition: the spec really does allow this"

        session = _normalise(raw)
        assert session.start.tzinfo is dt.UTC
        assert session.stages is not None
        assert session.stages.samples[0].timestamp.tzinfo is dt.UTC
        assert session.stages.samples[0].end_timestamp.tzinfo is dt.UTC
        # The arithmetic that used to explode.
        assert (session.end - session.start).total_seconds() == 3600

    def test_an_already_aware_timestamp_is_left_alone(self) -> None:
        session = _normalise(converter.structure([payload("deep")], list[SleepSession])[0])
        assert session.start == T0


class TestConnectedness:
    async def test_the_client_is_never_constructed_without_credentials(self) -> None:
        """HealthDataClient.__init__ does an unguarded os.environ[...] and raises
        KeyError. Reaching it at all would turn a normal unconfigured state into a
        crash."""
        gateway = RouterHealthGateway(Settings())
        with pytest.raises(HealthUnavailable):
            await gateway.snapshot()


class RecordingGateway(RouterHealthGateway):
    """Counts fetches, so the cache contract is observable."""

    fetches: int = 0

    async def _fetch(self) -> Snapshot:
        type(self).fetches += 1
        return Snapshot(sessions=(), providers=(), fetched_at=self.clock())


class TestCaching:
    def _gateway(self, now: list[dt.datetime]) -> RecordingGateway:
        RecordingGateway.fetches = 0
        settings = Settings(
            router_url="https://router.example", app_token="t", cache_ttl_seconds=300.0
        )
        return RecordingGateway(settings, clock=lambda: now[0])

    async def test_two_page_loads_inside_the_ttl_make_one_round_trip(self) -> None:
        """Navigating between nights re-renders from the same snapshot, so it must
        not fan out to every provider again -- especially against a 30s timeout
        this app cannot change."""
        now = [T0]
        gateway = self._gateway(now)
        await gateway.snapshot()
        now[0] = T0 + dt.timedelta(seconds=60)
        await gateway.snapshot()
        assert RecordingGateway.fetches == 1

    async def test_the_cache_expires(self) -> None:
        now = [T0]
        gateway = self._gateway(now)
        await gateway.snapshot()
        now[0] = T0 + dt.timedelta(seconds=600)
        await gateway.snapshot()
        assert RecordingGateway.fetches == 2
