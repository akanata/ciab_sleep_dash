"""The manifest and the code have to agree, or the app is invisible.

This is the failure class that produces no error anywhere. The spec's client builds
``{router}/api/services/v2/call/{shortname}``; if the manifest declares a different
shortname, or a different service string, the router has nowhere to route us. The
call 404s, ``_call_provider`` returns None, ``_fan_out`` filters it out, and
``get_sleep_sessions_merged`` hands back an empty list. No exception, no log line,
no non-200 -- just a dashboard that says "no sleep sessions" forever while a
provider sits there full of data.

The sibling connector carries the mirror image of this test because the provider
side already got burned by it (``endpoint = "/v1/"`` landing requests on
``/v1/v1/metrics``).
"""

import tomllib
from pathlib import Path
from typing import Any

import pytest
from litestar.testing import TestClient

from sleep_dash.app import create_app
from sleep_dash.config import DEFAULT_SHORTNAME

MANIFEST = Path(__file__).resolve().parents[1] / "openhost.toml"

# The spec hardcodes this as SERVICE_URL in client.py, even on the repo whose org
# has since been renamed to cloud-in-a-bottle. The router matches a provider's
# service string against the consumer's, so this exact string is what routes.
SPEC_SERVICE_URL = "github.com/imbue-openhost/health-data-service-spec"


@pytest.fixture(scope="module")
def manifest() -> dict[str, Any]:
    return tomllib.loads(MANIFEST.read_text())


@pytest.fixture(scope="module")
def consumes(manifest: dict[str, Any]) -> dict[str, Any]:
    blocks = manifest["services"]["v2"]["consumes"]
    assert len(blocks) == 1, "exactly one consumed service is expected"
    block: dict[str, Any] = blocks[0]
    return block


class TestServiceRouting:
    """The three keys whose failure mode is a silently blank dashboard."""

    def test_the_shortname_the_client_uses_is_the_one_the_manifest_declares(
        self, consumes: dict[str, Any]
    ) -> None:
        assert consumes["shortname"] == DEFAULT_SHORTNAME

    def test_the_manifest_consumes_exactly_the_spec_service(self, consumes: dict[str, Any]) -> None:
        assert consumes["service"] == SPEC_SERVICE_URL

    def test_the_consumer_block_declares_no_endpoint(self, consumes: dict[str, Any]) -> None:
        """``endpoint`` is a provider-only key: the router prepends it to inbound
        service requests. On a consumer it is meaningless, and copying one in from
        the sibling provider's manifest is an easy and silent mistake."""
        assert "endpoint" not in consumes

    def test_the_declared_version_is_a_range_not_a_pin(self, consumes: dict[str, Any]) -> None:
        """Consumers state a specifier, providers state a concrete version. A bare
        "0.1.0" here would stop matching the moment a provider ships 0.1.1."""
        assert consumes["version"].startswith(">=")


class TestRuntimeContract:
    """Keys the router reads to run the container at all."""

    def test_resources_use_cpu_cores_not_cpu_millicores(self, manifest: dict[str, Any]) -> None:
        """cpu_millicores is silently ignored and yields the 0.1-core default.
        health-dashboard uses it; copying that in is the regression this guards."""
        resources = manifest["resources"]
        assert "cpu_cores" in resources
        assert "cpu_millicores" not in resources

    def test_no_path_is_public(self, manifest: dict[str, Any]) -> None:
        """This is the owner's own sleep data. Every route stays behind the
        router's owner gate."""
        assert manifest["routing"]["public_paths"] == []

    def test_the_container_port_is_the_one_the_app_binds(self, manifest: dict[str, Any]) -> None:
        assert manifest["runtime"]["container"]["port"] == 8080

    def test_the_health_check_path_is_actually_served(self, manifest: dict[str, Any]) -> None:
        """A health_check pointing at a path the app does not serve makes the router
        conclude the container never booted and restart-loop it forever."""
        path = manifest["routing"]["health_check"]
        with TestClient(app=create_app()) as client:
            assert client.get(path).status_code == 200
