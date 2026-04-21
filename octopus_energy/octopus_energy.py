#!/usr/bin/env python3
"""Octopus Energy Deutschland - Home Assistant Add-on."""

import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone

import paho.mqtt.client as mqtt
import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

GRAPHQL_URL = "https://api.oeg-kraken.energy/v1/graphql/"
TIMEZONE = "Europe/Berlin"


# ---------------------------------------------------------------------------
# GraphQL queries
# ---------------------------------------------------------------------------

QUERY_OBTAIN_TOKEN = """
mutation ObtainToken($email: String!, $password: String!) {
  obtainKrakenToken(input: { email: $email, password: $password }) {
    token
  }
}
"""

QUERY_ACCOUNT = """
query Account($accountNumber: String!) {
  account(accountNumber: $accountNumber) {
    number
    balance
    overdueBalance
    ledgers {
      balance
      ledgerType
    }
    properties {
      id
    }
  }
}
"""

QUERY_PAYMENTS = """
query Payments($accountNumber: String!) {
  account(accountNumber: $accountNumber) {
    payments(first: 20) {
      edges {
        node {
          amount
          paymentDate
          transactionType
        }
      }
    }
  }
}
"""

QUERY_BILLS = """
query Bills($accountNumber: String!) {
  account(accountNumber: $accountNumber) {
    bills(first: 30) {
      edges {
        node {
          id
          billType
          fromDate
          toDate
          issuedDate
          temporaryUrl
          ... on InvoiceType {
            totalCharges {
              netTotal
              grossTotal
              taxTotal
            }
            transactions(first: 50) {
              edges {
                node {
                  postedDate
                  amounts {
                    net
                    tax
                    gross
                  }
                  title
                }
              }
            }
          }
          ... on StatementType {
            totalCharges {
              netTotal
              grossTotal
              taxTotal
            }
            transactions(first: 50) {
              edges {
                node {
                  postedDate
                  amounts {
                    net
                    tax
                    gross
                  }
                  title
                }
              }
            }
          }
        }
      }
    }
  }
}
"""

QUERY_MEASUREMENTS = """
query getAccountMeasurements(
    $propertyId: ID!
    $first: Int!
    $utilityFilters: [UtilityFiltersInput!]
    $startAt: DateTime
    $endAt: DateTime
    $timezone: String
) {
  property(id: $propertyId) {
    measurements(
      first: $first
      utilityFilters: $utilityFilters
      startAt: $startAt
      endAt: $endAt
      timezone: $timezone
    ) {
      edges {
        node {
          value
          unit
          ... on IntervalMeasurementType {
            startAt
            endAt
            durationInSeconds
          }
          metaData {
            statistics {
              costExclTax {
                pricePerUnit {
                  amount
                }
                costCurrency
                estimatedAmount
              }
              costInclTax {
                costCurrency
                estimatedAmount
              }
              value
              description
              label
              type
            }
          }
        }
      }
    }
  }
}
"""


# ---------------------------------------------------------------------------
# API client
# ---------------------------------------------------------------------------

