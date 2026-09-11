"""The dashboard route, its owner gate, and the degraded pages.

The theme of this module is that *no upstream failure may reach the router as a
failure*. A blank dashboard is a normal state; a 500 or a dead /health is not.
"""

import datetime as dt
from collections.abc import Iterator

import pytest
from litestar.testing import TestClient

from sleep_dash.app import create_app
from sleep_dash.config import Settings
from sleep_dash.health import HealthTransportError
from sleep_dash.health import HealthUnavailable
from tests.fakes import FakeHealthGateway
from tests.fakes import empty_snapshot
from tests.fakes import running
from tests.fakes import snapshot_of
from tests.fixtures import T0
from tests.fixtures import build_session

OWNER = {"X-OpenHost-Is-Owner": "true"}


def client_for(result: object) -> Iterator[TestClient]:
    gateway = FakeHealthGateway(result=result)  # type: ignore[arg-type]
    with TestClient(app=create_app(settings=Settings(), gateway=gateway)) as client:
        yield client


@pytest.fixture
def client() -> Iterator[TestClient]:
    yield from client_for(empty_snapshot(providers=(running("garmin"),)))


@pytest.fixture
def unavailable() -> Iterator[TestClient]:
    yield from client_for(HealthUnavailable("no router url"))


@pytest.fixture
def unreachable() -> Iterator[TestClient]:
    yield from client_for(HealthTransportError("provider timed out"))


class TestLivenessProbe:
    """The router restart-loops a container whose health check fails, so /health
    has to survive every state the health service can be in."""

    def test_health_answers_two_hundred_while_the_gateway_is_raising(
        self, unreachable: TestClient
    ) -> None:
        response = unreachable.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_health_is_reachable_without_the_owner_header(self, client: TestClient) -> None:
        """The router's probe carries no owner header. If /health sat behind the
        owner guard it would 401 and the container would never be marked booted."""
        assert client.get("/health").status_code == 200


class TestOwnerGate:
    def test_the_dashboard_requires_the_owner_header(self, client: TestClient) -> None:
        assert client.get("/").status_code == 401

    def test_the_dashboard_renders_for_the_owner(self, client: TestClient) -> None:
        response = client.get("/", headers=OWNER)
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")


class TestDegradedPages:
    """Every one of these is a page the owner can read, never a stack trace."""

    def test_not_being_connected_is_a_two_hundred_page_not_an_error(
        self, unavailable: TestClient
    ) -> None:
        """A bottle with no health provider installed is a complete, correct page.
        A 503 here would invite intermediaries to retry something that will never
        succeed until the owner installs a provider."""
        response = unavailable.get("/", headers=OWNER)
        assert response.status_code == 200
        assert "no health data service" in response.text.lower()

    def test_a_provider_timeout_is_a_five_oh_three_page_not_a_stack_trace(
        self, unreachable: TestClient
    ) -> None:
        response = unreachable.get("/", headers=OWNER)
        assert response.status_code == 503
        assert "Traceback" not in response.text
        assert "provider timed out" not in response.text  # no raw exception text
        assert "<html" in response.text

    def test_a_degraded_page_is_still_html_not_json(self, unavailable: TestClient) -> None:
        response = unavailable.get("/", headers=OWNER)
        assert response.headers["content-type"].startswith("text/html")

    def test_a_running_provider_with_no_sessions_says_so(self, client: TestClient) -> None:
        body = client.get("/", headers=OWNER).text.lower()
        assert "no sleep sessions" in body

    def test_a_night_renders_both_charts(self) -> None:
        for real in client_for(snapshot_of(build_session(), providers=(running("garmin"),))):
            body = real.get("/", headers=OWNER).text
            assert "class='stage'" in body
            assert "class='hr-line'" in body
            assert "id='crosshair'" in body

    def test_the_night_query_parameter_selects_that_night(self) -> None:
        older = build_session(session_id="older", start=T0)
        newer = build_session(session_id="newer", start=T0 + dt.timedelta(days=1))
        for real in client_for(snapshot_of(older, newer, providers=(running("garmin"),))):
            default = real.get("/", headers=OWNER).text
            picked = real.get("/?night=older", headers=OWNER).text
            # The default is the newest night, so asking for the older one differs,
            # and from it the only navigation available is back to the later night.
            assert default != picked
            assert "?night=newer" in picked

    def test_an_unknown_night_key_does_not_four_oh_four(self) -> None:
        """A bookmark to a night that has aged out of the fetch window."""
        for real in client_for(snapshot_of(build_session(), providers=(running("garmin"),))):
            assert real.get("/?night=long-gone", headers=OWNER).status_code == 200

    def test_zero_sessions_and_zero_providers_are_different_pages(self, client: TestClient) -> None:
        """One means "nothing has synced yet", the other means "nothing is
        installed". Conflating them sends the owner to the wrong place to fix it."""
        with_provider = client.get("/", headers=OWNER).text
        for none_at_all in client_for(empty_snapshot(providers=())):
            without = none_at_all.get("/", headers=OWNER).text
        assert with_provider != without
        assert "no health data provider" in without.lower()
