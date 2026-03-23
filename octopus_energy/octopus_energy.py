#!/usr/bin/env python3
"""Octopus Energy Deutschland - Home Assistant Add-on."""

import json
import logging
import os
import time
from datetime import datetime, timedelta

import paho.mqtt.client as mqtt
import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

GRAPHQL_URL = "https://api.oeg-kraken.energy/v1/graphql"


# ---------------------------------------------------------------------------
# GraphQL queries
# ---------------------------------------------------------------------------

QUERY_OBTAIN_TOKEN = """
mutation ObtainToken($email: String!, $password: String!) {
  obtainKrakenToken(input: { email: $email, password: $password }) {
    token
    refreshToken
    refreshExpiresIn
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
    electricityAgreements {
      validFrom
      validTo
      tariff {
        ... on HalfHourlyTariff {
          displayName
          standingCharge
          unitRate
        }
        ... on StandardTariff {
          displayName
          standingCharge
          unitRate
        }
      }
    }
  }
}
"""

QUERY_METER_CONSUMPTION = """
query Consumption($accountNumber: String!, $startDate: String!, $endDate: String!) {
  account(accountNumber: $accountNumber) {
    properties {
      electricityMeterPoints {
        meters {
          serialNumber
          consumption(
            startDate: $startDate
            endDate: $endDate
            grouping: DAY
          ) {
            startAt
            endAt
            value
            unit
          }
        }
      }
    }
  }
}
"""

