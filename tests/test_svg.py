"""The emitted SVG, asserted element by element.

There is no browser in these tests, so the things that can only be got wrong in
markup -- whether the hit rect can actually receive a pointer event, whether the
crosshair steals it, whether a lone sample draws anything at all -- are asserted
against the string.
"""

import re

import pytest
from health_data_service.data_types import Sample
from health_data_service.sleep_types import SleepStage

from sleep_dash import geometry as geo
from sleep_dash import theme
from sleep_dash.nights import Night
from sleep_dash.svg import build_chart
from sleep_dash.svg import chart_payload
from sleep_dash.svg import render_chart
from sleep_dash.timeline import build_timeline
from tests.fixtures import T0
from tests.fixtures import build_session
from tests.fixtures import session_from_samples

GAP = 600.0


def chart_for(session: object) -> tuple[object, object]:
    night = Night(session=session)  # type: ignore[arg-type]
    timeline = build_timeline(night, gap_seconds=GAP)
    return build_chart(night, timeline, gap_seconds=GAP), timeline


def markup(session: object) -> str:
    chart, _ = chart_for(session)
    return render_chart(chart, label="a night")  # type: ignore[arg-type]


class TestStageBars:
    def test_every_stage_interval_becomes_one_rect(self) -> None:
        session = build_session()
        assert session.stages is not None
        svg = markup(session)
        assert svg.count("class='stage'") == len(session.stages.samples)

    def test_each_stage_is_drawn_in_its_own_colour(self) -> None:
        svg = markup(build_session())
        for stage in (SleepStage.DEEP, SleepStage.LIGHT, SleepStage.REM, SleepStage.AWAKE):
            assert f"fill='{theme.STAGE_COLOURS[stage]}'" in svg

    def test_unknown_stage_is_drawn_with_a_pattern_not_a_second_grey(self) -> None:
        """A distinct grey scores dE 10.9 against LIGHT -- below the hard floor even
        for full colour vision -- so UNKNOWN is textured instead. See theme.py."""
        session = build_session(spans=((60, SleepStage.UNKNOWN), (60, SleepStage.LIGHT)))
        svg = markup(session)
        assert theme.UNKNOWN_FILL in svg
        assert f"<pattern id='{theme.UNKNOWN_HATCH_ID}'" in svg

    def test_a_night_without_stages_says_so_rather_than_drawing_nothing(self) -> None:
        svg = markup(build_session(with_stages=False))
        assert "No sleep stages recorded" in svg
        assert "class='stage'" not in svg


class TestHeartRate:
    def test_heart_rate_is_split_into_one_polyline_per_gap_free_run(self) -> None:
        session = build_session(minutes=60, hr_every=2, hr_skip=range(20, 50))
        svg = markup(session)
        assert svg.count("class='hr-line'") == 2
        assert svg.count("class='hr-fill'") == 2

    def test_a_contiguous_trace_is_a_single_polyline(self) -> None:
        assert markup(build_session(minutes=60, hr_every=2)).count("class='hr-line'") == 1

    def test_a_single_sample_run_is_drawn_as_a_dot_not_dropped(self) -> None:
        """A <polyline> with one point renders nothing, which would silently hide a
        real reading."""
        session = session_from_samples(minutes=30, heart_rate=[Sample(timestamp=T0, value=58.0)])
        svg = markup(session)
        assert "<circle" in svg
        assert "class='hr-line'" not in svg

    def test_a_night_without_heart_rate_keeps_the_panel_and_explains_itself(self) -> None:
        svg = markup(build_session(with_heart_rate=False))
        assert "No heart rate recorded" in svg
        # The panel keeps its height, so the crosshair still spans the same box.
        assert f"y2='{geo.CROSSHAIR_Y1}'" in svg


