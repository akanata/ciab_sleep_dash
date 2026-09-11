"""Parsing helpers for the whole-page contract tests."""

import re
from html.parser import HTMLParser

# Any text that reads as a clock time to a human: 9:05, 23:14, 06:30.
CLOCK = re.compile(r"\b\d{1,2}:\d{2}\b")


class TimeTextCollector(HTMLParser):
    """Collects every text node that looks like a clock time, with the data-ts of
    the element containing it.

    The browser localises times by rewriting elements carrying ``data-ts``. Any
    clock time rendered *without* one is a time frozen in UTC that the localisation
    pass will never touch -- a silent, permanent bug for every viewer outside UTC.
    """

    # HTMLParser hands script/style bodies to handle_data as though they were
    # text. They are machine payloads -- the JSON island's own ISO timestamps
    # contain "22:10" -- so they are not what this contract is about.
    OPAQUE = frozenset({"script", "style"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        # (text, data-ts of the innermost enclosing element or None)
        self.times: list[tuple[str, str | None]] = []
        self._stack: list[str | None] = []
        self._opaque_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.OPAQUE:
            self._opaque_depth += 1
            return
        if tag in {"br", "img", "meta", "link", "input", "hr"}:
            return
        self._stack.append(dict(attrs).get("data-ts"))

    def handle_endtag(self, tag: str) -> None:
        if tag in self.OPAQUE:
            self._opaque_depth = max(0, self._opaque_depth - 1)
            return
        if self._stack:
            self._stack.pop()

    def handle_data(self, data: str) -> None:
        if self._opaque_depth:
            return
        for match in CLOCK.finditer(data):
            enclosing = self._stack[-1] if self._stack else None
            self.times.append((match.group(0), enclosing))


def clock_times(html: str) -> list[tuple[str, str | None]]:
    parser = TimeTextCollector()
    parser.feed(html)
    return parser.times


class StampedCollector(HTMLParser):
    """Collects (data-ts, data-fmt, text) for every element carrying data-ts."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stamped: list[tuple[str, str, str]] = []
        self._open: list[tuple[str, str, list[str]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        found = dict(attrs)
        ts = found.get("data-ts")
        if ts is not None:
            self._open.append((ts, found.get("data-fmt") or "hm", []))

    def handle_endtag(self, tag: str) -> None:
        if self._open:
            ts, fmt, chunks = self._open.pop()
            self.stamped.append((ts, fmt, "".join(chunks).strip()))

    def handle_data(self, data: str) -> None:
        if self._open:
            self._open[-1][2].append(data)


def stamped_times(html: str) -> list[tuple[str, str, str]]:
    parser = StampedCollector()
    parser.feed(html)
    return parser.stamped
