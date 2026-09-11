"""The whole rendered document.

The contract this module exists to enforce: **the server never formats a final
clock time or date**. It cannot -- it does not know the viewer's timezone. Every
instant goes out as a UTC rendering carrying a ``data-ts``, and one JS pass rewrites
them all. A time rendered without ``data-ts`` is frozen in UTC forever for every
viewer outside it, and nothing about the page looks wrong.
"""

import datetime as dt

import pytest
from health_data_service.sleep_types import SleepStage

from sleep_dash import theme
from sleep_dash.config import Settings
from sleep_dash.health import ProviderInfo
from sleep_dash.health import Snapshot
from sleep_dash.page import render
from sleep_dash.view import NOT_CONNECTED
from sleep_dash.view import build_view
from sleep_dash.view import notice_view
from tests.fixtures import T0
from tests.fixtures import build_session
from tests.helpers import clock_times
from tests.helpers import stamped_times

NOW = dt.datetime(2026, 9, 10, 9, 30, tzinfo=dt.UTC)
SETTINGS = Settings()


def snapshot_of(*sessions: object, providers: tuple[ProviderInfo, ...] = ()) -> Snapshot:
    return Snapshot(
        sessions=tuple(sessions),  # type: ignore[arg-type]
        providers=providers,
        fetched_at=NOW,
    )


@pytest.fixture
def full_page() -> str:
    snapshot = snapshot_of(
        build_session(),
        providers=(ProviderInfo(app_id="g", app_name="garmin-connector", status="running"),),
    )
    return render(build_view(snapshot, None, SETTINGS, rendered_at=NOW))


class TestTimeLocalisationContract:
    def test_no_clock_time_is_rendered_without_a_machine_readable_instant(
        self, full_page: str
    ) -> None:
        found = clock_times(full_page)
        assert found, "the page should contain clock times at all"
        unstamped = [text for text, ts in found if ts is None]
        assert unstamped == [], f"these times will never be localised: {unstamped}"

    def test_the_fallback_text_is_the_utc_rendering_of_its_own_data_ts(
        self, full_page: str
    ) -> None:
        """With JS off the page must be *correct*, not merely populated."""
        stamped = stamped_times(full_page)
        assert stamped
        for raw, fmt, text in stamped:
            instant = dt.datetime.fromisoformat(raw)
            assert instant.tzinfo is not None, "an instant with no offset is ambiguous"
            expected = {
                "hm": instant.strftime("%H:%M"),
                "date": instant.strftime("%a %d %b"),
                "datetime": instant.strftime("%d %b %H:%M"),
            }[fmt]
            assert text == expected

    def test_the_night_title_is_localised_rather_than_dated_on_the_server(
        self, full_page: str
    ) -> None:
        """22:10 UTC on the 9th is still the 9th in London and already the 9th in
        Denver -- but a 23:30 UTC night is a different date either side. The server
        cannot pick, so it must not."""
        assert "data-fmt='date'" in full_page

    def test_the_timezone_label_is_present_for_the_script_to_fill_in(self, full_page: str) -> None:
        assert "id='tz-label'" in full_page
        assert ">UTC<" in full_page  # the honest fallback with JS off

    def test_a_degraded_page_also_localises_its_timestamps(self) -> None:
        """The empty-state pages carry a rendered-at time too, which is why the
        localisation pass runs before the chart code and independently of it."""
        page = render(notice_view(NOT_CONNECTED, rendered_at=NOW))
        assert [text for text, ts in clock_times(page) if ts is None] == []


class TestEscaping:
    def test_a_hostile_source_string_cannot_escape_the_footer(self) -> None:
        session = build_session(source="<script>alert(1)</script>")
        page = render(build_view(snapshot_of(session), None, SETTINGS, rendered_at=NOW))
        assert "<script>alert(1)</script>" not in page
        assert "&lt;script&gt;" in page

    def test_the_json_island_cannot_close_its_own_script_element(self) -> None:
        """HTML escaping does not apply inside <script>; only "</script" can end it."""
        session = build_session(session_id="</script><img src=x onerror=alert(1)>")
        page = render(build_view(snapshot_of(session), None, SETTINGS, rendered_at=NOW))
        island = page.split("id='night-data'>")[1].split("</script>")[0]
        assert "</script" not in island
        assert "onerror" not in island or "\\u003c" in island

    def test_a_hostile_night_key_cannot_break_out_of_the_nav_link(self) -> None:
        older = build_session(session_id="' onmouseover='alert(1)", start=T0)
        newer = build_session(session_id="safe", start=T0 + dt.timedelta(days=1))
        page = render(build_view(snapshot_of(older, newer), None, SETTINGS, rendered_at=NOW))
        assert "onmouseover='alert(1)" not in page


class TestSummaryTiles:
    def test_the_tiles_report_what_the_provider_said(self, full_page: str) -> None:
        assert "7h 50m" in full_page  # total_duration 470 min
        assert "98%" in full_page  # efficiency 97.9, rendered 0dp
        assert "58 bpm" in full_page

    def test_efficiency_is_not_multiplied_by_one_hundred(self, full_page: str) -> None:
        """It arrives already a percentage. The classic bug here reports 9790%."""
        assert "9790%" not in full_page

    def test_a_missing_scalar_renders_an_em_dash_and_never_a_zero(self) -> None:
        session = build_session(scalars=False, total_duration=None)
        page = render(build_view(snapshot_of(session), None, SETTINGS, rendered_at=NOW))
        assert "&mdash;" in page
        assert "0h 00m" not in page
        assert "0 bpm" not in page


