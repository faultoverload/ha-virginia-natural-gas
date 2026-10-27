# Virginia Natural Gas for Home Assistant

[![hacs][hacs-badge]][hacs]
[![Validate][validate-badge]][validate]

A custom integration that pulls your natural gas usage and charges from the
[Virginia Natural Gas customer portal](https://customerportal.southerncompany.com/User/LoginGateway?LDC=2)
into Home Assistant, so you can track gas in the
[Energy dashboard](https://www.home-assistant.io/docs/energy/gas/).

This is an unofficial project; it is not affiliated with or endorsed by Virginia Natural Gas
or Southern Company Gas.

## What you get

- **Long-term statistics** for gas consumption (CCF) and gas charges (USD). VNG only reports
  usage per billing period (one meter read a month), so each period's usage and charges are
  spread evenly over its days. The Energy dashboard's day and week views show that average;
  month and year totals match your bills.
  - Usage covers the last 13 billing periods the portal shows; charges go back about two years.
  - Every refresh re-imports everything the portal still shows. Older days that have scrolled
    out of the portal's window keep what was imported before.
- **Sensors**
  - Meter reading (CCF, total increasing), last meter read date, next meter read date
  - Last period usage, length in days, and gas charges
  - Current bill, due date, last payment and its date

The newest data is from the last meter read, so the Energy dashboard stays empty from then
until the next read (about a month). The integration checks twice a day.

## Installation

### HACS

1. In HACS, open the menu → **Custom repositories**, add
   `https://github.com/faultoverload/ha-virginia-natural-gas` with category **Integration**.
2. Install **Virginia Natural Gas** and restart Home Assistant.

### Manual

Copy `custom_components/virginia_natural_gas` into your Home Assistant
`config/custom_components` folder and restart.

## Setup

1. **Settings → Devices & services → Add integration → Virginia Natural Gas.**
2. Enter the User ID and password you use for My Account on virginianaturalgas.com.

The portal locks your account for a while after 5 failed sign-ins, so the integration never
retries a rejected password on its own. If VNG rejects it (for example after a password
change), Home Assistant shows a **Reauthenticate** notice; open it and enter the new password.

## Energy dashboard

**Settings → Dashboards → Energy → Gas consumption → Add gas source**, then choose the
statistic **Virginia Natural Gas _meter_ consumption**. For cost, choose **Use an entity
tracking the total costs** and pick **Virginia Natural Gas _meter_ cost**.

## Notes

- **Cost is the bill's gas charges**, which include the fixed monthly charge, so a month with
  no gas use still costs something. It leaves out other items on the bill, like late fees or
  budget-plan adjustments.
- VNG's portal reports usage in CCF (hundred cubic feet). For Virginia Natural Gas, the portal's
  CCF and therm figures are the same numbers.
- Accounts with more than one meter use the first meter, and logins that land on an account
  picker (more than one account) aren't supported yet. If that happens, setup fails with a
  "Failed to connect" error and the log names the page the portal went to.
- Your password is stored in Home Assistant's config entry, like other cloud integrations.
  Nothing is sent anywhere except the VNG portal.

## Development

```bash
uv venv --python 3.14
uv pip install -r requirements_test.txt
.venv/bin/python -m pytest
```

Tests use a fake portal with made-up data (`tests/portal.py`). To try the client against
the real portal, copy `.env.example` to `.env` and fill it in. `.env` and `captures/` are
git-ignored; never commit real portal pages, since they include names, addresses and
account numbers.

[hacs]: https://hacs.xyz
[hacs-badge]: https://img.shields.io/badge/HACS-Custom-orange.svg
[validate]: https://github.com/faultoverload/ha-virginia-natural-gas/actions/workflows/validate.yml
[validate-badge]: https://github.com/faultoverload/ha-virginia-natural-gas/actions/workflows/validate.yml/badge.svg
