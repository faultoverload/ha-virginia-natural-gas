"""A fake Virginia Natural Gas portal for tests. All account data here is made up."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
import json
from typing import Any

from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
    AiohttpClientMockResponse,
)
from yarl import URL

from custom_components.virginia_natural_gas.api import (
    BASE_URL,
    EXPIRED_PATH,
    GATEWAY_PATH,
    LOGIN_PAGE_PATH,
    LOGIN_PATH,
    SUMMARY_PATH,
    USAGE_PATH,
)

FAKE_USERNAME = "TestUser1"
FAKE_PASSWORD = "not-a-real-password1"
FAKE_METER = "1234567"
FAKE_TOKEN = "fake-antiforgery-token"
# Made-up tariff: fixed monthly charge plus a per-CCF rate.
BILL_FIXED = 15.0
BILL_PER_CCF = 1.5
BAD_LOGIN_MESSAGE = (
    "The User ID/Password you entered do not match the current User ID/Password "
    "we have on file for you."
)

LOGIN_PAGE = f"""<html><form action="/User/Login" method="post">
<input name="__RequestVerificationToken" type="hidden" value="{FAKE_TOKEN}" />
<input id="username" name="UserName" type="text" />
<input id="inputPassword" name="Password" type="password" />
</form><div id="errorMessage" class="error"></div></html>"""

LOGIN_FAILED_PAGE = LOGIN_PAGE.replace(
    '<div id="errorMessage" class="error"></div>',
    f'<div id="errorMessage" class="error">{BAD_LOGIN_MESSAGE}</div>',
)

SUMMARY_PAGE = """<html><div class="current-bill-inline"><div class="amount-col1">
<p class="amountdue">$1,234.56</p>
<p class="duedate bold-text duedate-padding"> Due Date: 4/2/2026 </p></div></div>
<div class="lastPayAmount">Last payment of $45.67 received on 03/01/2026 </div></html>"""

# Read dates of the made-up account, oldest first, and CCF used in the period each closes.
READS: list[tuple[date, float]] = [
    (date(2025, 9, 5), 3.0),
    (date(2025, 10, 6), 2.0),
    (date(2025, 11, 4), 15.0),
    (date(2025, 12, 5), 66.0),
    (date(2026, 1, 5), 136.0),
    (date(2026, 2, 3), 142.0),
    (date(2026, 3, 5), 157.0),
]
# Bills reach further back than reads, as on the real portal.
EXTRA_BILL_DATES = [date(2025, 7, 7), date(2025, 8, 6)]
NEXT_READ = date(2026, 4, 3)
FIRST_READING = 5000.0


def charges(ccf: float) -> float:
    """Gas charges for a period under the made-up tariff."""
    return round(BILL_FIXED + BILL_PER_CCF * ccf, 2)


def usage_rows(dropped: int = 0) -> list[dict[str, Any]]:
    """UsageHistoryCollection, newest first like the portal, minus the oldest ``dropped``."""
    rows = []
    reading = FIRST_READING
    previous = date(2025, 8, 6)
    for read_date, ccf in READS:
        reading += ccf
        rows.append(
            {
                "Date": read_date.strftime("%m/%d/%Y"),
                "MeterReading": f"{reading:.6f}",
                "ReadingDetails": "Actual",
                "CCfs": ccf,
                "Therms": ccf,
                "DaysUsed": (read_date - previous).days,
            }
        )
        previous = read_date
    return rows[dropped:][::-1]


def bill_rows() -> list[dict[str, Any]]:
    """MonthlyBillUsage, newest first like the portal."""
    bills = [(d, charges(10.0)) for d in EXTRA_BILL_DATES]
    bills += [(d, charges(ccf)) for d, ccf in READS]
    return [
        {
            "BillDate": "/Date(0)/",
            "BillDateString": f"{d.month}/{d.day}/{d.year} 12:00:00 AM",
            "CurrentGasCharges": amount,
            "TotalBillAmount": amount,
            "BillingDays": 0,
        }
        for d, amount in bills[::-1]
    ]


def usage_page(dropped_reads: int = 0) -> str:
    """The Usage History page with its embedded view model."""
    model = {
        "UsageHistoryCollection": usage_rows(dropped_reads),
        "MeterInformationCollection": [
            {
                "MeterNumber": FAKE_METER,
                "MeterStatus": "On",
                "NextMeterRead": NEXT_READ.strftime("%m/%d/%Y"),
            }
        ],
        "isUsageHistoryAvailable": "Y",
        "AMIUsageMData": {
            "LDCId": 2,
            "MonthlyBillUsage": bill_rows(),
            "NextMeterReadingDate": NEXT_READ.strftime("%m/%d/%Y"),
            "ThisMonthBill": "$0.00",
        },
    }
    # The real page writes the JSON into a single-quoted JS string.
    raw = json.dumps(model).replace("'", "\\'")
    return (
        "<html><script>\n    var monthlyCosts = [];\n"
        f"    var vmodel = '{raw}';\n"
        "    var perc;\n</script></html>"
    )


@dataclass
class FakePortal:
    """Registers portal endpoints on an AiohttpClientMocker."""

    bad_password: bool = False
    # Where a successful login redirects; the real portal goes to the summary.
    login_location: str = SUMMARY_PATH
    # Oldest reads that have scrolled out of the portal's window.
    dropped_reads: int = 0
    # Answer the login POST with some other page (a bot check, say).
    login_page_override: str | None = None
    logins: list[dict[str, Any]] = field(default_factory=list)
    logged_in: bool = False
    summary_loaded: bool = False

    def register(self, mock: AiohttpClientMocker) -> None:
        """Register all endpoints."""
        mock.clear_requests()
        mock.get(BASE_URL + GATEWAY_PATH, text="<html></html>")
        mock.get(BASE_URL + LOGIN_PAGE_PATH, text=LOGIN_PAGE)
        mock.post(BASE_URL + LOGIN_PATH, side_effect=self._login)
        mock.get(BASE_URL + SUMMARY_PATH, side_effect=self._summary)
        mock.get(BASE_URL + USAGE_PATH, side_effect=self._usage)

    @staticmethod
    def _redirect(method: str, url: URL, to: str) -> AiohttpClientMockResponse:
        return AiohttpClientMockResponse(method, url, status=302, headers={"Location": to})

    async def _login(self, method: str, url: URL, data: Any) -> AiohttpClientMockResponse:
        self.logins.append(data)
        if self.login_page_override is not None:
            return AiohttpClientMockResponse(method, url, text=self.login_page_override)
        if (
            self.bad_password
            or data["Password"] != FAKE_PASSWORD
            or data["__RequestVerificationToken"] != FAKE_TOKEN
        ):
            return AiohttpClientMockResponse(method, url, text=LOGIN_FAILED_PAGE)
        self.logged_in = True
        self.summary_loaded = False
        return self._redirect(method, url, self.login_location)

    async def _summary(self, method: str, url: URL, data: Any) -> AiohttpClientMockResponse:
        if not self.logged_in:
            return self._redirect(method, url, EXPIRED_PATH)
        self.summary_loaded = True
        return AiohttpClientMockResponse(method, url, text=SUMMARY_PAGE)

    async def _usage(self, method: str, url: URL, data: Any) -> AiohttpClientMockResponse:
        if not self.logged_in:
            return self._redirect(method, url, EXPIRED_PATH)
        if not self.summary_loaded:
            return self._redirect(method, url, "/Generic/ErrorPage")
        return AiohttpClientMockResponse(method, url, text=usage_page(self.dropped_reads))
