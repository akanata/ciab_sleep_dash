"""The Litestar app object and its wiring.

``create_app`` takes its collaborators as keyword arguments so tests can build an
isolated app around a fake gateway; the module-level ``app`` at the bottom is what
``hypercorn sleep_dash.app:app`` serves.
"""

import logging

from litestar import Litestar
from litestar import get
from litestar.datastructures import State

from sleep_dash.config import Settings
from sleep_dash.config import settings_from_env
from sleep_dash.health import HealthGateway
from sleep_dash.health import RouterHealthGateway
from sleep_dash.routes.dash import dash_router

logger = logging.getLogger(__name__)


@get("/health", sync_to_thread=False)
def health() -> dict[str, str]:
    """The router's liveness probe.

    Registered on the app rather than on ``dash_router``, which puts it outside the
    owner guard (the probe carries no owner header) and outside the dashboard's
    exception handlers (no health-service state can reach it).

    Deliberately unconditional: an unconfigured service, an unreachable provider and
    a night with no data are all normal states awaiting attention, and failing the
    probe for any of them would make the router restart a container that is working
    correctly -- and that the owner needs running to fix the problem.
    """
    return {"status": "ok"}


def create_app(
    *,
    settings: Settings | None = None,
    gateway: HealthGateway | None = None,
) -> Litestar:
    settings = settings if settings is not None else settings_from_env()
    gateway = gateway if gateway is not None else RouterHealthGateway(settings)
    state = State({"settings": settings, "gateway": gateway})
    return Litestar(route_handlers=[health, dash_router], state=state)


logging.basicConfig(level=logging.INFO)

app = create_app()
