"""Tests for the portal client and page parsers."""

from __future__ import annotations

from datetime import date

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_create_clientsession
import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.virginia_natural_gas.api import (
    BASE_URL,
    GATEWAY_PATH,
    CannotConnect,
    InvalidAuth,
    SessionExpired,
    VNGClient,
    parse_summary,
    parse_usage,
)

from .portal import (
    FAKE_METER,
    FAKE_PASSWORD,
    FAKE_TOKEN,
    FAKE_USERNAME,
    NEXT_READ,
    READS,
    SUMMARY_PAGE,
    FakePortal,
    charges,
    usage_page,
)


def _client(hass: HomeAssistant, password: str = FAKE_PASSWORD) -> VNGClient:
    return VNGClient(async_create_clientsession(hass), FAKE_USERNAME, password)


def test_parse_usage() -> None:
    """The embedded view model becomes sorted reads and bills."""
    history = parse_usage(usage_page())
    assert history.meter_number == FAKE_METER
    assert history.next_read == NEXT_READ
    assert [r.read_date for r in history.reads] == [d for d, _ in READS]
    last = history.reads[-1]
    assert last.usage == READS[-1][1]
    assert last.days == 30
    assert last.actual
    assert history.bills[0].bill_date == date(2025, 7, 7)
    assert history.bills[-1].gas_charges == charges(READS[-1][1])


def test_parse_usage_unescapes_quotes() -> None:
    """A quote inside the JS string literal survives."""
    page = usage_page().replace('"Status": "On"', '"Status": "On\\\'s"')
    assert parse_usage(page).meter_number == FAKE_METER


def test_parse_usage_without_model() -> None:
    """A page without the view model is an error, not empty data."""
    with pytest.raises(CannotConnect):
        parse_usage("<html>Usage history is not available</html>")


def test_parse_summary() -> None:
    """Amount due, due date and last payment come from the summary page."""
    summary = parse_summary(SUMMARY_PAGE)
    assert summary.amount_due == 1234.56
    assert summary.due_date == date(2026, 4, 2)
    assert summary.last_payment == 45.67
    assert summary.last_payment_date == date(2026, 3, 1)


def test_parse_summary_missing_fields() -> None:
    """Missing pieces come back as None."""
    summary = parse_summary("<html></html>")
    assert summary.amount_due is None
    assert summary.last_payment_date is None


async def test_login_and_fetch(hass: HomeAssistant, portal: FakePortal) -> None:
    """Login posts the form with the page token and lands on the summary."""
    client = _client(hass)
    summary = await client.login()
    assert summary.amount_due == 1234.56
    assert portal.logins == [
        {
            "__RequestVerificationToken": FAKE_TOKEN,
            "UserName": FAKE_USERNAME,
            "Password": FAKE_PASSWORD,
            "RememberMe": "false",
            "loginbtn": "Login",
        }
    ]
    history = await client.get_usage_history()
    assert len(history.reads) == len(READS)


async def test_bad_password(hass: HomeAssistant, portal: FakePortal) -> None:
    """The portal's own message is passed on."""
    with pytest.raises(InvalidAuth, match="do not match"):
        await _client(hass, "wrong-password1").login()


async def test_not_logged_in(hass: HomeAssistant, portal: FakePortal) -> None:
    """A redirect to the session-expired page is SessionExpired."""
    with pytest.raises(SessionExpired):
        await _client(hass).get_usage_history()


async def test_login_lands_somewhere_else(hass: HomeAssistant, portal: FakePortal) -> None:
    """An unexpected landing page (an account picker, say) is reported, not ignored."""
    portal.login_location = "/Account/AccountList"
    with pytest.raises(CannotConnect, match="/Account/AccountList"):
        await _client(hass).login()


async def test_server_error(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    """HTTP errors are CannotConnect."""
    aioclient_mock.get(BASE_URL + GATEWAY_PATH, status=503)
    with pytest.raises(CannotConnect):
        await _client(hass).login()


async def test_login_returns_other_page(hass: HomeAssistant, portal: FakePortal) -> None:
    """A 200 without a login error is not a bad password, so it must not lock out the user."""
    portal.login_page_override = "<html>Please wait while we check your browser</html>"
    with pytest.raises(CannotConnect):
        await _client(hass).login()


async def test_login_twice(hass: HomeAssistant, portal: FakePortal) -> None:
    """A second login on the same client works (the coordinator reuses its client)."""
    client = _client(hass)
    await client.login()
    await client.login()
    assert len((await client.get_usage_history()).reads) == len(READS)
