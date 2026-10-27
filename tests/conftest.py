"""Fixtures for Virginia Natural Gas tests."""

from __future__ import annotations

from homeassistant.components.recorder import Recorder
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.virginia_natural_gas.const import DOMAIN

from .portal import FAKE_PASSWORD, FAKE_USERNAME, FakePortal


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    recorder_mock: Recorder, enable_custom_integrations: None
) -> None:
    """Enable custom integrations; the integration depends on the recorder."""


@pytest.fixture
def portal(aioclient_mock: AiohttpClientMocker) -> FakePortal:
    """A fake portal registered on the HTTP mocker."""
    fake = FakePortal()
    fake.register(aioclient_mock)
    return fake


@pytest.fixture
def config_entry(hass: HomeAssistant) -> MockConfigEntry:
    """A config entry for the fake account."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=FAKE_USERNAME,
        unique_id=FAKE_USERNAME.lower(),
        data={CONF_USERNAME: FAKE_USERNAME, CONF_PASSWORD: FAKE_PASSWORD},
    )
    entry.add_to_hass(hass)
    return entry
