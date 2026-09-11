"""The dashboard route.

Exception-to-page mapping is done with ``Router(exception_handlers=...)`` rather than
try/except inside the handler, so there is exactly one place that decides what a
failure looks like -- and it always looks like a readable page, never a stack trace
and never JSON.
"""

import datetime as dt
import logging
from typing import Annotated
from typing import Any

from litestar import MediaType
from litestar import Request
from litestar import Response
from litestar import Router
from litestar import get
from litestar.connection import ASGIConnection
from litestar.datastructures import State
from litestar.exceptions import NotAuthorizedException
from litestar.handlers.base import BaseRouteHandler
from litestar.params import QueryParameter
from litestar.status_codes import HTTP_200_OK
from litestar.status_codes import HTTP_503_SERVICE_UNAVAILABLE

from sleep_dash.health import HealthGateway
from sleep_dash.health import HealthTransportError
from sleep_dash.health import HealthUnavailable
from sleep_dash.page import render
from sleep_dash.view import NOT_CONNECTED
from sleep_dash.view import UNREACHABLE
from sleep_dash.view import Notice
from sleep_dash.view import build_view
from sleep_dash.view import notice_view

logger = logging.getLogger(__name__)


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def owner_guard(connection: ASGIConnection[Any, Any, Any, Any], _: BaseRouteHandler) -> None:
    """Belt and braces with the router's own session gate.

    The router strips any client-supplied ``X-OpenHost-*`` before stamping its own,
    so this header is trustworthy.
    """
    if connection.headers.get("x-openhost-is-owner") != "true":
        raise NotAuthorizedException()


@get("/", media_type=MediaType.HTML)
async def dashboard(
    state: State,
    night: Annotated[str | None, QueryParameter(name="night", required=False)] = None,
) -> str:
    gateway: HealthGateway = state.gateway
    snapshot = await gateway.snapshot()
    return render(build_view(snapshot, night, state.settings, rendered_at=_utcnow()))


def _page_problem(status: int, notice: Notice) -> Any:
    """Render the page shell with an explanatory card instead of an error body."""

    def handler(_: Request[Any, Any, Any], exc: Exception) -> Response[str]:
        if status >= HTTP_503_SERVICE_UNAVAILABLE:
            logger.warning("Health service unavailable: %s", exc)
        return Response(
            content=render(notice_view(notice, rendered_at=_utcnow())),
            media_type=MediaType.HTML,
            status_code=status,
        )

    return handler


dash_router = Router(
    path="/",
    route_handlers=[dashboard],
    guards=[owner_guard],
    exception_handlers={
        # A bottle with no health provider installed is a complete, correct page --
        # not a server error, and not something a retry will fix.
        HealthUnavailable: _page_problem(HTTP_200_OK, NOT_CONNECTED),
        # Something upstream really did fail, and 503 is the honest signal.
        HealthTransportError: _page_problem(HTTP_503_SERVICE_UNAVAILABLE, UNREACHABLE),
    },
)
