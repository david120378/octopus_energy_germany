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
    bills(first: 10) {
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

    def get_measurements(self, days_back: int = 30, frequency: str = "DAY_INTERVAL") -> list:
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
        self.client = mqtt.Client()
        if user:
            self.client.username_pw_set(user, password)
        self.client.connect(host, port, keepalive=60)
        self.client.loop_start()

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
        "sw_version": "0.4.0",
    }

    sensors = [
        # Account
        {"name": "Octopus Kontostand", "unique_id": "octopus_account_balance",
         "state_topic": f"{topic_prefix}/account/balance", "unit_of_measurement": "EUR",
         "device_class": "monetary", "icon": "mdi:cash"},
        {"name": "Octopus Überfälliger Betrag", "unique_id": "octopus_overdue_balance",
         "state_topic": f"{topic_prefix}/account/overdue_balance", "unit_of_measurement": "EUR",
         "device_class": "monetary", "icon": "mdi:cash-alert"},
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
        # Consumption
        {"name": "Octopus Strom Verbrauch Heute", "unique_id": "octopus_electricity_today",
         "state_topic": f"{topic_prefix}/consumption/today", "unit_of_measurement": "kWh",
         "device_class": "energy", "state_class": "total_increasing", "icon": "mdi:lightning-bolt"},
        {"name": "Octopus Strom Verbrauch Gestern", "unique_id": "octopus_electricity_yesterday",
         "state_topic": f"{topic_prefix}/consumption/yesterday", "unit_of_measurement": "kWh",
         "device_class": "energy", "icon": "mdi:lightning-bolt-outline"},
        {"name": "Octopus Strom Verbrauch Aktueller Monat", "unique_id": "octopus_electricity_current_month",
         "state_topic": f"{topic_prefix}/consumption/current_month", "unit_of_measurement": "kWh",
         "device_class": "energy", "icon": "mdi:lightning-bolt"},
        {"name": "Octopus Strom Verbrauch Letzter Monat", "unique_id": "octopus_electricity_last_month",
         "state_topic": f"{topic_prefix}/consumption/last_month", "unit_of_measurement": "kWh",
         "device_class": "energy", "icon": "mdi:lightning-bolt-outline"},
        # Cost (from API, incl. tax)
        {"name": "Octopus Strom Kosten Heute", "unique_id": "octopus_cost_today",
         "state_topic": f"{topic_prefix}/cost/today", "unit_of_measurement": "EUR",
         "device_class": "monetary", "icon": "mdi:currency-eur"},
        {"name": "Octopus Strom Kosten Gestern", "unique_id": "octopus_cost_yesterday",
         "state_topic": f"{topic_prefix}/cost/yesterday", "unit_of_measurement": "EUR",
         "device_class": "monetary", "icon": "mdi:currency-eur"},
        {"name": "Octopus Strom Kosten Aktueller Monat", "unique_id": "octopus_cost_current_month",
         "state_topic": f"{topic_prefix}/cost/current_month", "unit_of_measurement": "EUR",
         "device_class": "monetary", "icon": "mdi:currency-eur"},
        {"name": "Octopus Strom Kosten Letzter Monat", "unique_id": "octopus_cost_last_month",
         "state_topic": f"{topic_prefix}/cost/last_month", "unit_of_measurement": "EUR",
         "device_class": "monetary", "icon": "mdi:currency-eur"},
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
    ]

    for sensor in sensors:
        sensor["device"] = device
        discovery_topic = f"homeassistant/sensor/{sensor['unique_id']}/config"
        mqtt_pub.client.publish(discovery_topic, json.dumps(sensor), retain=True)

    log.info("Home Assistant MQTT Discovery: %d Sensoren registriert.", len(sensors))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def sum_kwh(entries: list, date_prefix: str) -> float:
    return round(sum(
        float(e.get("value", 0))
        for e in entries
        if e.get("startAt", "").startswith(date_prefix)
    ), 3)

def sum_cost(entries: list, date_prefix: str) -> float:
    total = 0.0
    for e in entries:
        if not e.get("startAt", "").startswith(date_prefix):
            continue
        for stat in e.get("metaData", {}).get("statistics", []):
            incl = stat.get("costInclTax", {})
            if incl.get("estimatedAmount") is not None:
                total += float(incl["estimatedAmount"])
    return round(total / 100, 4)


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
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    cur_month = now.strftime("%Y-%m")
    last_mo = (now.replace(day=1) - timedelta(days=1))
    last_month = last_mo.strftime("%Y-%m")

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
        lambda: client.get_measurements(days_back=60, frequency="DAY_INTERVAL"),
    )
    if measurements:
        p("consumption/all", measurements)

        kwh_today = sum_kwh(measurements, today)
        kwh_yesterday = sum_kwh(measurements, yesterday)
        kwh_cur_month = sum(
            float(e.get("value", 0))
            for e in measurements if e.get("startAt", "").startswith(cur_month)
        )
        kwh_last_month = sum(
            float(e.get("value", 0))
            for e in measurements if e.get("startAt", "").startswith(last_month)
        )
        p("consumption/today", round(kwh_today, 3))
        p("consumption/yesterday", round(kwh_yesterday, 3))
        p("consumption/current_month", round(kwh_cur_month, 3))
        p("consumption/last_month", round(kwh_last_month, 3))

        cost_today = sum_cost(measurements, today)
        cost_yesterday = sum_cost(measurements, yesterday)
        cost_cur_month = sum(
            sum_cost([e], e.get("startAt", "")[:7])
            for e in measurements if e.get("startAt", "").startswith(cur_month)
        )
        cost_last_month = sum(
            sum_cost([e], e.get("startAt", "")[:7])
            for e in measurements if e.get("startAt", "").startswith(last_month)
        )
        p("cost/today", round(cost_today, 4))
        p("cost/yesterday", round(cost_yesterday, 4))
        p("cost/current_month", round(cost_cur_month, 2))
        p("cost/last_month", round(cost_last_month, 2))

        log.info(
            "Verbrauch: Heute %.3f kWh (%.2f EUR), Monat %.3f kWh (%.2f EUR)",
            kwh_today, cost_today, kwh_cur_month, cost_cur_month,
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
        p("bills/count", len(bills))
        p("bills/all", bills)
        if bills:
            latest = bills[0]
            charges = latest.get("totalCharges", {})
            p("bills/latest/gross_total", round(charges.get("grossTotal", 0) / 100, 2))
            p("bills/latest/net_total", round(charges.get("netTotal", 0) / 100, 2))
            p("bills/latest/tax_total", round(charges.get("taxTotal", 0) / 100, 2))
            p("bills/latest/issued_date", latest.get("issuedDate", ""))
            p("bills/latest/from_date", latest.get("fromDate", ""))
            p("bills/latest/to_date", latest.get("toDate", ""))
            p("bills/latest/bill_type", latest.get("billType", ""))
            p("bills/latest/pdf_url", latest.get("temporaryUrl", ""))
            transactions = [e["node"] for e in latest.get("transactions", {}).get("edges", [])]
            p("bills/latest/transactions", transactions)
            log.info("Rechnungen veröffentlicht. Letzte: %.2f EUR", charges.get("grossTotal", 0) / 100)

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
        log.info("Nächster Abruf in %d Minuten.", fetch_interval // 60)
        time.sleep(fetch_interval)


if __name__ == "__main__":
    main()
