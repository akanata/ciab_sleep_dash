"""Grouping sessions into nights, and choosing which night to show. Pure.

``get_sleep_sessions_merged`` concatenates every provider's sessions, sorts them
newest-first, and does NOT dedupe -- so two watches on the same wrist produce two
sessions for the same night. This module collapses those into one Night.
"""

import datetime as dt
from collections.abc import Iterable
from collections.abc import Sequence

import attrs
from health_data_service.sleep_types import SleepSession


def duration_minutes(session: SleepSession) -> float:
    """How long the sleeper actually slept, in minutes.

    Prefers the provider's own figure; falls back to the session's wall-clock span,
    because ``total_duration`` is ``| None`` on every session.
    """
    reported = session.total_duration
    if reported is not None and reported.value is not None:
        return float(reported.value)
    return (session.end - session.start).total_seconds() / 60.0


def is_nap(session: SleepSession, *, threshold: float) -> bool:
    return duration_minutes(session) < threshold


@attrs.frozen
class Night:
    """One night's sleep, and any other providers' takes on the same night."""

    session: SleepSession
    others: tuple[SleepSession, ...] = ()

    @property
    def key(self) -> str:
        return self.session.id

    @property
    def keys(self) -> tuple[str, ...]:
        """Every session id that should resolve to this night."""
        return (self.session.id, *(s.id for s in self.others))

    @property
    def other_sources(self) -> tuple[str, ...]:
        return tuple(sorted({s.source for s in self.others if s.source}))


def _richness(session: SleepSession) -> tuple[int, int, float, str]:
    """The winner ordering, most significant first, as a sortable key.

    Stage-sample count leads because the hypnogram is the point of this page. The
    alphabetical source is a tiebreak of last resort so that identical data always
    renders identically -- a page that changes under the reader for no reason is
    worse than either choice.
    """
    stages = len(session.stages.samples) if session.stages is not None else 0
    heart = len(session.heart_rate.samples) if session.heart_rate is not None else 0
    return (stages, heart, duration_minutes(session), session.source or "")


def _pick_winner(group: list[SleepSession]) -> Night:
    # max() on the first three, but the source tiebreak runs the other way: lowest
    # alphabetically wins, so it cannot be folded into a single max() key.
    best = group[0]
    for candidate in group[1:]:
        c_stages, c_heart, c_dur, c_src = _richness(candidate)
        b_stages, b_heart, b_dur, b_src = _richness(best)
        if (c_stages, c_heart, c_dur) > (b_stages, b_heart, b_dur):
            best = candidate
        elif (c_stages, c_heart, c_dur) == (b_stages, b_heart, b_dur) and c_src < b_src:
            best = candidate
    return Night(session=best, others=tuple(s for s in group if s is not best))


def group_nights(sessions: Iterable[SleepSession]) -> list[Night]:
    """Collapse overlapping sessions into nights, newest first.

    Any overlap at all means "the same night": two devices never agree to the minute
    on when sleep began, and a 6-minute disagreement is not two nights.
    """
    ordered = sorted(sessions, key=lambda s: s.start)
    groups: list[list[SleepSession]] = []
    group_end: dt.datetime | None = None
    for session in ordered:
        if group_end is None or session.start >= group_end:
            groups.append([session])
            group_end = session.end
        else:
            groups[-1].append(session)
            group_end = max(group_end, session.end)
    nights = [_pick_winner(group) for group in groups]
    nights.sort(key=lambda n: n.session.start, reverse=True)
    return nights


def nights_from(sessions: Iterable[SleepSession], *, nap_minutes: float) -> tuple[list[Night], int]:
    """Nights worth showing, plus how many short sessions were hidden."""
    kept = [s for s in sessions if not is_nap(s, threshold=nap_minutes)]
    hidden = sum(1 for s in sessions if is_nap(s, threshold=nap_minutes))
    return group_nights(kept), hidden


@attrs.frozen
class Selection:
    """Which night is on screen, and where the navigation arrows point."""

    night: Night | None
    index: int = 0
    # Named for wall-clock direction, not list position: the list is newest-first,
    # so the earlier night is at index + 1.
    earlier_key: str | None = None
    later_key: str | None = None
    total: int = 0


def select(nights: Sequence[Night], key: str | None) -> Selection:
    """Resolve ``?night=`` to a night and its neighbours.

    An unknown key falls back to the latest night rather than raising: a bookmark to
    a night that has aged out of the fetch window must not 404. A key naming a
    session that lost its dedupe resolves to the winner of its group.
    """
    if not nights:
        return Selection(night=None)
    index = 0
    if key is not None:
        for position, night in enumerate(nights):
            if key in night.keys:
                index = position
                break
    return Selection(
        night=nights[index],
        index=index,
        earlier_key=nights[index + 1].key if index + 1 < len(nights) else None,
        later_key=nights[index - 1].key if index > 0 else None,
        total=len(nights),
    )
