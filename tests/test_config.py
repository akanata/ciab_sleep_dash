"""Settings parsing.

The load-bearing property here is that a missing router URL or app token is a
*state*, not an error. The spec's own ``HealthDataClient.__init__`` does an
unguarded ``os.environ["OPENHOST_ROUTER_URL"]`` and raises KeyError; if we let that
happen at app construction, ``create_app()`` fails, ``/health`` never answers, and
the router restart-loops the container the owner would have used to fix it.
"""

import pytest

from sleep_dash.config import DEFAULT_HR_GAP_SECONDS
from sleep_dash.config import DEFAULT_NAP_MINUTES
from sleep_dash.config import DEFAULT_SESSION_LIMIT
from sleep_dash.config import DEFAULT_SHORTNAME
from sleep_dash.config import ConfigError
from sleep_dash.config import settings_from_env


class TestConnectedness:
    def test_missing_router_env_is_not_connected_rather_than_an_exception(self) -> None:
        settings = settings_from_env({})
        assert settings.connected is False
        assert settings.router_url is None
        assert settings.app_token is None

    def test_a_url_without_a_token_is_still_not_connected(self) -> None:
        """Half a configuration is not a configuration. Constructing the client with
        a None token would send ``Authorization: Bearer None``."""
        settings = settings_from_env({"OPENHOST_ROUTER_URL": "https://router.example"})
        assert settings.connected is False

    def test_both_vars_present_is_connected(self) -> None:
        settings = settings_from_env(
            {"OPENHOST_ROUTER_URL": "https://router.example", "OPENHOST_APP_TOKEN": "tok"}
        )
        assert settings.connected is True
        assert settings.router_url == "https://router.example"
        assert settings.app_token == "tok"


class TestEnvVarRenaming:
    """Cloud in a Bottle renamed OPENHOST_* to BOTTLE_*, but the deployed apps and
    the spec's own client still export and read the old names. Both are accepted."""

    def test_the_legacy_openhost_names_are_accepted(self) -> None:
        settings = settings_from_env(
            {"OPENHOST_ROUTER_URL": "https://old.example", "OPENHOST_APP_TOKEN": "old"}
        )
        assert settings.router_url == "https://old.example"

    def test_the_new_bottle_names_are_accepted(self) -> None:
        settings = settings_from_env(
            {"BOTTLE_ROUTER_URL": "https://new.example", "BOTTLE_APP_TOKEN": "new"}
        )
        assert settings.router_url == "https://new.example"

    def test_the_new_name_wins_when_both_are_set(self) -> None:
        settings = settings_from_env(
            {
                "OPENHOST_ROUTER_URL": "https://old.example",
                "BOTTLE_ROUTER_URL": "https://new.example",
                "OPENHOST_APP_TOKEN": "old",
                "BOTTLE_APP_TOKEN": "new",
            }
        )
        assert settings.router_url == "https://new.example"
        assert settings.app_token == "new"


class TestTunableKnobs:
    def test_the_defaults_are_the_documented_ones(self) -> None:
        settings = settings_from_env({})
        assert settings.shortname == DEFAULT_SHORTNAME
        assert settings.session_limit == DEFAULT_SESSION_LIMIT
        assert settings.nap_minutes == DEFAULT_NAP_MINUTES
        assert settings.hr_gap_seconds == DEFAULT_HR_GAP_SECONDS

    def test_the_session_limit_can_be_tuned_by_env(self) -> None:
        assert settings_from_env({"SLEEP_DASH_SESSION_LIMIT": "5"}).session_limit == 5

    def test_the_nap_threshold_can_be_tuned_by_env(self) -> None:
        """30 minutes hides real short nights for people with fragmented sleep."""
        assert settings_from_env({"SLEEP_DASH_NAP_MINUTES": "5"}).nap_minutes == 5.0

    @pytest.mark.parametrize(
        ("name", "value"),
        [
            ("SLEEP_DASH_SESSION_LIMIT", "not-a-number"),
            ("SLEEP_DASH_SESSION_LIMIT", "0"),
            ("SLEEP_DASH_SESSION_LIMIT", "-3"),
            ("SLEEP_DASH_NAP_MINUTES", "maybe"),
            ("SLEEP_DASH_HR_GAP_SECONDS", ""),
            ("SLEEP_DASH_CACHE_TTL_SECONDS", "-1"),
        ],
    )
    def test_an_unparseable_knob_is_an_error_rather_than_a_silent_default(
        self, name: str, value: str
    ) -> None:
        """Silently reading "not-a-number" as the default would leave the owner
        believing they had changed something."""
        with pytest.raises(ConfigError):
            settings_from_env({name: value})