class OctopusEnergyClient:
    def __init__(self, email: str, password: str, account_number: str):
        self.email = email
        self.password = password
        self.account_number = account_number
        self.token: str | None = None
        self.token_expires_at: datetime | None = None
        self.property_id: str | None = None

    def _graphql(self, query: str, variables: dict | None = None) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = self.token

        payload = {"query": query}
        if variables:
            payload["variables"] = variables

        try:
            response = requests.post(GRAPHQL_URL, json=payload, headers=headers, timeout=30)
        except requests.exceptions.RequestException as exc:
            raise RuntimeError(f"Netzwerkfehler: {exc}") from exc

        if not response.ok:
            log.error("API Antwort %s: %s", response.status_code, response.text[:500])
            response.raise_for_status()

        data = response.json()

        if "errors" in data:
            log.error("GraphQL Fehler: %s", json.dumps(data["errors"]))
            raise RuntimeError(f"GraphQL error: {data['errors']}")

        return data.get("data", {})

    def authenticate(self) -> None:
        log.info("Authentifiziere bei Octopus Energy Deutschland...")
        self.token = None
        data = self._graphql(
            QUERY_OBTAIN_TOKEN,
            {"email": self.email, "password": self.password},
        )
        self.token = data["obtainKrakenToken"]["token"]
        self.token_expires_at = datetime.now() + timedelta(minutes=55)
        log.info("Authentifizierung erfolgreich.")

    def ensure_authenticated(self) -> None:
        if not self.token or (self.token_expires_at and datetime.now() >= self.token_expires_at):
            self.authenticate()

    def _query(self, query: str, variables: dict | None = None) -> dict:
        self.ensure_authenticated()
        return self._graphql(query, variables)

    def get_account(self) -> dict:
        data = self._query(QUERY_ACCOUNT, {"accountNumber": self.account_number})
        account = data.get("account", {})
        # Cache property ID
        properties = account.get("properties", [])
        if properties and not self.property_id:
            self.property_id = str(properties[0].get("id", ""))
            log.info("Property ID: %s", self.property_id)
        return account

    def get_payments(self) -> list:
        data = self._query(QUERY_PAYMENTS, {"accountNumber": self.account_number})
        edges = data.get("account", {}).get("payments", {}).get("edges", [])
        return [e["node"] for e in edges]

    def get_bills(self) -> list:
        data = self._query(QUERY_BILLS, {"accountNumber": self.account_number})
        edges = data.get("account", {}).get("bills", {}).get("edges", [])
        return [edge["node"] for edge in edges]

    def get_measurements(self, days_back: int = 400, frequency: str = "DAY_INTERVAL") -> list:
        if not self.property_id:
            raise RuntimeError("Property ID nicht verfügbar – Kontodaten zuerst abrufen.")

        now_utc = datetime.now(timezone.utc)
        start_utc = now_utc - timedelta(days=days_back)

        data = self._query(
            QUERY_MEASUREMENTS,
            {
                "propertyId": self.property_id,
                "first": days_back + 5,
                "startAt": start_utc.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                "endAt": now_utc.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                "timezone": TIMEZONE,
                "utilityFilters": [{"electricityFilters": {"readingFrequencyType": frequency}}],
            },
        )
        edges = data.get("property", {}).get("measurements", {}).get("edges", [])
        return [e["node"] for e in edges]


# ---------------------------------------------------------------------------
# MQTT publisher
# ---------------------------------------------------------------------------

class MQTTPublisher:
    def __init__(self, host: str, port: int, user: str, password: str, topic_prefix: str):
        self.topic_prefix = topic_prefix
        self.reconnected = False
        self._connected = False

        self.client = mqtt.Client()
        if user:
            self.client.username_pw_set(user, password)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.connect(host, port, keepalive=60)
        self.client.loop_start()

    def _on_connect(self, client, userdata, flags, rc) -> None:
        if rc == 0:
            if self._connected:
                log.warning("MQTT Verbindung wiederhergestellt — sofortiger Neuabruf wird ausgelöst.")
                self.reconnected = True
            else:
                self._connected = True
                log.info("MQTT verbunden.")
        else:
            log.error("MQTT Verbindungsfehler: rc=%s", rc)

    def _on_disconnect(self, client, userdata, rc) -> None:
        self._connected = False
        if rc != 0:
            log.warning("MQTT Verbindung verloren (rc=%s). Warte auf Reconnect...", rc)

    def publish(self, subtopic: str, payload) -> None:
        topic = f"{self.topic_prefix}/{subtopic}"
        if isinstance(payload, (dict, list)):
            message = json.dumps(payload, default=str)
        else:
            message = str(payload)
        self.client.publish(topic, message, retain=True)
        log.debug("Veröffentlicht: %s", topic)

    def disconnect(self) -> None:
        self.client.loop_stop()
        self.client.disconnect()


# ---------------------------------------------------------------------------
# Home Assistant MQTT Discovery
# ---------------------------------------------------------------------------