class TestLegend:
    def test_every_drawn_lane_has_a_swatch(self, full_page: str) -> None:
        for stage in (SleepStage.DEEP, SleepStage.LIGHT, SleepStage.REM, SleepStage.AWAKE):
            assert theme.STAGE_LABELS[stage] in full_page

    def test_stage_colours_match_the_health_dashboard_palette(self, full_page: str) -> None:
        """The two apps are meant to read as one system."""
        assert theme.STAGE_COLOURS[SleepStage.DEEP] == "#6366f1"
        assert theme.STAGE_COLOURS[SleepStage.LIGHT] == "#64748b"
        assert theme.STAGE_COLOURS[SleepStage.REM] == "#06b6d4"
        assert theme.STAGE_COLOURS[SleepStage.AWAKE] == "#f59e0b"
        for stage in (SleepStage.DEEP, SleepStage.REM, SleepStage.AWAKE):
            assert theme.STAGE_COLOURS[stage] in full_page

    def test_the_legend_duration_is_measured_from_the_timeline(self, full_page: str) -> None:
        # CANONICAL_SPANS: deep is 60 + 55 = 115 minutes.
        assert "1h 55m" in full_page


class TestProgressiveEnhancement:
    def test_the_readout_is_hidden_until_the_script_unhides_it(self, full_page: str) -> None:
        assert "id='readout' hidden" in full_page

    def test_the_navigation_links_are_plain_anchors(self) -> None:
        older = build_session(session_id="older", start=T0)
        newer = build_session(session_id="newer", start=T0 + dt.timedelta(days=1))
        page = render(build_view(snapshot_of(older, newer), None, SETTINGS, rendered_at=NOW))
        assert "<a href='?night=older'>" in page

    def test_the_chart_is_present_without_any_script_running(self, full_page: str) -> None:
        """Server-rendered SVG: the charts are in the document, not built by JS."""
        svg = full_page.split("<svg")[1].split("</svg>")[0]
        assert "class='stage'" in svg
        assert "class='hr-line'" in svg


class TestProviderDisagreement:
    def test_a_second_provider_is_named_rather_than_blended(self) -> None:
        rich = build_session(session_id="rich", source="garmin")
        coarse = build_session(session_id="coarse", source="oura", spans=((480, SleepStage.LIGHT),))
        page = render(build_view(snapshot_of(rich, coarse), None, SETTINGS, rendered_at=NOW))
        assert "data from garmin" in page
        assert "also reported by oura" in page

    def test_a_running_provider_that_returned_nothing_is_named_in_the_footer(self) -> None:
        """_fan_out reads any non-200 as "this provider has nothing", so an outage
        is otherwise indistinguishable from a quiet night."""
        snapshot = Snapshot(
            sessions=(build_session(source="garmin"),),
            providers=(
                ProviderInfo(app_id="g", app_name="garmin", status="running"),
                ProviderInfo(app_id="o", app_name="oura", status="running"),
            ),
            fetched_at=NOW,
        )
        page = render(build_view(snapshot, None, SETTINGS, rendered_at=NOW))
        assert "at least one provider returned nothing" in page

    def test_hidden_naps_are_counted_rather_than_dropped_silently(self) -> None:
        night = build_session(session_id="night")
        nap = build_session(
            session_id="nap",
            start=T0 + dt.timedelta(days=1),
            minutes=20,
            total_duration=18.0,
        )
        page = render(build_view(snapshot_of(night, nap), None, SETTINGS, rendered_at=NOW))
        assert "1 session under 30 minutes hidden" in page


class TestPartialNights:
    def test_a_session_with_stages_but_no_heart_rate_still_draws_both_panels(self) -> None:
        page = render(
            build_view(
                snapshot_of(build_session(with_heart_rate=False)),
                None,
                SETTINGS,
                rendered_at=NOW,
            )
        )
        assert "class='stage'" in page
        assert "No heart rate recorded" in page

    def test_a_session_with_heart_rate_but_no_stages_still_draws_both_panels(self) -> None:
        page = render(
            build_view(
                snapshot_of(build_session(with_stages=False)),
                None,
                SETTINGS,
                rendered_at=NOW,
            )
        )
        assert "class='hr-line'" in page
        assert "No sleep stages recorded" in page


class TestTheme:
    def test_the_page_uses_the_health_dashboard_surfaces(self, full_page: str) -> None:
        assert theme.PAGE_BG in full_page
        assert theme.CARD_BG in full_page
        assert theme.TEXT in full_page

    def test_the_document_declares_a_dark_colour_scheme(self, full_page: str) -> None:
        """Without this the browser paints scrollbars and form controls light."""
        assert "name='color-scheme' content='dark'" in full_page

    def test_the_chart_scrolls_rather_than_shrinking_on_a_phone(self, full_page: str) -> None:
        assert "chart-scroll" in full_page
        assert "min-width:640px" in full_page
