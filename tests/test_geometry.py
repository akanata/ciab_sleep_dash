"""Scales, lanes, bars and ticks.

The headline test in this module is the one that ties the readout to the drawing:
without it, the interpolation rule in ``timeline`` and the polyline in ``svg`` are
free to drift apart, and the resulting bug -- a tooltip that disagrees with the
chart by a few bpm -- is exactly the kind nobody notices until they stop trusting
the page.
"""

import datetime as dt

import pytest
from health_data_service.sleep_types import SleepStage

from sleep_dash import geometry as geo
from sleep_dash.nights import Night
from sleep_dash.timeline import build_timeline
from sleep_dash.timeline import hr_runs
from tests.fixtures import T0
from tests.fixtures import build_session

GAP = 600.0


def y_on_path(points: list[tuple[float, float]], x: float) -> float | None:
    """The height of the drawn polyline at ``x``, by linear interpolation --
    which is exactly what the renderer draws between two points."""
    for (x0, y0), (x1, y1) in zip(points, points[1:], strict=False):
        if x0 <= x <= x1:
            if x1 == x0:
                return y0
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return None


class TestPanelLayout:
    def test_the_crosshair_spans_both_panels(self) -> None:
        assert geo.CROSSHAIR_Y0 == geo.STAGE_Y0
        assert geo.CROSSHAIR_Y1 == geo.HR_Y1
        # ...and crosses the channel between them, which is the point.
        assert geo.CROSSHAIR_Y0 < geo.STAGE_Y1 < geo.HR_Y0 < geo.CROSSHAIR_Y1

    def test_the_panels_do_not_overlap(self) -> None:
        assert geo.STAGE_Y1 < geo.HR_Y0

    def test_the_axis_strip_is_below_both_panels(self) -> None:
        assert geo.HR_Y1 < geo.VIEW_H


class TestXScale:
    def test_both_panels_use_one_x_scale(self) -> None:
        """Not a property of the code so much as a fact the rest of the design rests
        on: one scale instance produces the stage bars and the heart-rate points, so
        a given instant is at the same x in both."""
        xs = geo.XScale(t0=T0, t1=T0 + dt.timedelta(hours=8))
        session = build_session()
        assert session.stages is not None and session.heart_rate is not None
        bars = geo.stage_bars(session.stages.samples, xs, geo.lanes([SleepStage.LIGHT]))
        paths = geo.hr_paths(
            hr_runs(session.heart_rate.samples, gap_seconds=GAP), xs, geo.HrScale(50, 70)
        )
        assert bars[0].x == pytest.approx(paths[0][0][0])

    def test_the_scale_spans_the_full_plot_width(self) -> None:
        xs = geo.XScale(t0=T0, t1=T0 + dt.timedelta(hours=8))
        assert xs.x(T0) == pytest.approx(geo.PLOT_X0)
        assert xs.x(xs.t1) == pytest.approx(geo.PLOT_X0 + geo.PLOT_W)

    def test_a_zero_length_session_does_not_divide_by_zero(self) -> None:
        xs = geo.XScale(t0=T0, t1=T0)
        assert xs.x(T0) == pytest.approx(geo.PLOT_X0)

    def test_the_minute_centre_is_where_the_timeline_samples(self) -> None:
        """x_of_minute(m) must equal x(start + 60m + 30s), or the crosshair sits
        beside the value it is reporting."""
        xs = geo.XScale(t0=T0, t1=T0 + dt.timedelta(minutes=100))
        for minute in (0, 37, 99):
            expected = xs.x(T0 + dt.timedelta(seconds=60 * minute + 30))
            assert xs.x_of_minute(minute, 100) == pytest.approx(expected)


class TestHeartRateScale:
    def test_a_flat_heart_rate_trace_does_not_divide_by_zero(self) -> None:
        lo, hi = geo.hr_bounds([58.0] * 20)
        assert hi - lo >= geo.HR_MIN_SPAN
        assert geo.HrScale(lo, hi).y(58.0) == pytest.approx(
            geo.HR_Y0 + geo.HR_H / 2, abs=geo.HR_H / 2
        )

    def test_bounds_contain_every_sample(self) -> None:
        values = [48.0, 52.0, 77.0, 61.0]
        lo, hi = geo.hr_bounds(values)
        assert lo <= min(values) and hi >= max(values)

    def test_an_empty_series_still_yields_a_drawable_axis(self) -> None:
        lo, hi = geo.hr_bounds([])
        assert hi > lo

    def test_the_scale_inverts_cleanly(self) -> None:
        scale = geo.HrScale(*geo.hr_bounds([50.0, 70.0]))
        assert scale.bpm_at(scale.y(63.0)) == pytest.approx(63.0)

    def test_higher_bpm_is_higher_on_the_page(self) -> None:
        scale = geo.HrScale(40.0, 80.0)
        assert scale.y(70.0) < scale.y(50.0)