def publish_ha_discovery(mqtt_pub: MQTTPublisher, topic_prefix: str) -> None:
    device = {
        "identifiers": ["octopus_energy_de"],
        "name": "Octopus Energy Deutschland",
        "manufacturer": "Octopus Energy",
        "model": "OEG Kraken API",
        "sw_version": "0.5.11",
    }

    sensors = [
        # Account
        {"name": "Octopus Kontostand", "unique_id": "octopus_account_balance",
         "state_topic": f"{topic_prefix}/account/balance", "unit_of_measurement": "EUR",
         "device_class": "monetary", "icon": "mdi:cash"},
        {"name": "Octopus Überfälliger Betrag", "unique_id": "octopus_overdue_balance",
         "state_topic": f"{topic_prefix}/account/overdue_balance", "unit_of_measurement": "EUR",
         "device_class": "monetary", "icon": "mdi:cash-alert"},
        # Consumption
        {"name": "Octopus Strom Verbrauch Heute", "unique_id": "octopus_consumption_today",
         "state_topic": f"{topic_prefix}/consumption/today", "unit_of_measurement": "kWh",
         "device_class": "energy", "icon": "mdi:lightning-bolt"},
        {"name": "Octopus Strom Verbrauch Gestern", "unique_id": "octopus_consumption_yesterday",
         "state_topic": f"{topic_prefix}/consumption/yesterday", "unit_of_measurement": "kWh",
         "device_class": "energy", "icon": "mdi:lightning-bolt-outline"},
        {"name": "Octopus Strom Verbrauch Aktuelle Woche", "unique_id": "octopus_consumption_current_week",
         "state_topic": f"{topic_prefix}/consumption/current_week", "unit_of_measurement": "kWh",
         "device_class": "energy", "icon": "mdi:lightning-bolt"},
        {"name": "Octopus Strom Verbrauch Letzte Woche", "unique_id": "octopus_consumption_last_week",
         "state_topic": f"{topic_prefix}/consumption/last_week", "unit_of_measurement": "kWh",
         "device_class": "energy", "icon": "mdi:lightning-bolt-outline"},
        {"name": "Octopus Strom Verbrauch Aktueller Monat", "unique_id": "octopus_consumption_current_month",
         "state_topic": f"{topic_prefix}/consumption/current_month", "unit_of_measurement": "kWh",
         "device_class": "energy", "icon": "mdi:lightning-bolt"},
        {"name": "Octopus Strom Verbrauch Letzter Monat", "unique_id": "octopus_consumption_last_month",
         "state_topic": f"{topic_prefix}/consumption/last_month", "unit_of_measurement": "kWh",
         "device_class": "energy", "icon": "mdi:lightning-bolt-outline"},
        {"name": "Octopus Strom Verbrauch Aktuelles Jahr", "unique_id": "octopus_consumption_current_year",
         "state_topic": f"{topic_prefix}/consumption/current_year", "unit_of_measurement": "kWh",
         "device_class": "energy", "icon": "mdi:lightning-bolt"},
        {"name": "Octopus Strom Verbrauch Letztes Jahr", "unique_id": "octopus_consumption_last_year",
         "state_topic": f"{topic_prefix}/consumption/last_year", "unit_of_measurement": "kWh",
         "device_class": "energy", "icon": "mdi:lightning-bolt-outline"},
        # Cost (incl. tax)
        {"name": "Octopus Strom Kosten Heute", "unique_id": "octopus_cost_today",
         "state_topic": f"{topic_prefix}/cost/today", "unit_of_measurement": "EUR",
         "device_class": "monetary", "icon": "mdi:currency-eur"},
        {"name": "Octopus Strom Kosten Gestern", "unique_id": "octopus_cost_yesterday",
         "state_topic": f"{topic_prefix}/cost/yesterday", "unit_of_measurement": "EUR",
         "device_class": "monetary", "icon": "mdi:currency-eur"},
        {"name": "Octopus Strom Kosten Aktuelle Woche", "unique_id": "octopus_cost_current_week",
         "state_topic": f"{topic_prefix}/cost/current_week", "unit_of_measurement": "EUR",
         "device_class": "monetary", "icon": "mdi:currency-eur"},
        {"name": "Octopus Strom Kosten Letzte Woche", "unique_id": "octopus_cost_last_week",
         "state_topic": f"{topic_prefix}/cost/last_week", "unit_of_measurement": "EUR",
         "device_class": "monetary", "icon": "mdi:currency-eur"},
        {"name": "Octopus Strom Kosten Aktueller Monat", "unique_id": "octopus_cost_current_month",
         "state_topic": f"{topic_prefix}/cost/current_month", "unit_of_measurement": "EUR",
         "device_class": "monetary", "icon": "mdi:currency-eur"},
        {"name": "Octopus Strom Kosten Letzter Monat", "unique_id": "octopus_cost_last_month",
         "state_topic": f"{topic_prefix}/cost/last_month", "unit_of_measurement": "EUR",
         "device_class": "monetary", "icon": "mdi:currency-eur"},
        {"name": "Octopus Strom Kosten Aktuelles Jahr", "unique_id": "octopus_cost_current_year",
         "state_topic": f"{topic_prefix}/cost/current_year", "unit_of_measurement": "EUR",
         "device_class": "monetary", "icon": "mdi:currency-eur"},
        {"name": "Octopus Strom Kosten Letztes Jahr", "unique_id": "octopus_cost_last_year",
         "state_topic": f"{topic_prefix}/cost/last_year", "unit_of_measurement": "EUR",
         "device_class": "monetary", "icon": "mdi:currency-eur"},
        # Bills
        {"name": "Octopus Letzte Rechnung (Brutto)", "unique_id": "octopus_last_bill_gross",
         "state_topic": f"{topic_prefix}/bills/latest/gross_total", "unit_of_measurement": "EUR",
         "device_class": "monetary", "icon": "mdi:receipt"},
        {"name": "Octopus Letzte Rechnung (Netto)", "unique_id": "octopus_last_bill_net",
         "state_topic": f"{topic_prefix}/bills/latest/net_total", "unit_of_measurement": "EUR",
         "device_class": "monetary", "icon": "mdi:receipt-outline"},
        {"name": "Octopus Letzte Rechnung Datum", "unique_id": "octopus_last_bill_date",
         "state_topic": f"{topic_prefix}/bills/latest/issued_date", "icon": "mdi:calendar"},
        {"name": "Octopus Letzte Rechnung Von", "unique_id": "octopus_last_bill_from",
         "state_topic": f"{topic_prefix}/bills/latest/from_date", "icon": "mdi:calendar-start"},
        {"name": "Octopus Letzte Rechnung Bis", "unique_id": "octopus_last_bill_to",
         "state_topic": f"{topic_prefix}/bills/latest/to_date", "icon": "mdi:calendar-end"},
        {"name": "Octopus Letzte Rechnung PDF", "unique_id": "octopus_last_bill_pdf_url",
         "state_topic": f"{topic_prefix}/bills/latest/pdf_url", "icon": "mdi:file-pdf-box"},
        {"name": "Octopus Anzahl Rechnungen", "unique_id": "octopus_bill_count",
         "state_topic": f"{topic_prefix}/bills/count", "icon": "mdi:counter"},
        # Individual monthly kWh sensors (current + last year)
        *[
            {
                "name": f"Octopus Verbrauch {yr}-{mo:02d}",
                "unique_id": f"octopus_consumption_{yr}_{mo:02d}",
                "state_topic": f"{topic_prefix}/consumption/monthly/{yr}-{mo:02d}",
                "unit_of_measurement": "kWh",
                "device_class": "energy",
                "state_class": "measurement",
                "icon": "mdi:lightning-bolt",
            }
            for yr in [datetime.now().year - 1, datetime.now().year]
            for mo in range(1, 13)
        ],
        {"name": "Octopus Monatsverbrauch", "unique_id": "octopus_consumption_monthly",
         "state_topic": f"{topic_prefix}/consumption/monthly",
         "value_template": "{{ value_json.months | length }}",
         "json_attributes_topic": f"{topic_prefix}/consumption/monthly",
         "json_attributes_template": "{{ value_json | tojson }}",
         "icon": "mdi:chart-bar"},
        {"name": "Octopus Alle Rechnungen", "unique_id": "octopus_bills_all",
         "state_topic": f"{topic_prefix}/bills/all",
         "value_template": "{{ value_json.bills | length }}",
         "json_attributes_topic": f"{topic_prefix}/bills/all",
         "json_attributes_template": "{{ value_json | tojson }}",
         "icon": "mdi:file-document-multiple"},
        # Payments
        {"name": "Octopus Letzte Zahlung", "unique_id": "octopus_last_payment",
         "state_topic": f"{topic_prefix}/payments/latest/amount", "unit_of_measurement": "EUR",
         "device_class": "monetary", "icon": "mdi:bank-transfer"},
        {"name": "Octopus Letzte Zahlung Datum", "unique_id": "octopus_last_payment_date",
         "state_topic": f"{topic_prefix}/payments/latest/date", "icon": "mdi:calendar-check"},
        # Meta
        {"name": "Octopus Letzter Abruf", "unique_id": "octopus_last_updated",
         "state_topic": f"{topic_prefix}/last_updated", "device_class": "timestamp",
         "icon": "mdi:clock-check"},
        # Tariff info
        {"name": "Octopus Arbeitspreis", "unique_id": "octopus_unit_rate",
         "state_topic": f"{topic_prefix}/tariff/unit_rate", "unit_of_measurement": "EUR/kWh",
         "icon": "mdi:tag"},
    ]

    for sensor in sensors:
        sensor["device"] = device
        discovery_topic = f"homeassistant/sensor/{sensor['unique_id']}/config"
        mqtt_pub.client.publish(discovery_topic, json.dumps(sensor), retain=True)

    log.info("Home Assistant MQTT Discovery: %d Sensoren registriert.", len(sensors))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def sum_kwh(entries: list, date_keys) -> float:
    """Sum kWh for entries whose startAt date matches date_keys (prefix str or set of YYYY-MM-DD)."""
    if isinstance(date_keys, str):
        match = lambda s: s.startswith(date_keys)
    else:
        match = lambda s: s[:10] in date_keys
    return round(sum(float(e.get("value", 0)) for e in entries if match(e.get("startAt", ""))), 3)


