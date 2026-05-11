"""Config flow for HARO."""

from __future__ import annotations

from typing import Any

try:
    import voluptuous as vol
    from homeassistant import config_entries
except Exception:  # pragma: no cover - lets pure unit tests import the module without HA installed.
    vol = None
    config_entries = None

from .const import CONF_REPLAY_URL, CONF_TOKEN, DEFAULT_REPLAY_URL, DOMAIN
from .replay_client import ReplayWebSocketClient


async def validate_replay_connection(replay_url: str, token: str) -> None:
    """Require successful Replay websocket auth."""
    client = ReplayWebSocketClient(replay_url, token)
    await client.connect()
    await client.close()


if config_entries is not None and vol is not None:
    _vol = vol

    class HaroConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):  # type: ignore[misc]
        """Handle a HARO config flow."""

        VERSION = 1
        MINOR_VERSION = 0

        async def async_step_user(self, user_input: dict[str, Any] | None = None) -> Any:
            """Create HARO config entry."""
            errors: dict[str, str] = {}
            if user_input is not None:
                try:
                    await validate_replay_connection(str(user_input[CONF_REPLAY_URL]), str(user_input[CONF_TOKEN]))
                except Exception:
                    errors["base"] = "cannot_connect"
                else:
                    return self.async_create_entry(title="HARO", data=user_input)

            schema = _vol.Schema(
                {_vol.Required(CONF_REPLAY_URL, default=DEFAULT_REPLAY_URL): str, _vol.Required(CONF_TOKEN): str}
            )
            return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

else:
    HaroConfigFlow: Any
    HaroConfigFlow = object