class TestInteractionMarkup:
    def test_the_hit_rect_can_receive_pointer_events(self) -> None:
        """fill='none' alone receives nothing in SVG; pointer-events='all' is what
        makes an invisible rect hittable."""
        svg = markup(build_session())
        hit = re.search(r"<rect id='hit'[^>]*>", svg)
        assert hit is not None
        assert "fill='none'" in hit.group(0)
        assert "pointer-events='all'" in hit.group(0)

    def test_the_hit_rect_covers_both_panels(self) -> None:
        svg = markup(build_session())
        hit = re.search(r"<rect id='hit'[^>]*>", svg)
        assert hit is not None
        assert f"height='{geo.CROSSHAIR_Y1 - geo.STAGE_Y0}'" in hit.group(0)

    def test_the_crosshair_group_does_not_intercept_the_pointer(self) -> None:
        svg = markup(build_session())
        group = re.search(r"<g id='crosshair'[^>]*>", svg)
        assert group is not None
        assert "pointer-events='none'" in group.group(0)

    def test_the_crosshair_is_hidden_until_the_script_moves_it(self) -> None:
        group = re.search(r"<g id='crosshair'[^>]*>", markup(build_session()))
        assert group is not None
        assert "visibility='hidden'" in group.group(0)

    def test_the_crosshair_is_one_line_spanning_both_panels(self) -> None:
        """The single reason both charts share one <svg>."""
        svg = markup(build_session())
        line = re.search(r"<g id='crosshair'.*?<line([^>]*)>", svg, re.S)
        assert line is not None
        assert f"y1='{geo.CROSSHAIR_Y0}'" in line.group(1)
        assert f"y2='{geo.CROSSHAIR_Y1}'" in line.group(1)

    def test_the_chart_is_focusable_and_labelled(self) -> None:
        svg = markup(build_session())
        assert "tabindex='0'" in svg
        assert "role='img'" in svg
        assert "aria-label=" in svg


class TestAxis:
    def test_axis_tick_labels_carry_data_ts_so_one_pass_localises_the_chart(self) -> None:
        svg = markup(build_session())
        labels = re.findall(r"<text class='axis'([^>]*)>", svg)
        assert labels
        for attributes in labels:
            assert "data-ts='" in attributes
            assert "data-fmt='hm'" in attributes


class TestPayload:
    def test_the_payload_has_one_entry_per_minute(self) -> None:
        chart, timeline = chart_for(build_session())
        payload = chart_payload(chart, timeline)  # type: ignore[arg-type]
        assert payload["minutes"] == timeline.minutes  # type: ignore[union-attr]
        assert len(payload["stage"]) == timeline.minutes  # type: ignore[arg-type,union-attr]
        assert len(payload["hr"]) == timeline.minutes  # type: ignore[arg-type,union-attr]

    def test_stage_indices_address_the_names_the_page_actually_renders(self) -> None:
        """The timeline indexes STAGE_ORDER, but the chart only draws the lanes
        present. An unremapped index would colour the readout wrongly."""
        chart, timeline = chart_for(build_session())
        payload = chart_payload(chart, timeline)  # type: ignore[arg-type]
        names = payload["names"]
        for index in payload["stage"]:  # type: ignore[union-attr]
            assert index == -1 or 0 <= index < len(names)  # type: ignore[arg-type]

    def test_the_payload_carries_the_geometry_the_script_needs(self) -> None:
        chart, timeline = chart_for(build_session())
        payload = chart_payload(chart, timeline)  # type: ignore[arg-type]
        assert payload["x0"] == geo.PLOT_X0
        assert payload["w"] == geo.PLOT_W
        assert payload["hrY0"] == geo.HR_Y0
        assert payload["hrH"] == geo.HR_H

    def test_the_readout_colour_matches_the_bar_colour(self) -> None:
        chart, timeline = chart_for(build_session())
        payload = chart_payload(chart, timeline)  # type: ignore[arg-type]
        for colour in payload["colors"]:  # type: ignore[union-attr]
            assert colour in theme.STAGE_COLOURS.values()

    @pytest.mark.parametrize("minutes", [1, 5, 480])
    def test_the_payload_survives_short_nights(self, minutes: int) -> None:
        session = build_session(minutes=minutes, spans=((minutes, SleepStage.LIGHT),))
        chart, timeline = chart_for(session)
        payload = chart_payload(chart, timeline)  # type: ignore[arg-type]
        assert payload["minutes"] >= 1  # type: ignore[operator]
