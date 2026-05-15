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

from .const import (
    CONF_HAEO_CONFIG_ENTRY_ID,
    CONF_REPLAY_SITE_ID,
    CONF_REPLAY_SITE_NAME,
    CONF_TOKEN,
    DEFAULT_REPLAY_URL,
    DOMAIN,
)


def _setup_api_url(replay_url: str, path: str) -> str:
    """Return the HTTP setup API URL for a Replay websocket URL."""
    if replay_url.startswith("wss://"):
        base = f"https://{replay_url[6:].rstrip('/')}"
    elif replay_url.startswith("ws://"):
        base = f"http://{replay_url[5:].rstrip('/')}"
    else:
        base = replay_url.rstrip("/")
    return f"{base}/api/ingest/setup{path}"


async def bind_replay_site(
    replay_url: str,
    token: str,
    site_id: str,
    haeo_entry_id: str,
    *,
    confirm: bool = False,
) -> None:
    """Bind the selected Replay site to this HAEO config entry."""
    import aiohttp

    async with (
        aiohttp.ClientSession() as session,
        session.post(
            _setup_api_url(replay_url, f"/sites/{site_id}/bind"),
            headers={"Authorization": f"Bearer {token}"},
            json={"haeo_entry_id": haeo_entry_id, "confirm": confirm},
        ) as response,
    ):
        if response.status >= 400:
            raise RuntimeError(f"Replay setup failed: {response.status}")


async def fetch_replay_sites(replay_url: str, token: str) -> list[dict[str, Any]]:
    """Return Replay sites owned by the user token."""
    import aiohttp

    async with (
        aiohttp.ClientSession() as session,
        session.get(
            _setup_api_url(replay_url, "/sites"),
            headers={"Authorization": f"Bearer {token}"},
        ) as response,
    ):
        if response.status >= 400:
            raise RuntimeError(f"Replay setup failed: {response.status}")
        payload = await response.json()
        sites = payload.get("sites", [])
        return sites if isinstance(sites, list) else []


async def create_replay_site(replay_url: str, token: str, name: str) -> dict[str, Any]:
    """Create a Replay site owned by the user token."""
    import aiohttp

    async with (
        aiohttp.ClientSession() as session,
        session.post(
            _setup_api_url(replay_url, "/sites"),
            headers={"Authorization": f"Bearer {token}"},
            json={"name": name},
        ) as response,
    ):
        if response.status >= 400:
            raise RuntimeError(f"Replay setup failed: {response.status}")
        payload = await response.json()
        site = payload.get("site", {})
        return site if isinstance(site, dict) else {}


if config_entries is not None and vol is not None and selector is not None:
    _vol = vol
    _selector = selector
    NO_HAEO_ENTRY_OPTION = "__no_haeo_entries__"
    CREATE_SITE_OPTION = "__create_site__"

    def _site_id_matching_haeo_entry(sites: list[dict[str, Any]], haeo_entry_id: str) -> str | None:
        """Return the Replay site already bound to the selected HAEO entry."""
        for site in sites:
            if str(site.get("haeo_entry_id", "")) == haeo_entry_id:
                site_id = str(site.get("id", "")).strip()
                if site_id:
                    return site_id
        return None

    class HaroConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):  # type: ignore[misc]
        """Handle a HARO config flow."""

        VERSION = 1
        MINOR_VERSION = 0

        _token: str | None = None
        _haeo_entry_id: str | None = None
        _haeo_title: str | None = None
        _sites: list[dict[str, Any]]

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
                        self._token = str(user_input[CONF_TOKEN])
                        self._haeo_entry_id = selected_entry_id
                        self._haeo_title = selected_entry.title if selected_entry is not None else selected_entry_id
                        self._sites = await fetch_replay_sites(DEFAULT_REPLAY_URL, self._token)
                except Exception:
                    if not errors:
                        errors["base"] = "cannot_connect"
                else:
                    if not errors and selected_entry is not None:
                        return await self.async_step_site()

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

        async def async_step_site(self, user_input: dict[str, Any] | None = None) -> Any:
            """Pick or create the Replay site to bind to this HAEO entry."""
            errors: dict[str, str] = {}
            token = self._token
            haeo_entry_id = self._haeo_entry_id
            if token is None or haeo_entry_id is None:
                return await self.async_step_user()

            if user_input is not None:
                selected_site_id = str(user_input.get(CONF_REPLAY_SITE_ID, "")).strip()
                if selected_site_id == CREATE_SITE_OPTION:
                    return await self.async_step_create_site()
                try:
                    await bind_replay_site(DEFAULT_REPLAY_URL, token, selected_site_id, haeo_entry_id, confirm=True)
                except Exception:
                    if not errors:
                        errors["base"] = "cannot_connect"
                else:
                    title = self._haeo_title or haeo_entry_id
                    return self.async_create_entry(
                        title=f"HARO - {title}",
                        data={
                            CONF_HAEO_CONFIG_ENTRY_ID: haeo_entry_id,
                            CONF_TOKEN: token,
                            CONF_REPLAY_SITE_ID: selected_site_id,
                        },
                    )

            options = [
                _selector.SelectOptionDict(
                    value=str(site.get("id")),
                    label=str(site.get("name") or site.get("id")),
                )
                for site in getattr(self, "_sites", [])
                if site.get("id")
            ]
            options.append(_selector.SelectOptionDict(value=CREATE_SITE_OPTION, label="Create a new Replay site"))
            default_site_id = _site_id_matching_haeo_entry(getattr(self, "_sites", []), haeo_entry_id)
            schema = _vol.Schema(
                {
                    _vol.Required(
                        CONF_REPLAY_SITE_ID, default=default_site_id or CREATE_SITE_OPTION
                    ): _selector.SelectSelector(
                        _selector.SelectSelectorConfig(options=options, mode=_selector.SelectSelectorMode.DROPDOWN)
                    ),
                }
            )
            return self.async_show_form(step_id="site", data_schema=schema, errors=errors)

        async def async_step_create_site(self, user_input: dict[str, Any] | None = None) -> Any:
            """Create a Replay site before binding it to this HAEO entry."""
            errors: dict[str, str] = {}
            token = self._token
            haeo_entry_id = self._haeo_entry_id
            if token is None or haeo_entry_id is None:
                return await self.async_step_user()

            if user_input is not None:
                name = str(user_input.get(CONF_REPLAY_SITE_NAME, "")).strip()
                if not name:
                    errors["base"] = "invalid_replay_site"
                else:
                    try:
                        site = await create_replay_site(DEFAULT_REPLAY_URL, token, name)
                        selected_site_id = str(site.get("id", "")).strip()
                        await bind_replay_site(DEFAULT_REPLAY_URL, token, selected_site_id, haeo_entry_id, confirm=True)
                    except Exception:
                        if not errors:
                            errors["base"] = "cannot_connect"
                    else:
                        title = self._haeo_title or haeo_entry_id
                        return self.async_create_entry(
                            title=f"HARO - {title}",
                            data={
                                CONF_HAEO_CONFIG_ENTRY_ID: haeo_entry_id,
                                CONF_TOKEN: token,
                                CONF_REPLAY_SITE_ID: selected_site_id,
                            },
                        )

            schema = _vol.Schema({_vol.Required(CONF_REPLAY_SITE_NAME): str})
            return self.async_show_form(step_id="create_site", data_schema=schema, errors=errors)

else:
    HaroConfigFlow: Any
    HaroConfigFlow = object