def sum_cost(entries: list, date_keys) -> float:
    """Sum cost incl. tax (EUR) for entries whose startAt date matches date_keys."""
    if isinstance(date_keys, str):
        match = lambda s: s.startswith(date_keys)
    else:
        match = lambda s: s[:10] in date_keys
    total = 0.0
    for e in entries:
        if not match(e.get("startAt", "")):
            continue
        for stat in e.get("metaData", {}).get("statistics", []):
            incl = stat.get("costInclTax", {})
            if incl.get("estimatedAmount") is not None:
                total += float(incl["estimatedAmount"])
    return round(total / 100, 2)


def week_dates(monday: datetime) -> set:
    return {(monday + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)}


def try_fetch(label: str, fn):
    try:
        return fn()
    except Exception as exc:
        log.error("Fehler beim Abrufen von %s: %s", label, exc)
        return None


# ---------------------------------------------------------------------------
# Fetch & publish
# ---------------------------------------------------------------------------

def fetch_and_publish(client: OctopusEnergyClient, mqtt_pub: MQTTPublisher) -> None:
    p = mqtt_pub.publish
    now = datetime.now(timezone.utc).astimezone()
    today_str = now.strftime("%Y-%m-%d")
    yesterday_str = (now - timedelta(days=1)).strftime("%Y-%m-%d")

    # Week: Monday-based
    cur_mon = now - timedelta(days=now.weekday())
    last_mon = cur_mon - timedelta(days=7)
    cur_week = week_dates(cur_mon)
    last_week = week_dates(last_mon)

    cur_month = now.strftime("%Y-%m")
    last_month = (now.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    cur_year = now.strftime("%Y")
    last_year = str(now.year - 1)

    try:
        client.ensure_authenticated()
    except Exception as exc:
        log.error("Authentifizierung fehlgeschlagen: %s", exc)
        return

    # -- Account (also caches property_id) -----------------------------------
    account = try_fetch("Kontodaten", client.get_account)
    if account:
        p("account/balance", round(account.get("balance", 0) / 100, 2))
        p("account/overdue_balance", round(account.get("overdueBalance", 0) / 100, 2))
        p("account/details", account)
        for ledger in account.get("ledgers", []):
            p(f"account/ledger/{ledger.get('ledgerType','').lower()}", round(ledger.get("balance", 0) / 100, 2))
        log.info("Kontodaten veröffentlicht. Kontostand: %.2f EUR", account.get("balance", 0) / 100)

    # -- Measurements (consumption + cost) -----------------------------------
    measurements = try_fetch(
        "Verbrauchsdaten",
        lambda: client.get_measurements(days_back=400, frequency="DAY_INTERVAL"),
    )
    if measurements:
        # Consumption (kWh)
        p("consumption/today",        sum_kwh(measurements, today_str))
        p("consumption/yesterday",    sum_kwh(measurements, yesterday_str))
        p("consumption/current_week", sum_kwh(measurements, cur_week))
        p("consumption/last_week",    sum_kwh(measurements, last_week))
        p("consumption/current_month",sum_kwh(measurements, cur_month))
        p("consumption/last_month",   sum_kwh(measurements, last_month))
        p("consumption/current_year", sum_kwh(measurements, cur_year))
        p("consumption/last_year",    sum_kwh(measurements, last_year))

        # Cost (EUR incl. tax)
        p("cost/today",         sum_cost(measurements, today_str))
        p("cost/yesterday",     sum_cost(measurements, yesterday_str))
        p("cost/current_week",  sum_cost(measurements, cur_week))
        p("cost/last_week",     sum_cost(measurements, last_week))
        p("cost/current_month", sum_cost(measurements, cur_month))
        p("cost/last_month",    sum_cost(measurements, last_month))
        p("cost/current_year",  sum_cost(measurements, cur_year))
        p("cost/last_year",     sum_cost(measurements, last_year))

        # Monthly aggregates for current + last year (for year comparison cards)
        monthly = []
        for yr in [last_year, cur_year]:
            for mo in range(1, 13):
                ym = f"{yr}-{mo:02d}"
                kwh = sum_kwh(measurements, ym)
                cost = sum_cost(measurements, ym)
                monthly.append({"month": ym, "kwh": kwh, "cost": cost})
        p("consumption/monthly", {"months": monthly})

        # Individual sensors per month (for chart cards)
        for item in monthly:
            p(f"consumption/monthly/{item['month']}", item['kwh'])

        # Derive unit rate from today's cost/consumption if available
        kwh_today = sum_kwh(measurements, today_str)
        cost_today = sum_cost(measurements, today_str)
        if kwh_today > 0:
            p("tariff/unit_rate", round(cost_today / kwh_today, 4))

        log.info(
            "Verbrauch: Heute %.3f kWh (%.2f EUR) | Monat %.3f kWh (%.2f EUR) | Jahr %.3f kWh (%.2f EUR)",
            kwh_today, cost_today,
            sum_kwh(measurements, cur_month), sum_cost(measurements, cur_month),
            sum_kwh(measurements, cur_year), sum_cost(measurements, cur_year),
        )

    # -- Payments ------------------------------------------------------------
    payments = try_fetch("Zahlungen", client.get_payments)
    if payments:
        p("payments/all", payments)
        p("payments/latest/amount", round(payments[0].get("amount", 0) / 100, 2))
        p("payments/latest/date", payments[0].get("paymentDate", ""))
        p("payments/latest/type", payments[0].get("transactionType", ""))
        log.info("Zahlungen veröffentlicht. Letzte: %.2f EUR", payments[0].get("amount", 0) / 100)

    # -- Bills ---------------------------------------------------------------
    bills = try_fetch("Rechnungen", client.get_bills)
    if bills is not None:
        cutoff = now.replace(year=now.year - 2)
        recent_bills = [
            b for b in bills
            if b.get("issuedDate", "9999") >= cutoff.strftime("%Y-%m-%d")
        ]
        p("bills/count", len(recent_bills))
        # Nur Summary-Felder — temporaryUrl und transactions werden NICHT
        # mitgeschickt (bereits in bills/YYYY-MM/* Topics), um das
        # HA-Recorder-Limit von 16 384 Bytes nicht zu überschreiten.
        bills_summary = [
            {
                "id": b.get("id"),
                "billType": b.get("billType"),
                "fromDate": b.get("fromDate"),
                "toDate": b.get("toDate"),
                "issuedDate": b.get("issuedDate"),
                "totalCharges": b.get("totalCharges", {}),
            }
            for b in recent_bills
        ]
        p("bills/all", {"bills": bills_summary})

        for bill in recent_bills:
            issued = bill.get("issuedDate", "")
            key = issued[:7] if issued else None  # YYYY-MM
            if not key:
                continue
            charges = bill.get("totalCharges", {})
            p(f"bills/{key}/gross_total", round(charges.get("grossTotal", 0) / 100, 2))
            p(f"bills/{key}/net_total",   round(charges.get("netTotal", 0) / 100, 2))
            p(f"bills/{key}/tax_total",   round(charges.get("taxTotal", 0) / 100, 2))
            p(f"bills/{key}/issued_date", issued)
            p(f"bills/{key}/from_date",   bill.get("fromDate", ""))
            p(f"bills/{key}/to_date",     bill.get("toDate", ""))
            p(f"bills/{key}/bill_type",   bill.get("billType", ""))
            p(f"bills/{key}/pdf_url",     bill.get("temporaryUrl", ""))
            transactions = [e["node"] for e in bill.get("transactions", {}).get("edges", [])]
            p(f"bills/{key}/transactions", transactions)

        if recent_bills:
            latest = recent_bills[0]
            charges = latest.get("totalCharges", {})
            p("bills/latest/gross_total", round(charges.get("grossTotal", 0) / 100, 2))
            p("bills/latest/net_total",   round(charges.get("netTotal", 0) / 100, 2))
            p("bills/latest/tax_total",   round(charges.get("taxTotal", 0) / 100, 2))
            p("bills/latest/issued_date", latest.get("issuedDate", ""))
            p("bills/latest/from_date",   latest.get("fromDate", ""))
            p("bills/latest/to_date",     latest.get("toDate", ""))
            p("bills/latest/bill_type",   latest.get("billType", ""))
            p("bills/latest/pdf_url",     latest.get("temporaryUrl", ""))
            log.info("Rechnungen veröffentlicht: %d Stück. Letzte: %.2f EUR",
                     len(recent_bills), charges.get("grossTotal", 0) / 100)

    p("last_updated", now.isoformat())
    log.info("Abruf abgeschlossen.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    email = os.environ["EMAIL"]
    password = os.environ["PASSWORD"]
    account_number = os.environ["ACCOUNT_NUMBER"]
    mqtt_host = os.environ.get("MQTT_HOST", "core-mosquitto")
    mqtt_port = int(os.environ.get("MQTT_PORT", 1883))
    mqtt_user = os.environ.get("MQTT_USER", "")
    mqtt_password = os.environ.get("MQTT_PASSWORD", "")
    topic_prefix = os.environ.get("MQTT_TOPIC_PREFIX", "octopus_energy")
    fetch_interval = int(os.environ.get("FETCH_INTERVAL", 60)) * 60

    client = OctopusEnergyClient(email, password, account_number)
    mqtt_pub = MQTTPublisher(mqtt_host, mqtt_port, mqtt_user, mqtt_password, topic_prefix)

    publish_ha_discovery(mqtt_pub, topic_prefix)

    while True:
        log.info("Starte Datenabruf von Octopus Energy Deutschland...")
        fetch_and_publish(client, mqtt_pub)
        mqtt_pub.reconnected = False
        log.info("Nächster Abruf in %d Minuten.", fetch_interval // 60)

        # Warte in 30-Sekunden-Schritten — reagiert sofort auf MQTT-Reconnect
        elapsed = 0
        while elapsed < fetch_interval:
            time.sleep(30)
            elapsed += 30
            if mqtt_pub.reconnected:
                log.warning("MQTT Reconnect erkannt — starte sofortigen Neuabruf.")
                break


if __name__ == "__main__":
    main()
