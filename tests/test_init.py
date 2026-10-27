"""Tests for setup, statistics import and sensors."""

from __future__ import annotations

from datetime import date, timedelta

from freezegun.api import FrozenDateTimeFactory
from homeassistant.components.recorder import Recorder
from homeassistant.components.recorder.statistics import (
    get_metadata,
    statistics_during_period,
)
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util.unit_system import US_CUSTOMARY_SYSTEM
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

from custom_components.virginia_natural_gas.const import DOMAIN, UPDATE_INTERVAL
from custom_components.virginia_natural_gas.coordinator import day_start, statistic_ids

from .portal import (
    EXTRA_BILL_DATES,
    FAKE_METER,
    FAKE_USERNAME,
    FIRST_READING,
    READS,
    FakePortal,
    charges,
)

CONSUMPTION_ID, COST_ID = statistic_ids(FAKE_METER)
USAGE_START = EXTRA_BILL_DATES[-1]  # the first read's period starts on the previous bill
COST_START = EXTRA_BILL_DATES[0]  # the oldest bill has no start, so cost starts at its date
LAST_DAY = READS[-1][0] - timedelta(days=1)


@pytest.fixture(autouse=True)
def frozen_today(freezer: FrozenDateTimeFactory) -> FrozenDateTimeFactory:
    """Pin 'now' to a week after the last read."""
    freezer.move_to("2026-03-12 16:00:00+00:00")
    return freezer


@pytest.fixture(autouse=True)
def us_units(hass: HomeAssistant) -> None:
    """Show sensors in US units, as a Virginia install would."""
    hass.config.units = US_CUSTOMARY_SYSTEM


async def _stats(hass: HomeAssistant) -> dict:
    await async_wait_recording_done(hass)
    return await hass.async_add_executor_job(
        statistics_during_period,
        hass,
        day_start(date(2020, 1, 1)),
        None,
        {CONSUMPTION_ID, COST_ID},
        "hour",
        None,
        {"state", "sum"},
    )


def _entity(hass: HomeAssistant, key: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"{FAKE_USERNAME.lower()}_{key}"
    )
    assert entity_id, key
    return entity_id


async def test_setup_imports_statistics_and_sensors(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    portal: FakePortal,
    config_entry: MockConfigEntry,
) -> None:
    """The first refresh spreads every period over its days and fills the sensors."""
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.LOADED

    stats = await _stats(hass)
    usage = stats[CONSUMPTION_ID]
    assert usage[0]["start"] == day_start(USAGE_START).timestamp()
    assert usage[-1]["start"] == day_start(LAST_DAY).timestamp()
    assert len(usage) == (LAST_DAY - USAGE_START).days + 1
    assert usage[-1]["sum"] == pytest.approx(sum(ccf for _, ccf in READS), abs=1e-3)

    cost = stats[COST_ID]
    assert cost[0]["start"] == day_start(COST_START).timestamp()
    assert cost[-1]["start"] == day_start(LAST_DAY).timestamp()
    expected_cost = charges(10.0) + sum(charges(ccf) for _, ccf in READS)
    assert cost[-1]["sum"] == pytest.approx(expected_cost, abs=1e-3)

    metadata = await hass.async_add_executor_job(get_metadata, hass)
    assert metadata[CONSUMPTION_ID][1]["unit_of_measurement"] == "CCF"

    states = {
        key: hass.states.get(_entity(hass, key)).state
        for key in (
            "meter_reading",
            "last_read_date",
            "next_read_date",
            "last_period_usage",
            "last_period_days",
            "last_period_cost",
            "amount_due",
            "due_date",
            "last_payment",
            "last_payment_date",
        )
    }
    assert states == {
        "meter_reading": str(FIRST_READING + sum(ccf for _, ccf in READS)),
        "last_read_date": "2026-03-05",
        "next_read_date": "2026-04-03",
        "last_period_usage": "157.0",
        "last_period_days": "30",
        "last_period_cost": str(charges(157.0)),
        "amount_due": "1234.56",
        "due_date": "2026-04-02",
        "last_payment": "45.67",
        "last_payment_date": "2026-03-01",
    }


async def test_refresh_keeps_days_that_left_the_window(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    portal: FakePortal,
    config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """When the oldest period drops off the portal, the sum continues from what was stored."""
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    first = await _stats(hass)

    portal.dropped_reads = 1
    freezer.tick(UPDATE_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    second = await _stats(hass)
    assert second[CONSUMPTION_ID][0]["start"] == day_start(USAGE_START).timestamp()
    assert second[CONSUMPTION_ID][-1]["sum"] == pytest.approx(
        first[CONSUMPTION_ID][-1]["sum"], abs=1e-3
    )
    assert len(portal.logins) == 2


async def test_bad_password_starts_reauth_and_stops(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    portal: FakePortal,
    config_entry: MockConfigEntry,
) -> None:
    """A rejected login asks the user to reauthenticate instead of retrying."""
    portal.bad_password = True
    assert not await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert [f["context"]["source"] for f in flows] == [SOURCE_REAUTH]
    assert len(portal.logins) == 1


async def test_portal_down_retries(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    portal: FakePortal,
    config_entry: MockConfigEntry,
) -> None:
    """An unexpected landing page means try again later."""
    portal.login_location = "/Generic/ErrorPage"
    assert not await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_statistics_listed_for_energy_dashboard(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    portal: FakePortal,
    config_entry: MockConfigEntry,
    hass_ws_client,
) -> None:
    """The gas source picker lists sum statistics whose unit_class is volume."""
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    await async_wait_recording_done(hass)

    client = await hass_ws_client(hass)
    await client.send_json(
        {"id": 1, "type": "recorder/list_statistic_ids", "statistic_type": "sum"}
    )
    resp = await client.receive_json()
    listed = {r["statistic_id"]: r for r in resp["result"]}
    assert listed[CONSUMPTION_ID]["unit_class"] == "volume"
    assert listed[CONSUMPTION_ID]["statistics_unit_of_measurement"] == "CCF"
    assert COST_ID in listed
