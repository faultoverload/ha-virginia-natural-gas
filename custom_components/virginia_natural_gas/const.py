"""Constants for the Virginia Natural Gas integration."""

from datetime import timedelta
from zoneinfo import ZoneInfo

DOMAIN = "virginia_natural_gas"

# VNG only serves southeastern Virginia; its dates are local calendar days.
PORTAL_TZ = ZoneInfo("America/New_York")

# The portal only changes when a meter is read or a bill posts (about monthly), so
# there is no point asking often; the site also sits behind bot protection.
UPDATE_INTERVAL = timedelta(hours=12)

# Billing periods longer than this are treated as gaps (a missing bill) rather than
# one long period, so their charges are not smeared across months.
MAX_PERIOD_DAYS = 62
