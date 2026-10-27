"""Tests for the config flow."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.virginia_natural_gas.const import DOMAIN

from .portal import FAKE_PASSWORD, FAKE_USERNAME, FakePortal

USER_INPUT = {CONF_USERNAME: FAKE_USERNAME, CONF_PASSWORD: FAKE_PASSWORD}


def _no_setup():
    return patch("custom_components.virginia_natural_gas.async_setup_entry", return_value=True)


async def test_login(hass: HomeAssistant, portal: FakePortal) -> None:
    """A good login creates the entry, keyed on the lower-cased user ID."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    with _no_setup():
        result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == USER_INPUT
    assert result["result"].unique_id == FAKE_USERNAME.lower()


async def test_bad_password_then_good(hass: HomeAssistant, portal: FakePortal) -> None:
    """A rejected login shows an error and tries exactly once."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**USER_INPUT, CONF_PASSWORD: "wrong-password1"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}
    assert len(portal.logins) == 1

    with _no_setup():
        result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_cannot_connect(hass: HomeAssistant, portal: FakePortal) -> None:
    """An unexpected landing page is a connection error."""
    portal.login_location = "/Generic/ErrorPage"
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["errors"] == {"base": "cannot_connect"}


async def test_already_configured(
    hass: HomeAssistant, portal: FakePortal, config_entry: MockConfigEntry
) -> None:
    """The same user ID (in any case) can't be added twice, and isn't logged in again."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**USER_INPUT, CONF_USERNAME: FAKE_USERNAME.upper()}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert portal.logins == []


async def test_reauth(
    hass: HomeAssistant, portal: FakePortal, config_entry: MockConfigEntry
) -> None:
    """Reauth stores the new password."""
    hass.config_entries.async_update_entry(
        config_entry, data={**config_entry.data, CONF_PASSWORD: "old-password1"}
    )
    result = await config_entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    with _no_setup():
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_PASSWORD: FAKE_PASSWORD}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert config_entry.data[CONF_PASSWORD] == FAKE_PASSWORD
