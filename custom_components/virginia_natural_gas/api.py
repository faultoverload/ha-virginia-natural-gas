"""Client for the Virginia Natural Gas customer portal (Southern Company Gas).

The portal is an ASP.NET MVC site shared by the Southern Company Gas utilities; the
``LDC`` query parameter picks the utility (2 is Virginia Natural Gas). Logging in is a
plain form POST with the page's anti-forgery token. There is no JSON API for usage:
the Usage History page embeds its whole view model as a JSON string in a ``var vmodel``
script variable, and the Account Summary page is parsed for the bill and payment.

A logged-out request is redirected to ``/Generic/SessionExpiry``.

Never log raw responses: they include the account holder's name, address and
account number.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import html
import json
import logging
import re
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

BASE_URL = "https://customerportal.southerncompany.com"
LDC = "2"  # Southern Company Gas's id for Virginia Natural Gas

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
)

GATEWAY_PATH = f"/User/LoginGateway?LDC={LDC}"
LOGIN_PAGE_PATH = f"/User/Login?LDC={LDC}"
LOGIN_PATH = "/User/Login"
SUMMARY_PATH = "/Account/AccountSummary"
USAGE_PATH = "/MeterDataManagement/UsageHistory"
EXPIRED_PATH = "/Generic/SessionExpiry"

_TOKEN_RE = re.compile(r'name="__RequestVerificationToken"[^>]*value="([^"]+)"')
_LOGIN_ERROR_RE = re.compile(r'id="errorMessage"[^>]*>(.*?)<', re.S)
_VMODEL_RE = re.compile(r"var vmodel = '(.*?)';\s*$", re.S | re.M)
_AMOUNT_DUE_RE = re.compile(r'class="amountdue"[^>]*>\s*\$?([\d,]+\.\d{2})')
_DUE_DATE_RE = re.compile(r"Due Date:\s*(\d{1,2}/\d{1,2}/\d{4})")
_LAST_PAYMENT_RE = re.compile(
    r"Last payment of \$([\d,]+\.\d{2}) received on (\d{1,2}/\d{1,2}/\d{4})"
)
_TIMEOUT = aiohttp.ClientTimeout(total=60)


class VNGError(Exception):
    """Base error for the portal client."""


class CannotConnect(VNGError):
    """The portal could not be reached or returned something unexpected."""


class InvalidAuth(VNGError):
    """The user ID or password was rejected (or the account is locked)."""


class SessionExpired(VNGError):
    """The portal session is no longer logged in."""


@dataclass(frozen=True, slots=True)
class MeterRead:
    """A meter read that closes a billing period."""

    read_date: date
    reading: float
    usage: float  # CCF used since the previous read
    days: int  # days since the previous read
    actual: bool  # False for an estimated read


@dataclass(frozen=True, slots=True)
class Bill:
    """A bill, dated on the meter read that closed its period."""

    bill_date: date
    gas_charges: float  # this period's gas charges
    total: float  # the bill total, which can include other charges or credits


@dataclass(frozen=True, slots=True)
class UsageHistory:
    """What the Usage History page shows."""

    meter_number: str
    next_read: date | None
    reads: list[MeterRead]
    bills: list[Bill]


@dataclass(frozen=True, slots=True)
class AccountSummary:
    """The current bill and last payment from the Account Summary page."""

    amount_due: float | None
    due_date: date | None
    last_payment: float | None
    last_payment_date: date | None


def _num(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", "").replace("$", ""))
    except ValueError:
        return None


def _date(value: Any) -> date | None:
    """Parse ``10/06/2026`` or ``10/6/2026 12:00:00 AM``."""
    if not value:
        return None
    try:
        return datetime.strptime(str(value).split()[0], "%m/%d/%Y").date()
    except ValueError:
        return None


def parse_token(page: str) -> str:
    """Return the anti-forgery token from the login page."""
    if not (match := _TOKEN_RE.search(page)):
        raise CannotConnect("No login form on the portal's login page")
    return match.group(1)


def parse_login_error(page: str) -> str | None:
    """Return the login page's error message, if it shows one."""
    if not (match := _LOGIN_ERROR_RE.search(page)):
        return None
    return html.unescape(match.group(1)).strip() or None


