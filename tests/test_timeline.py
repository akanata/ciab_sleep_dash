"""The per-minute lookup the crosshair reads.

The whole point of this module is that the number in the readout and the height of
the drawn line are the SAME number. Any rule that computes them differently -- say,
nearest-sample for the readout and interpolation for the line -- produces a tooltip
that quietly disagrees with the picture the reader is pointing at.
"""

import datetime as dt

import pytest
from health_data_service.data_types import IntervalSample
from health_data_service.data_types import Sample
from health_data_service.sleep_types import SleepStage

from sleep_dash.nights import Night
from sleep_dash.timeline import STAGE_ORDER
from sleep_dash.timeline import build_timeline
from sleep_dash.timeline import hr_runs
from sleep_dash.timeline import stage_totals
from sleep_dash.timeline import window
from tests.fixtures import T0
from tests.fixtures import build_session
from tests.fixtures import session_from_samples
from tests.fixtures import stage_samples

GAP = 600.0


def night(**kwargs: object) -> Night:
    return Night(session=build_session(**kwargs))  # type: ignore[arg-type]


def lane(stage: SleepStage) -> int:
    return STAGE_ORDER.index(stage)


class TestWindow:
    def test_the_window_covers_the_session(self) -> None:
        start, end = window(night())
        assert start == T0
        assert (end - start).total_seconds() / 60 == 480

    def test_the_window_widens_to_cover_heart_rate_outside_the_session(self) -> None:
        """A provider whose trace runs past the session end is telling the truth.
        Dropping a real reading to keep the axis tidy is the wrong trade."""
        late = T0 + dt.timedelta(minutes=50)
        session = session_from_samples(
            minutes=30,
            heart_rate=[Sample(timestamp=T0, value=55.0), Sample(timestamp=late, value=61.0)],
        )
        _, end = window(Night(session=session))
        assert end >= late


class TestStagePerMinute:
    def test_a_minute_is_given_the_stage_covering_its_midpoint(self) -> None:
        # 10 minutes LIGHT then 10 minutes DEEP.
        spans = ((10, SleepStage.LIGHT), (10, SleepStage.DEEP))
        timeline = build_timeline(
            night(spans=spans, minutes=20, with_heart_rate=False), gap_seconds=GAP
        )
        assert timeline.minutes == 20
        assert timeline.stage[0] == lane(SleepStage.LIGHT)
        assert timeline.stage[9] == lane(SleepStage.LIGHT)
        # Minute 10 spans [10:00, 11:00); its midpoint 10:30 is inside DEEP.
        assert timeline.stage[10] == lane(SleepStage.DEEP)
        assert timeline.stage[19] == lane(SleepStage.DEEP)

    def test_stage_intervals_that_leave_a_hole_produce_minus_one_not_a_guess(self) -> None:
        """An uncovered stretch is missing data, and the chart shows a gap. Filling
        it in would invent a stage the device never recorded."""
        session = session_from_samples(
            minutes=30,
            stages=[
                IntervalSample(
                    timestamp=T0,
                    value=SleepStage.LIGHT,
                    end_timestamp=T0 + dt.timedelta(minutes=10),
                ),
                # minutes 10-19 uncovered
                IntervalSample(
                    timestamp=T0 + dt.timedelta(minutes=20),
                    value=SleepStage.DEEP,
                    end_timestamp=T0 + dt.timedelta(minutes=30),
                ),
            ],
        )
        timeline = build_timeline(Night(session=session), gap_seconds=GAP)
        assert timeline.stage[5] == lane(SleepStage.LIGHT)
        assert timeline.stage[15] == -1
        assert timeline.stage[25] == lane(SleepStage.DEEP)

    def test_a_later_overlapping_interval_wins(self) -> None:
        """One rule, applied in both the minute scan and the drawing order, so the
        array and the picture cannot disagree."""
        session = session_from_samples(
            minutes=20,
            stages=[
                IntervalSample(
                    timestamp=T0,
                    value=SleepStage.LIGHT,
                    end_timestamp=T0 + dt.timedelta(minutes=20),
                ),
                IntervalSample(
                    timestamp=T0 + dt.timedelta(minutes=10),
                    value=SleepStage.REM,
                    end_timestamp=T0 + dt.timedelta(minutes=20),
                ),
            ],
        )
        timeline = build_timeline(Night(session=session), gap_seconds=GAP)
        assert timeline.stage[15] == lane(SleepStage.REM)

    def test_an_unknown_stage_is_a_real_reading_not_a_hole(self) -> None:
        spans = ((10, SleepStage.UNKNOWN),)
        timeline = build_timeline(
            night(spans=spans, minutes=10, with_heart_rate=False), gap_seconds=GAP
        )
        assert timeline.stage[5] == lane(SleepStage.UNKNOWN)
        assert timeline.stage[5] != -1