class TestLanes:
    def test_light_and_deep_always_have_lanes(self) -> None:
        """A night reported as one long LIGHT block would otherwise render as a
        single bar filling the whole panel, which reads as a chart with no data."""
        assert geo.lanes([SleepStage.LIGHT]) == (SleepStage.LIGHT, SleepStage.DEEP)

    def test_an_unknown_lane_appears_only_when_the_night_has_unknown_samples(self) -> None:
        normal = geo.lanes([SleepStage.AWAKE, SleepStage.REM, SleepStage.LIGHT, SleepStage.DEEP])
        assert SleepStage.UNKNOWN not in normal
        assert len(normal) == 4
        with_unknown = geo.lanes([*normal, SleepStage.UNKNOWN])
        assert with_unknown[-1] is SleepStage.UNKNOWN

    def test_lanes_run_awake_at_the_top_to_deep_at_the_bottom(self) -> None:
        order = geo.lanes([SleepStage.AWAKE, SleepStage.REM, SleepStage.LIGHT, SleepStage.DEEP])
        assert order[0] is SleepStage.AWAKE
        assert order[-1] is SleepStage.DEEP
        assert geo.lane_centre(0, 4) < geo.lane_centre(3, 4)

    def test_lanes_fill_the_panel_without_overlapping(self) -> None:
        for count in (2, 4, 5):
            spans = [geo.lane_geometry(i, count) for i in range(count)]
            for (y0, h0), (y1, _) in zip(spans, spans[1:], strict=False):
                assert y0 + h0 <= y1 + 0.001
            assert spans[0][0] >= geo.STAGE_Y0
            assert spans[-1][0] + spans[-1][1] <= geo.STAGE_Y1 + 0.001


class TestBars:
    def test_a_one_minute_stage_is_still_visible(self) -> None:
        session = build_session(minutes=480, spans=((1, SleepStage.AWAKE), (479, SleepStage.LIGHT)))
        xs = geo.XScale(t0=T0, t1=T0 + dt.timedelta(minutes=480))
        assert session.stages is not None
        bars = geo.stage_bars(session.stages.samples, xs, geo.lanes([SleepStage.AWAKE]))
        assert bars[0].width >= geo.MIN_BAR_W

    def test_bar_width_is_proportional_to_the_interval(self) -> None:
        """The entire reason this app exists: health-dashboard draws every stage as
        an equal-width column and throws end_timestamp away."""
        session = build_session(minutes=120, spans=((30, SleepStage.LIGHT), (90, SleepStage.DEEP)))
        xs = geo.XScale(t0=T0, t1=T0 + dt.timedelta(minutes=120))
        assert session.stages is not None
        bars = geo.stage_bars(session.stages.samples, xs, geo.lanes([SleepStage.LIGHT]))
        assert bars[1].width == pytest.approx(bars[0].width * 3, rel=0.01)

    def test_bars_are_emitted_in_chronological_order(self) -> None:
        session = build_session()
        xs = geo.XScale(t0=T0, t1=T0 + dt.timedelta(minutes=480))
        assert session.stages is not None
        bars = geo.stage_bars(session.stages.samples, xs, geo.lanes([SleepStage.LIGHT]))
        assert [b.x for b in bars] == sorted(b.x for b in bars)


class TestTicks:
    @pytest.mark.parametrize("hours", [2, 4, 8, 14, 25])
    def test_tick_counts_stay_readable(self, hours: int) -> None:
        xs = geo.XScale(t0=T0, t1=T0 + dt.timedelta(hours=hours))
        ticks = geo.time_ticks(xs)
        assert 2 <= len(ticks) <= geo.TARGET_TICKS + 1

    def test_ticks_land_on_round_utc_boundaries(self) -> None:
        xs = geo.XScale(t0=T0, t1=T0 + dt.timedelta(hours=8))
        step = geo.tick_step_minutes(480)
        for tick in geo.time_ticks(xs):
            minutes = tick.timestamp.hour * 60 + tick.timestamp.minute
            assert minutes % step == 0

    def test_every_tick_sits_inside_the_plot(self) -> None:
        xs = geo.XScale(t0=T0, t1=T0 + dt.timedelta(hours=8))
        for tick in geo.time_ticks(xs):
            assert geo.PLOT_X0 - 0.001 <= tick.x <= geo.PLOT_X0 + geo.PLOT_W + 0.001


class TestReadoutMatchesDrawing:
    """The contract between timeline.py and svg.py, asserted directly."""

    def test_the_widget_value_at_a_minute_is_the_value_the_line_is_drawn_at(self) -> None:
        session = build_session(minutes=480, hr_every=2)
        night = Night(session=session)
        timeline = build_timeline(night, gap_seconds=GAP)
        assert session.heart_rate is not None

        xs = geo.XScale(
            t0=timeline.start, t1=timeline.start + dt.timedelta(minutes=timeline.minutes)
        )
        ys = geo.HrScale(*geo.hr_bounds([s.value for s in session.heart_rate.samples]))
        paths = geo.hr_paths(hr_runs(session.heart_rate.samples, gap_seconds=GAP), xs, ys)

        checked = 0
        for minute, reading in enumerate(timeline.hr):
            if reading is None:
                continue
            x = xs.x_of_minute(minute, timeline.minutes)
            drawn = next((y for y in (y_on_path(p, x) for p in paths) if y is not None), None)
            if drawn is None:
                continue
            # Read the picture back in bpm and compare to what the widget will say.
            assert ys.bpm_at(drawn) == pytest.approx(reading, abs=1.0)
            checked += 1
        assert checked > 200, "the test should actually be exercising the night"
