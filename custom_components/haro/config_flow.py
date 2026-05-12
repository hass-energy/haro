"""Config flow for HARO."""

from __future__ import annotations

from typing import Any

try:
    import voluptuous as vol
    from homeassistant import config_entries
    from homeassistant.helpers import selector
except Exception:  # pragma: no cover - lets pure unit tests import the module without HA installed.
    vol = None
    config_entries = None
    selector = None

from .const import CONF_HAEO_CONFIG_ENTRY_ID, CONF_TOKEN, DEFAULT_REPLAY_URL, DOMAIN
from .replay_client import ReplayWebSocketClient


async def validate_replay_connection(replay_url: str, token: str) -> None:
    """Require successful Replay websocket auth."""
    client = ReplayWebSocketClient(replay_url, token)
    await client.connect()
    await client.close()


if config_entries is not None and vol is not None and selector is not None:
    _vol = vol
    _selector = selector
    NO_HAEO_ENTRY_OPTION = "__no_haeo_entries__"

    class HaroConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):  # type: ignore[misc]
        """Handle a HARO config flow."""

        VERSION = 1
        MINOR_VERSION = 0

        async def async_step_user(self, user_input: dict[str, Any] | None = None) -> Any:
            """Create HARO config entry."""
            errors: dict[str, str] = {}
            haeo_entries = self.hass.config_entries.async_entries("haeo")

            if user_input is not None:
                selected_entry_id = str(user_input[CONF_HAEO_CONFIG_ENTRY_ID])
                selected_entry = next((entry for entry in haeo_entries if entry.entry_id == selected_entry_id), None)
                if selected_entry is None:
                    errors["base"] = "invalid_haeo_entry"
                else:
                    existing_entry = await self.async_set_unique_id(selected_entry_id)
                    if existing_entry is not None:
                        return self.async_abort(reason="already_configured")

                try:
                    if not errors:
                        await validate_replay_connection(DEFAULT_REPLAY_URL, str(user_input[CONF_TOKEN]))
                except Exception:
                    if not errors:
                        errors["base"] = "cannot_connect"
                else:
                    if not errors and selected_entry is not None:
                        return self.async_create_entry(title=f"HARO - {selected_entry.title}", data=user_input)

            options = [
                _selector.SelectOptionDict(value=entry.entry_id, label=entry.title or entry.entry_id)
                for entry in haeo_entries
            ]
            if not options:
                options = [_selector.SelectOptionDict(value=NO_HAEO_ENTRY_OPTION, label="No HAEO installs found")]

            schema = _vol.Schema(
                {
                    _vol.Required(CONF_HAEO_CONFIG_ENTRY_ID): _selector.SelectSelector(
                        _selector.SelectSelectorConfig(options=options, mode=_selector.SelectSelectorMode.DROPDOWN)
                    ),
                    _vol.Required(CONF_TOKEN): str,
                }
            )
            return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

else:
    HaroConfigFlow: Any
    HaroConfigFlow = object