class TestHeartRatePerMinute:
    def test_a_reading_is_interpolated_between_the_bracketing_samples(self) -> None:
        """The drawn polyline IS linear interpolation between samples, so the
        readout has to be too."""
        session = session_from_samples(
            minutes=10,
            heart_rate=[
                Sample(timestamp=T0, value=50.0),
                Sample(timestamp=T0 + dt.timedelta(minutes=10), value=70.0),
            ],
        )
        timeline = build_timeline(Night(session=session), gap_seconds=GAP)
        # Minute 4's midpoint is 4.5 min in: 50 + 20 * 0.45 = 59.
        assert timeline.hr[4] == pytest.approx(59, abs=1)

    def test_a_minute_inside_a_ten_minute_gap_has_no_reading_and_no_line(self) -> None:
        """The readout reads em dash exactly where the line is broken."""
        session = build_session(minutes=60, with_stages=False, hr_every=2, hr_skip=range(20, 50))
        timeline = build_timeline(Night(session=session), gap_seconds=GAP)
        assert timeline.hr[35] is None
        assert session.heart_rate is not None
        runs = hr_runs(session.heart_rate.samples, gap_seconds=GAP)
        assert len(runs) == 2, "the drawn line is broken in the same place"

    def test_a_minute_outside_the_series_has_no_reading(self) -> None:
        session = session_from_samples(
            minutes=30,
            heart_rate=[
                Sample(timestamp=T0 + dt.timedelta(minutes=10), value=60.0),
                Sample(timestamp=T0 + dt.timedelta(minutes=12), value=61.0),
            ],
        )
        timeline = build_timeline(Night(session=session), gap_seconds=GAP)
        assert timeline.hr[0] is None
        assert timeline.hr[29] is None

    def test_a_session_with_no_heart_rate_is_all_missing_not_an_error(self) -> None:
        timeline = build_timeline(night(with_heart_rate=False), gap_seconds=GAP)
        assert set(timeline.hr) == {None}
        assert timeline.minutes == 480


class TestRuns:
    def test_a_contiguous_trace_is_one_run(self) -> None:
        session = build_session(minutes=60, hr_every=2)
        assert session.heart_rate is not None
        assert len(hr_runs(session.heart_rate.samples, gap_seconds=GAP)) == 1

    def test_an_empty_series_has_no_runs(self) -> None:
        assert hr_runs([], gap_seconds=GAP) == []


class TestElapsedTime:
    def test_a_night_crossing_a_fall_back_boundary_is_measured_in_elapsed_minutes(self) -> None:
        """The server never touches a local zone, so a 25-hour wall-clock night is
        simply its real elapsed length. The browser renders 01:00 twice, correctly."""
        start = dt.datetime(2026, 11, 1, 4, 0, tzinfo=dt.UTC)  # US fall-back night
        timeline = build_timeline(
            Night(session=build_session(start=start, minutes=540, with_heart_rate=False)),
            gap_seconds=GAP,
        )
        assert timeline.minutes == 540


class TestStageTotals:
    def test_totals_are_summed_from_the_interval_widths(self) -> None:
        totals = stage_totals(stage_samples(T0, ((90, SleepStage.LIGHT), (60, SleepStage.DEEP))))
        assert totals[SleepStage.LIGHT] == 90.0
        assert totals[SleepStage.DEEP] == 60.0
