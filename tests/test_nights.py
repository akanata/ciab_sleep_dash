"""Grouping sessions into nights, and choosing which one to show.

Two providers watching the same sleeper produce two sessions for one night, and the
spec's ``get_sleep_sessions_merged`` does not dedupe them. Blending them would invent
numbers no provider would stand behind, so one wins wholesale and the rest are named
rather than merged.
"""

import datetime as dt

from health_data_service.sleep_types import SleepStage

from sleep_dash.nights import duration_minutes
from sleep_dash.nights import group_nights
from sleep_dash.nights import is_nap
from sleep_dash.nights import nights_from
from sleep_dash.nights import select
from tests.fixtures import T0
from tests.fixtures import build_session

DAY = dt.timedelta(days=1)


class TestDuration:
    def test_the_reported_total_duration_is_used_when_present(self) -> None:
        assert duration_minutes(build_session(total_duration=470.0)) == 470.0

    def test_a_session_with_no_total_duration_is_measured_end_minus_start(self) -> None:
        """total_duration is `| None` on every session, so the nap filter cannot
        depend on it being there."""
        session = build_session(total_duration=None, minutes=480)
        assert duration_minutes(session) == 480.0

    def test_a_session_under_thirty_minutes_is_a_nap(self) -> None:
        assert is_nap(build_session(total_duration=22.0), threshold=30.0) is True
        assert is_nap(build_session(total_duration=44.0), threshold=30.0) is False


class TestGrouping:
    def test_two_providers_reporting_the_same_night_collapse_to_one(self) -> None:
        garmin = build_session(session_id="g", source="garmin")
        oura = build_session(session_id="o", source="oura", start=T0 + dt.timedelta(minutes=6))
        nights = group_nights([garmin, oura])
        assert len(nights) == 1
        assert len(nights[0].others) == 1

    def test_separate_nights_stay_separate(self) -> None:
        nights = group_nights(
            [build_session(session_id="a"), build_session(session_id="b", start=T0 + DAY)]
        )
        assert len(nights) == 2

    def test_the_session_with_more_stage_samples_wins(self) -> None:
        """The hypnogram is the point of the page, so the richer timeline wins."""
        coarse = build_session(session_id="coarse", source="oura", spans=((480, SleepStage.LIGHT),))
        rich = build_session(session_id="rich", source="garmin")
        for order in ([coarse, rich], [rich, coarse]):
            assert group_nights(order)[0].session.id == "rich"

    def test_the_winner_is_deterministic_when_every_tiebreak_is_equal(self) -> None:
        """Identical data from two providers must always render the same way, or the
        page changes under the reader for no reason."""
        a = build_session(session_id="a", source="zebra")
        b = build_session(session_id="b", source="alpha")
        for order in ([a, b], [b, a]):
            assert group_nights(order)[0].session.source == "alpha"

    def test_scalars_are_never_blended_across_providers(self) -> None:
        rich = build_session(session_id="rich", source="garmin")
        coarse = build_session(session_id="coarse", source="oura", spans=((480, SleepStage.LIGHT),))
        night = group_nights([rich, coarse])[0]
        assert night.session.efficiency is not None
        assert night.session.efficiency.source == "garmin"
        assert night.other_sources == ("oura",)

    def test_nights_come_back_newest_first(self) -> None:
        nights = group_nights(
            [build_session(session_id="old"), build_session(session_id="new", start=T0 + DAY)]
        )
        assert [n.key for n in nights] == ["new", "old"]


class TestNapFiltering:
    def test_a_nap_is_hidden_and_counted(self) -> None:
        night = build_session(session_id="night")
        nap = build_session(session_id="nap", start=T0 + DAY, minutes=20, total_duration=18.0)
        nights, hidden = nights_from([night, nap], nap_minutes=30.0)
        assert [n.key for n in nights] == ["night"]
        assert hidden == 1

    def test_lowering_the_threshold_keeps_the_short_night(self) -> None:
        """30 minutes hides real nights for people with fragmented sleep, which is
        why it is a setting rather than a constant."""
        nap = build_session(session_id="nap", minutes=20, total_duration=18.0)
        nights, hidden = nights_from([nap], nap_minutes=5.0)
        assert [n.key for n in nights] == ["nap"]
        assert hidden == 0


class TestSelection:
    def _three(self) -> list:
        return group_nights(
            [
                build_session(session_id="d1", start=T0),
                build_session(session_id="d2", start=T0 + DAY),
                build_session(session_id="d3", start=T0 + 2 * DAY),
            ]
        )

    def test_no_key_selects_the_latest_night(self) -> None:
        assert select(self._three(), None).night is not None
        assert select(self._three(), None).night.key == "d3"  # type: ignore[union-attr]

    def test_earlier_and_later_navigate_in_wall_clock_order_not_list_order(self) -> None:
        """The list is newest-first, so nights[index + 1] is the EARLIER night.
        Naming these prev/next is how you ship arrows that go the wrong way."""
        selection = select(self._three(), "d2")
        assert selection.earlier_key == "d1"
        assert selection.later_key == "d3"

    def test_the_latest_night_has_nothing_later(self) -> None:
        selection = select(self._three(), "d3")
        assert selection.later_key is None
        assert selection.earlier_key == "d2"

    def test_the_earliest_night_has_nothing_earlier(self) -> None:
        selection = select(self._three(), "d1")
        assert selection.earlier_key is None

    def test_an_unknown_night_key_falls_back_to_the_latest(self) -> None:
        """A bookmark to a night that has since aged out of the fetch window must
        not 404."""
        selection = select(self._three(), "no-such-night")
        assert selection.night is not None
        assert selection.night.key == "d3"

    def test_a_key_naming_a_deduped_loser_resolves_to_its_winner(self) -> None:
        rich = build_session(session_id="rich", source="garmin")
        coarse = build_session(session_id="coarse", source="oura", spans=((480, SleepStage.LIGHT),))
        selection = select(group_nights([rich, coarse]), "coarse")
        assert selection.night is not None
        assert selection.night.key == "rich"

    def test_selecting_from_nothing_yields_no_night(self) -> None:
        selection = select([], None)
        assert selection.night is None
        assert selection.earlier_key is None and selection.later_key is None
