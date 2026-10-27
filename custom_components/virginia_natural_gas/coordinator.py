"""Coordinator: fetches billing periods and writes daily usage and cost to statistics."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
import logging

import aiohttp
from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    statistics_during_period,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import slugify
from homeassistant.util.unit_conversion import VolumeConverter

from .api import (
    AccountSummary,
    InvalidAuth,
    SessionExpired,
    VNGClient,
    VNGError,
)
from .const import DOMAIN, PORTAL_TZ, UPDATE_INTERVAL
from .periods import daily_cost, daily_usage

_LOGGER = logging.getLogger(__name__)

type VNGConfigEntry = ConfigEntry[VNGCoordinator]

# How far before the first re-imported day to look for the running sum to continue.
_PRIOR_LOOKBACK = timedelta(days=5 * 365)


@dataclass(frozen=True, slots=True)
class VNGData:
    """What the sensors show."""

    meter_number: str
    meter_reading: float | None
    last_read_date: date | None
    last_period_usage: float | None
    last_period_days: int | None
    last_period_cost: float | None
    next_read_date: date | None
    summary: AccountSummary


def day_start(day: date) -> datetime:
    """Local midnight in Virginia for ``day``, as an aware datetime."""
    return datetime.combine(day, time.min, tzinfo=PORTAL_TZ)


def statistic_ids(meter_number: str) -> tuple[str, str]:
    """Return (consumption, cost) external statistic ids for a meter."""
    base = f"{DOMAIN}:{slugify(meter_number)}"
    return f"{base}_gas_consumption", f"{base}_gas_cost"


class VNGCoordinator(DataUpdateCoordinator[VNGData]):
    """Fetches from the portal twice a day."""

    config_entry: VNGConfigEntry

    def __init__(self, hass: HomeAssistant, entry: VNGConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )
        # Own cookie jar: the portal session must not mix with other integrations.
        session = async_create_clientsession(hass, cookie_jar=aiohttp.CookieJar())
        self.client = VNGClient(session, entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD])

    async def _async_update_data(self) -> VNGData:
        # Log in every time: refreshes are hours apart, so the old session is gone.
        try:
            summary = await self.client.login()
            history = await self.client.get_usage_history()
        except InvalidAuth as err:
            # Stop polling: every failed login counts toward the portal's lockout.
            raise ConfigEntryAuthFailed(str(err)) from err
        except SessionExpired as err:
            raise UpdateFailed("Portal session ended right after login") from err
        except VNGError as err:
            raise UpdateFailed(str(err)) from err

        if not history.meter_number:
            raise UpdateFailed("No gas meter found on the account")
        consumption_id, cost_id = statistic_ids(history.meter_number)
        await self._import_statistics(
            history.meter_number,
            consumption_id,
            daily_usage(history.reads),
            cost_id,
            daily_cost(history.bills),
        )

        last_read = history.reads[-1] if history.reads else None
        period_cost = None
        if last_read:
            period_cost = (
                sum(b.gas_charges for b in history.bills if b.bill_date == last_read.read_date)
                or None
            )
        return VNGData(
            meter_number=history.meter_number,
            meter_reading=last_read.reading if last_read else None,
            last_read_date=last_read.read_date if last_read else None,
            last_period_usage=last_read.usage if last_read else None,
            last_period_days=last_read.days if last_read else None,
            last_period_cost=round(period_cost, 2) if period_cost is not None else None,
            next_read_date=history.next_read,
            summary=summary,
        )

    async def _import_statistics(
        self,
        meter: str,
        consumption_id: str,
        usage: dict[date, float],
        cost_id: str,
        cost: dict[date, float],
    ) -> None:
        """Rewrite every day the portal still shows, continuing the running sum before it.

        The portal shows a rolling window (about 13 periods of usage and 24 bills);
        days that have dropped out of it keep what was imported earlier.
        """
        for statistic_id, values, name, unit_class, unit in (
            (
                consumption_id,
                usage,
                f"Virginia Natural Gas {meter} consumption",
                VolumeConverter.UNIT_CLASS,
                UnitOfVolume.CENTUM_CUBIC_FEET,
            ),
            (cost_id, cost, f"Virginia Natural Gas {meter} cost", None, None),
        ):
            if not values:
                continue
            first_start = day_start(min(values))
            prior = await get_instance(self.hass).async_add_executor_job(
                statistics_during_period,
                self.hass,
                first_start - _PRIOR_LOOKBACK,
                first_start,
                {statistic_id},
                "hour",
                None,
                {"sum"},
            )
            rows = prior.get(statistic_id) or []
            running = float(rows[-1].get("sum") or 0.0) if rows else 0.0
            stats: list[StatisticData] = []
            for day in sorted(values):
                running += values[day]
                stats.append(
                    StatisticData(start=day_start(day), state=values[day], sum=round(running, 4))
                )
            metadata = StatisticMetaData(
                mean_type=StatisticMeanType.NONE,
                has_sum=True,
                name=name,
                source=DOMAIN,
                statistic_id=statistic_id,
                unit_class=unit_class,
                unit_of_measurement=unit,
            )
            _LOGGER.debug("Importing %s days into %s", len(stats), statistic_id)
            async_add_external_statistics(self.hass, metadata, stats)