QUERY_BILLS = """
query Bills($accountNumber: String!) {
  account(accountNumber: $accountNumber) {
    bills {
      edges {
        node {
          id
          billType
          fromDate
          toDate
          issuedDate
          temporaryUrl
          totalCharges {
            netTotal
            grossTotal
            taxTotal
          }
          transactions {
            edges {
              node {
                postedDate
                amounts {
                  net
                  tax
                  gross
                }
                title
                isCredit
                isExport
              }
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

    def _graphql(self, query: str, variables: dict | None = None) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = self.token

        payload = {"query": query}
        if variables:
            payload["variables"] = variables

        response = requests.post(GRAPHQL_URL, json=payload, headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json()

        if "errors" in data:
            raise RuntimeError(f"GraphQL error: {data['errors']}")

        return data.get("data", {})

    def authenticate(self) -> None:
        log.info("Authentifiziere bei Octopus Energy Deutschland...")
        data = self._graphql(
            QUERY_OBTAIN_TOKEN,
            {"email": self.email, "password": self.password},
        )
        token_data = data["obtainKrakenToken"]
        self.token = token_data["token"]
        self.token_expires_at = datetime.now() + timedelta(minutes=55)
        log.info("Authentifizierung erfolgreich.")

    def ensure_authenticated(self) -> None:
        if not self.token or (self.token_expires_at and datetime.now() >= self.token_expires_at):
            self.authenticate()

    def get_account(self) -> dict:
        self.ensure_authenticated()
        data = self._graphql(QUERY_ACCOUNT, {"accountNumber": self.account_number})
        return data.get("account", {})

    def get_consumption(self, days_back: int = 30) -> list:
        self.ensure_authenticated()
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
        data = self._graphql(
            QUERY_METER_CONSUMPTION,
            {
                "accountNumber": self.account_number,
                "startDate": start_date,
                "endDate": end_date,
            },
        )
        results = []
        for prop in data.get("account", {}).get("properties", []):
            for meter_point in prop.get("electricityMeterPoints", []):
                for meter in meter_point.get("meters", []):
                    serial = meter.get("serialNumber", "unknown")
                    for entry in meter.get("consumption", []):
                        results.append({
                            "serial_number": serial,
                            **entry,
                        })
        return results

    def get_bills(self) -> list:
        self.ensure_authenticated()
        data = self._graphql(QUERY_BILLS, {"accountNumber": self.account_number})
        edges = data.get("account", {}).get("bills", {}).get("edges", [])
        return [edge["node"] for edge in edges]


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

    def publish(self, subtopic: str, payload: dict | list | str | float) -> None:
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
    sensors = [
        {
            "name": "Octopus Kontostand",
            "unique_id": "octopus_account_balance",
            "state_topic": f"{topic_prefix}/account/balance",
            "unit_of_measurement": "EUR",
            "device_class": "monetary",
            "icon": "mdi:cash",
        },
        {
            "name": "Octopus Überfälliger Betrag",
            "unique_id": "octopus_overdue_balance",
            "state_topic": f"{topic_prefix}/account/overdue_balance",
            "unit_of_measurement": "EUR",
            "device_class": "monetary",
            "icon": "mdi:cash-alert",
        },
        {
            "name": "Octopus Letzte Rechnung (Brutto)",
            "unique_id": "octopus_last_bill_gross",
            "state_topic": f"{topic_prefix}/bills/latest/gross_total",
            "unit_of_measurement": "EUR",
            "device_class": "monetary",
            "icon": "mdi:receipt",
        },
        {
            "name": "Octopus Letzte Rechnung Datum",
            "unique_id": "octopus_last_bill_date",
            "state_topic": f"{topic_prefix}/bills/latest/issued_date",
            "icon": "mdi:calendar",
        },
        {
            "name": "Octopus Verbrauch Heute",
            "unique_id": "octopus_consumption_today",
            "state_topic": f"{topic_prefix}/consumption/today",
            "unit_of_measurement": "kWh",
            "device_class": "energy",
            "icon": "mdi:lightning-bolt",
        },
    ]

    device = {
        "identifiers": ["octopus_energy_de"],
        "name": "Octopus Energy Deutschland",
        "manufacturer": "Octopus Energy",
        "model": "OEG Kraken API",
    }

    for sensor in sensors:
        sensor["device"] = device
        discovery_topic = f"homeassistant/sensor/{sensor['unique_id']}/config"
        mqtt_pub.client.publish(discovery_topic, json.dumps(sensor), retain=True)
        log.debug("HA Discovery: %s", discovery_topic)

    log.info("Home Assistant MQTT Discovery Sensoren registriert.")


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def fetch_and_publish(client: OctopusEnergyClient, mqtt_pub: MQTTPublisher) -> None:
    topic_prefix = mqtt_pub.topic_prefix

    # -- Account data --------------------------------------------------------
    try:
        account = client.get_account()
        balance = account.get("balance", 0)
        overdue = account.get("overdueBalance", 0)

        mqtt_pub.publish("account/balance", round(balance / 100, 2))
        mqtt_pub.publish("account/overdue_balance", round(overdue / 100, 2))
        mqtt_pub.publish("account/details", account)

        ledgers = account.get("ledgers", [])
        for ledger in ledgers:
            ledger_type = ledger.get("ledgerType", "UNKNOWN").lower()
            mqtt_pub.publish(f"account/ledger/{ledger_type}", round(ledger.get("balance", 0) / 100, 2))

        log.info("Kontodaten veröffentlicht. Kontostand: %.2f EUR", balance / 100)
    except Exception as exc:
        log.error("Fehler beim Abrufen der Kontodaten: %s", exc)

    # -- Bills ---------------------------------------------------------------
    try:
        bills = client.get_bills()
        mqtt_pub.publish("bills/all", bills)

        if bills:
            latest = bills[0]
            charges = latest.get("totalCharges", {})
            gross = charges.get("grossTotal", 0)
            mqtt_pub.publish("bills/latest/gross_total", round(gross / 100, 2))
            mqtt_pub.publish("bills/latest/issued_date", latest.get("issuedDate", ""))
            mqtt_pub.publish("bills/latest/from_date", latest.get("fromDate", ""))
            mqtt_pub.publish("bills/latest/to_date", latest.get("toDate", ""))
            mqtt_pub.publish("bills/latest/details", latest)
            log.info("Rechnungsdaten veröffentlicht. Letzte Rechnung: %.2f EUR", gross / 100)
    except Exception as exc:
        log.error("Fehler beim Abrufen der Rechnungen: %s", exc)

    # -- Consumption ---------------------------------------------------------
    try:
        consumption = client.get_consumption(days_back=30)
        mqtt_pub.publish("consumption/last_30_days", consumption)

        today_str = datetime.now().strftime("%Y-%m-%d")
        today_entries = [e for e in consumption if e.get("startAt", "").startswith(today_str)]
        today_total = sum(float(e.get("value", 0)) for e in today_entries)
        mqtt_pub.publish("consumption/today", round(today_total, 3))

        yesterday_str = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        yesterday_entries = [e for e in consumption if e.get("startAt", "").startswith(yesterday_str)]
        yesterday_total = sum(float(e.get("value", 0)) for e in yesterday_entries)
        mqtt_pub.publish("consumption/yesterday", round(yesterday_total, 3))

        log.info("Verbrauchsdaten veröffentlicht. Heute: %.3f kWh, Gestern: %.3f kWh",
                 today_total, yesterday_total)
    except Exception as exc:
        log.error("Fehler beim Abrufen der Verbrauchsdaten: %s", exc)

    mqtt_pub.publish("last_updated", datetime.now().isoformat())


def main() -> None:
    email = os.environ["EMAIL"]
    password = os.environ["PASSWORD"]
    account_number = os.environ["ACCOUNT_NUMBER"]
    mqtt_host = os.environ.get("MQTT_HOST", "core-mosquitto")
    mqtt_port = int(os.environ.get("MQTT_PORT", 1883))
    mqtt_user = os.environ.get("MQTT_USER", "")
    mqtt_password = os.environ.get("MQTT_PASSWORD", "")
    topic_prefix = os.environ.get("MQTT_TOPIC_PREFIX", "octopus_energy")
    fetch_interval = int(os.environ.get("FETCH_INTERVAL", 60)) * 60  # convert to seconds

    client = OctopusEnergyClient(email, password, account_number)
    mqtt_pub = MQTTPublisher(mqtt_host, mqtt_port, mqtt_user, mqtt_password, topic_prefix)

    publish_ha_discovery(mqtt_pub, topic_prefix)

    while True:
        log.info("Starte Datenabruf von Octopus Energy...")
        fetch_and_publish(client, mqtt_pub)
        log.info("Nächster Abruf in %d Minuten.", fetch_interval // 60)
        time.sleep(fetch_interval)


if __name__ == "__main__":
    main()