def parse_usage(page: str) -> UsageHistory:
    """Parse the view model embedded in the Usage History page."""
    if not (match := _VMODEL_RE.search(page)):
        raise CannotConnect("No usage data on the Usage History page")
    # It is a single-quoted JS string literal holding JSON.
    raw = match.group(1).replace("\\'", "'")
    try:
        model = json.loads(raw)
    except ValueError as err:
        raise CannotConnect("Could not read the Usage History data") from err

    reads: list[MeterRead] = []
    for row in model.get("UsageHistoryCollection") or []:
        read_date = _date(row.get("Date"))
        usage = _num(row.get("CCfs"))
        if read_date is None or usage is None:
            continue
        reads.append(
            MeterRead(
                read_date=read_date,
                reading=_num(row.get("MeterReading")) or 0.0,
                usage=usage,
                days=int(_num(row.get("DaysUsed")) or 0),
                actual=str(row.get("ReadingDetails", "")).lower() == "actual",
            )
        )

    ami = model.get("AMIUsageMData") or {}
    bills: list[Bill] = []
    for row in ami.get("MonthlyBillUsage") or []:
        bill_date = _date(row.get("BillDateString"))
        charges = _num(row.get("CurrentGasCharges"))
        if bill_date is None or charges is None:
            continue
        bills.append(
            Bill(
                bill_date=bill_date,
                gas_charges=charges,
                total=_num(row.get("TotalBillAmount")) or 0.0,
            )
        )

    meters = model.get("MeterInformationCollection") or []
    meter = meters[0] if meters else {}
    return UsageHistory(
        meter_number=str(meter.get("MeterNumber") or ""),
        next_read=_date(meter.get("NextMeterRead") or ami.get("NextMeterReadingDate")),
        reads=sorted(reads, key=lambda r: r.read_date),
        bills=sorted(bills, key=lambda b: b.bill_date),
    )


def parse_summary(page: str) -> AccountSummary:
    """Parse the current bill and last payment from the Account Summary page."""
    amount = _AMOUNT_DUE_RE.search(page)
    due = _DUE_DATE_RE.search(page)
    payment = _LAST_PAYMENT_RE.search(page)
    return AccountSummary(
        amount_due=_num(amount.group(1)) if amount else None,
        due_date=_date(due.group(1)) if due else None,
        last_payment=_num(payment.group(1)) if payment else None,
        last_payment_date=_date(payment.group(2)) if payment else None,
    )


class VNGClient:
    """Logs in to the portal and reads usage and billing pages."""

    def __init__(self, session: aiohttp.ClientSession, username: str, password: str) -> None:
        """Initialize the client. ``session`` should have its own cookie jar."""
        self._session = session
        self._username = username
        self._password = password

    async def _request(self, method: str, path: str, **kwargs: Any) -> tuple[int, str, str]:
        """Return (status, redirect location, body); redirects are not followed."""
        headers = {"User-Agent": USER_AGENT, **kwargs.pop("headers", {})}
        try:
            async with self._session.request(
                method,
                BASE_URL + path,
                headers=headers,
                allow_redirects=False,
                timeout=_TIMEOUT,
                **kwargs,
            ) as resp:
                body = await resp.text()
                location = resp.headers.get("Location", "")
        except (aiohttp.ClientError, TimeoutError) as err:
            raise CannotConnect(f"Error talking to the portal: {err}") from err
        if resp.status >= 400:
            raise CannotConnect(f"Portal returned HTTP {resp.status} for {path}")
        return resp.status, location, body

    async def _get_page(self, path: str) -> str:
        status, location, body = await self._request("GET", path)
        if status in (301, 302, 303, 307, 308):
            if EXPIRED_PATH.lower() in location.lower() or "/user/login" in location.lower():
                raise SessionExpired("Not logged in")
            raise CannotConnect(f"Portal redirected {path} somewhere unexpected")
        return body

    async def login(self) -> AccountSummary:
        """Log in and return the Account Summary it lands on.

        Raises InvalidAuth if the portal rejects the user ID or password.
        """
        # Start clean so every login takes the same path; the session's jar is ours.
        self._session.cookie_jar.clear()
        # The gateway sets the cookie that picks Virginia Natural Gas.
        await self._request("GET", GATEWAY_PATH)
        _, _, page = await self._request("GET", LOGIN_PAGE_PATH)
        token = parse_token(page)
        status, location, body = await self._request(
            "POST",
            LOGIN_PATH,
            data={
                "__RequestVerificationToken": token,
                "UserName": self._username,
                "Password": self._password,
                "RememberMe": "false",
                "loginbtn": "Login",
            },
            headers={"Origin": BASE_URL, "Referer": BASE_URL + LOGIN_PAGE_PATH},
        )
        if status == 200:
            # The login page came back with "User ID/Password ... do not match" or a
            # lockout notice. Every failure counts toward the portal's five-attempt
            # lockout, so callers must not retry on their own. Any other page (a bot
            # check or maintenance notice) is not the password's fault.
            if message := parse_login_error(body):
                raise InvalidAuth(message)
            raise CannotConnect("Login returned a page without the account or an error")
        if SUMMARY_PATH.lower() not in location.lower():
            # Something else wants attention first (an account picker, a notice or a
            # password reset). Only the path is logged: it carries no account data.
            raise CannotConnect(f"Login went to {location.split('?')[0]} instead of the account")
        # Loading the summary picks the account for the session; until then other
        # pages redirect to an error page.
        return parse_summary(await self._get_page(SUMMARY_PATH))

    async def get_usage_history(self) -> UsageHistory:
        """Fetch and parse the Usage History page. Call after login()."""
        return parse_usage(await self._get_page(USAGE_PATH))
