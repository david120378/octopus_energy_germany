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
    properties {
      id
    }
  }
}
"""

QUERY_PAYMENTS = """
query Payments($accountNumber: String!) {
  account(accountNumber: $accountNumber) {
    payments(first: 5) {
      edges {
        node {
          amount
          paymentDate
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
          ... on InvoiceType {
            totalCharges {
              netTotal
              grossTotal
            }
          }
          ... on StatementType {
            totalCharges {
              netTotal
              grossTotal
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

    def get_measurements(self, days_back: int = 400) -> list:
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
                "utilityFilters": [{"electricityFilters": {"readingFrequencyType": "DAY_INTERVAL"}}],
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

# Sensor-IDs die in früheren Versionen existierten und jetzt entfernt werden.
# Leere Payloads löschen die Discovery-Einträge aus HA.
_REMOVED_UNIQUE_IDS = [
    "octopus_consumption_today",
    "octopus_consumption_yesterday",
    "octopus_consumption_current_week",
    "octopus_consumption_last_week",
    "octopus_consumption_current_month",
    "octopus_consumption_last_month",
    "octopus_consumption_current_year",
    "octopus_consumption_last_year",
    "octopus_cost_today",
    "octopus_cost_yesterday",
    "octopus_cost_current_week",
    "octopus_cost_last_week",
    "octopus_cost_last_month",
    "octopus_cost_last_year",
    "octopus_last_bill_net",
    "octopus_last_bill_from",
    "octopus_last_bill_to",
    "octopus_last_bill_pdf_url",
    "octopus_bill_count",
    "octopus_consumption_monthly",
    "octopus_last_payment_date",
    *[f"octopus_consumption_{yr}_{mo:02d}"
      for yr in [datetime.now().year - 1, datetime.now().year]
      for mo in range(1, 13)],
    *[f"octopus_cost_{yr}_{mo:02d}"
      for yr in [datetime.now().year - 1, datetime.now().year]
      for mo in range(1, 13)],
]


def publish_ha_discovery(mqtt_pub: MQTTPublisher, topic_prefix: str) -> None:
    device = {
        "identifiers": ["octopus_energy_de"],
        "name": "Octopus Energy Deutschland",
        "manufacturer": "Octopus Energy",
        "model": "OEG Kraken API",
        "sw_version": "0.6.0",
    }

    sensors = [
        # Konto
        {"name": "Octopus Kontostand", "unique_id": "octopus_account_balance",
         "state_topic": f"{topic_prefix}/account/balance", "unit_of_measurement": "EUR",
         "device_class": "monetary", "icon": "mdi:cash"},
        {"name": "Octopus Überfälliger Betrag", "unique_id": "octopus_overdue_balance",
         "state_topic": f"{topic_prefix}/account/overdue_balance", "unit_of_measurement": "EUR",
         "device_class": "monetary", "icon": "mdi:cash-alert"},
        # Zählerstand — Basis für HA Long-Term Statistics (Tag / Monat / Jahr)
        {"name": "Octopus Strom Zählerstand", "unique_id": "octopus_consumption_cumulative",
         "state_topic": f"{topic_prefix}/consumption/cumulative",
         "unit_of_measurement": "kWh", "device_class": "energy", "state_class": "total",
         "icon": "mdi:counter"},
        # Kosten (aus Rechnungen)
        {"name": "Octopus Strom Kosten Aktueller Monat", "unique_id": "octopus_cost_current_month",
         "state_topic": f"{topic_prefix}/cost/current_month", "unit_of_measurement": "EUR",
         "device_class": "monetary", "state_class": "total", "icon": "mdi:currency-eur"},
        {"name": "Octopus Strom Kosten Aktuelles Jahr", "unique_id": "octopus_cost_current_year",
         "state_topic": f"{topic_prefix}/cost/current_year", "unit_of_measurement": "EUR",
         "device_class": "monetary", "state_class": "total", "icon": "mdi:currency-eur"},
        # Tarif
        {"name": "Octopus Arbeitspreis", "unique_id": "octopus_unit_rate",
         "state_topic": f"{topic_prefix}/tariff/unit_rate", "unit_of_measurement": "EUR/kWh",
         "icon": "mdi:tag"},
        # Rechnungen
        {"name": "Octopus Letzte Rechnung (Brutto)", "unique_id": "octopus_last_bill_gross",
         "state_topic": f"{topic_prefix}/bills/latest/gross_total", "unit_of_measurement": "EUR",
         "device_class": "monetary", "icon": "mdi:receipt"},
        {"name": "Octopus Letzte Rechnung Datum", "unique_id": "octopus_last_bill_date",
         "state_topic": f"{topic_prefix}/bills/latest/issued_date", "icon": "mdi:calendar"},
        {"name": "Octopus Alle Rechnungen", "unique_id": "octopus_bills_all",
         "state_topic": f"{topic_prefix}/bills/all",
         "value_template": "{{ value_json.bills | length }}",
         "json_attributes_topic": f"{topic_prefix}/bills/all",
         "json_attributes_template": "{{ value_json | tojson }}",
         "icon": "mdi:file-document-multiple"},
        # Zahlungen
        {"name": "Octopus Letzte Zahlung", "unique_id": "octopus_last_payment",
         "state_topic": f"{topic_prefix}/payments/latest/amount", "unit_of_measurement": "EUR",
         "device_class": "monetary", "icon": "mdi:bank-transfer"},
        # Meta
        {"name": "Octopus Letzter Abruf", "unique_id": "octopus_last_updated",
         "state_topic": f"{topic_prefix}/last_updated", "device_class": "timestamp",
         "icon": "mdi:clock-check"},
    ]

    for sensor in sensors:
        sensor["device"] = device
        discovery_topic = f"homeassistant/sensor/{sensor['unique_id']}/config"
        mqtt_pub.client.publish(discovery_topic, json.dumps(sensor), retain=True)

    # Alte Discovery-Einträge aus früheren Versionen löschen
    for uid in _REMOVED_UNIQUE_IDS:
        mqtt_pub.client.publish(f"homeassistant/sensor/{uid}/config", "", retain=True)

    log.info("Home Assistant MQTT Discovery: %d Sensoren registriert, %d alte entfernt.",
             len(sensors), len(_REMOVED_UNIQUE_IDS))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def sum_kwh(entries: list, date_prefix: str) -> float:
    """Summiert kWh für alle Einträge deren startAt mit date_prefix beginnt."""
    return round(
        sum(float(e.get("value", 0)) for e in entries
            if e.get("startAt", "").startswith(date_prefix)),
        3,
    )


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
    cur_month = now.strftime("%Y-%m")
    cur_year = now.strftime("%Y")
    last_month = (now.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")

    try:
        client.ensure_authenticated()
    except Exception as exc:
        log.error("Authentifizierung fehlgeschlagen: %s", exc)
        return

    # -- Account --
    account = try_fetch("Kontodaten", client.get_account)
    if account:
        p("account/balance", round(account.get("balance", 0) / 100, 2))
        p("account/overdue_balance", round(account.get("overdueBalance", 0) / 100, 2))
        log.info("Kontostand: %.2f EUR", account.get("balance", 0) / 100)

    # -- Measurements → kumulativer Zählerstand (Basis für HA-Statistiken) --
    measurements = try_fetch(
        "Verbrauchsdaten",
        lambda: client.get_measurements(days_back=400),
    )
    if measurements:
        cumulative_kwh = round(sum(float(e.get("value", 0)) for e in measurements), 3)
        p("consumption/cumulative", cumulative_kwh)
        log.info("Zählerstand: %.3f kWh (aus %d Tagen)", cumulative_kwh, len(measurements))

    # -- Payments --
    payments = try_fetch("Zahlungen", client.get_payments)
    if payments:
        p("payments/latest/amount", round(payments[0].get("amount", 0) / 100, 2))
        log.info("Letzte Zahlung: %.2f EUR", payments[0].get("amount", 0) / 100)

    # -- Bills --
    bills = try_fetch("Rechnungen", client.get_bills)
    if bills is not None:
        cutoff = now.replace(year=now.year - 2)
        recent_bills = [
            b for b in bills
            if b.get("issuedDate", "9999") >= cutoff.strftime("%Y-%m-%d")
        ]

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

        if recent_bills:
            latest = recent_bills[0]
            charges = latest.get("totalCharges", {})
            p("bills/latest/gross_total", round(charges.get("grossTotal", 0) / 100, 2))
            p("bills/latest/issued_date", latest.get("issuedDate", ""))

        # Monatliche Kosten (aus fromDate)
        bill_costs = {}
        for bill in recent_bills:
            from_key = bill.get("fromDate", "")[:7]
            if from_key:
                bill_costs[from_key] = round(
                    bill.get("totalCharges", {}).get("grossTotal", 0) / 100, 2
                )

        p("cost/current_month", bill_costs.get(cur_month, 0))
        p("cost/current_year",
          round(sum(v for k, v in bill_costs.items() if k.startswith(cur_year)), 2))

        # Arbeitspreis aus letztem vollständigen Monat
        if measurements:
            lm_cost = bill_costs.get(last_month, 0)
            lm_kwh = sum_kwh(measurements, last_month)
            if lm_kwh > 0 and lm_cost > 0:
                p("tariff/unit_rate", round(lm_cost / lm_kwh, 4))

        log.info(
            "Kosten: %s=%.2f EUR | %s=%.2f EUR",
            cur_month, bill_costs.get(cur_month, 0),
            cur_year, round(sum(v for k, v in bill_costs.items() if k.startswith(cur_year)), 2),
        )

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

        elapsed = 0
        while elapsed < fetch_interval:
            time.sleep(30)
            elapsed += 30
            if mqtt_pub.reconnected:
                log.warning("MQTT Reconnect erkannt — starte sofortigen Neuabruf.")
                break


if __name__ == "__main__":
    main()
