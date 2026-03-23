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
    gasAgreements {
      validFrom
      validTo
      tariff {
        ... on StandardTariff {
          displayName
          standingCharge
          unitRate
        }
      }
    }
    payments {
      edges {
        node {
          amount
          postedDate
          transactionType
        }
      }
    }
    properties {
      electricityMeterPoints {
        mpan
        meters {
          serialNumber
          isExport
          smartDevices {
            deviceId
          }
        }
      }
      gasMeterPoints {
        mprn
        meters {
          serialNumber
        }
      }
    }
  }
}
"""

QUERY_METER_CONSUMPTION_DAILY = """
query ConsumptionDaily($accountNumber: String!, $startDate: String!, $endDate: String!) {
  account(accountNumber: $accountNumber) {
    properties {
      electricityMeterPoints {
        meters {
          serialNumber
          isExport
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
      gasMeterPoints {
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

QUERY_METER_CONSUMPTION_HALFHOUR = """
query ConsumptionHalfHour($accountNumber: String!, $startDate: String!, $endDate: String!) {
  account(accountNumber: $accountNumber) {
    properties {
      electricityMeterPoints {
        meters {
          serialNumber
          isExport
          consumption(
            startDate: $startDate
            endDate: $endDate
            grouping: HALF_HOUR
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

QUERY_METER_CONSUMPTION_MONTHLY = """
query ConsumptionMonthly($accountNumber: String!, $startDate: String!, $endDate: String!) {
  account(accountNumber: $accountNumber) {
    properties {
      electricityMeterPoints {
        meters {
          serialNumber
          isExport
          consumption(
            startDate: $startDate
            endDate: $endDate
            grouping: MONTH
          ) {
            startAt
            endAt
            value
            unit
          }
        }
      }
      gasMeterPoints {
        meters {
          serialNumber
          consumption(
            startDate: $startDate
            endDate: $endDate
            grouping: MONTH
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

    def get_consumption_daily(self, days_back: int = 30) -> dict:
        self.ensure_authenticated()
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
        data = self._graphql(
            QUERY_METER_CONSUMPTION_DAILY,
            {"accountNumber": self.account_number, "startDate": start_date, "endDate": end_date},
        )
        return self._parse_consumption(data)

    def get_consumption_halfhour(self, days_back: int = 2) -> dict:
        self.ensure_authenticated()
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
        data = self._graphql(
            QUERY_METER_CONSUMPTION_HALFHOUR,
            {"accountNumber": self.account_number, "startDate": start_date, "endDate": end_date},
        )
        return self._parse_consumption(data)

    def get_consumption_monthly(self, months_back: int = 12) -> dict:
        self.ensure_authenticated()
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=months_back * 31)).strftime("%Y-%m-%d")
        data = self._graphql(
            QUERY_METER_CONSUMPTION_MONTHLY,
            {"accountNumber": self.account_number, "startDate": start_date, "endDate": end_date},
        )
        return self._parse_consumption(data)

    def _parse_consumption(self, data: dict) -> dict:
        result = {"electricity": [], "electricity_export": [], "gas": []}
        for prop in data.get("account", {}).get("properties", []):
            for meter_point in prop.get("electricityMeterPoints", []):
                for meter in meter_point.get("meters", []):
                    serial = meter.get("serialNumber", "unknown")
                    is_export = meter.get("isExport", False)
                    key = "electricity_export" if is_export else "electricity"
                    for entry in meter.get("consumption", []):
                        result[key].append({"serial_number": serial, **entry})
            for meter_point in prop.get("gasMeterPoints", []):
                for meter in meter_point.get("meters", []):
                    serial = meter.get("serialNumber", "unknown")
                    for entry in meter.get("consumption", []):
                        result["gas"].append({"serial_number": serial, **entry})
        return result

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
        "sw_version": "1.1.0",
    }

    sensors = [
        # Account
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
        # Tariff - Electricity
        {
            "name": "Octopus Strom Arbeitspreis",
            "unique_id": "octopus_electricity_unit_rate",
            "state_topic": f"{topic_prefix}/tariff/electricity/unit_rate_ct",
            "unit_of_measurement": "ct/kWh",
            "icon": "mdi:lightning-bolt",
        },
        {
            "name": "Octopus Strom Grundgebühr",
            "unique_id": "octopus_electricity_standing_charge",
            "state_topic": f"{topic_prefix}/tariff/electricity/standing_charge_ct",
            "unit_of_measurement": "ct/Tag",
            "icon": "mdi:calendar-today",
        },
        {
            "name": "Octopus Strom Tarifname",
            "unique_id": "octopus_electricity_tariff_name",
            "state_topic": f"{topic_prefix}/tariff/electricity/display_name",
            "icon": "mdi:tag",
        },
        {
            "name": "Octopus Strom Tarif gültig bis",
            "unique_id": "octopus_electricity_tariff_valid_to",
            "state_topic": f"{topic_prefix}/tariff/electricity/valid_to",
            "icon": "mdi:calendar-end",
        },
        # Tariff - Gas
        {
            "name": "Octopus Gas Arbeitspreis",
            "unique_id": "octopus_gas_unit_rate",
            "state_topic": f"{topic_prefix}/tariff/gas/unit_rate_ct",
            "unit_of_measurement": "ct/kWh",
            "icon": "mdi:fire",
        },
        {
            "name": "Octopus Gas Grundgebühr",
            "unique_id": "octopus_gas_standing_charge",
            "state_topic": f"{topic_prefix}/tariff/gas/standing_charge_ct",
            "unit_of_measurement": "ct/Tag",
            "icon": "mdi:calendar-today",
        },
        # Bills
        {
            "name": "Octopus Letzte Rechnung (Brutto)",
            "unique_id": "octopus_last_bill_gross",
            "state_topic": f"{topic_prefix}/bills/latest/gross_total",
            "unit_of_measurement": "EUR",
            "device_class": "monetary",
            "icon": "mdi:receipt",
        },
        {
            "name": "Octopus Letzte Rechnung (Netto)",
            "unique_id": "octopus_last_bill_net",
            "state_topic": f"{topic_prefix}/bills/latest/net_total",
            "unit_of_measurement": "EUR",
            "device_class": "monetary",
            "icon": "mdi:receipt-outline",
        },
        {
            "name": "Octopus Letzte Rechnung Datum",
            "unique_id": "octopus_last_bill_date",
            "state_topic": f"{topic_prefix}/bills/latest/issued_date",
            "icon": "mdi:calendar",
        },
        {
            "name": "Octopus Letzte Rechnung Von",
            "unique_id": "octopus_last_bill_from",
            "state_topic": f"{topic_prefix}/bills/latest/from_date",
            "icon": "mdi:calendar-start",
        },
        {
            "name": "Octopus Letzte Rechnung Bis",
            "unique_id": "octopus_last_bill_to",
            "state_topic": f"{topic_prefix}/bills/latest/to_date",
            "icon": "mdi:calendar-end",
        },
        {
            "name": "Octopus Letzte Rechnung PDF",
            "unique_id": "octopus_last_bill_pdf_url",
            "state_topic": f"{topic_prefix}/bills/latest/pdf_url",
            "icon": "mdi:file-pdf-box",
        },
        {
            "name": "Octopus Anzahl Rechnungen",
            "unique_id": "octopus_bill_count",
            "state_topic": f"{topic_prefix}/bills/count",
            "icon": "mdi:counter",
        },
        # Electricity consumption
        {
            "name": "Octopus Strom Verbrauch Heute",
            "unique_id": "octopus_electricity_today",
            "state_topic": f"{topic_prefix}/consumption/electricity/today",
            "unit_of_measurement": "kWh",
            "device_class": "energy",
            "state_class": "total_increasing",
            "icon": "mdi:lightning-bolt",
        },
        {
            "name": "Octopus Strom Verbrauch Gestern",
            "unique_id": "octopus_electricity_yesterday",
            "state_topic": f"{topic_prefix}/consumption/electricity/yesterday",
            "unit_of_measurement": "kWh",
            "device_class": "energy",
            "icon": "mdi:lightning-bolt-outline",
        },
        {
            "name": "Octopus Strom Verbrauch Aktueller Monat",
            "unique_id": "octopus_electricity_current_month",
            "state_topic": f"{topic_prefix}/consumption/electricity/current_month",
            "unit_of_measurement": "kWh",
            "device_class": "energy",
            "icon": "mdi:lightning-bolt",
        },
        {
            "name": "Octopus Strom Verbrauch Letzter Monat",
            "unique_id": "octopus_electricity_last_month",
            "state_topic": f"{topic_prefix}/consumption/electricity/last_month",
            "unit_of_measurement": "kWh",
            "device_class": "energy",
            "icon": "mdi:lightning-bolt-outline",
        },
        {
            "name": "Octopus Strom Verbrauch Aktuelles Jahr",
            "unique_id": "octopus_electricity_current_year",
            "state_topic": f"{topic_prefix}/consumption/electricity/current_year",
            "unit_of_measurement": "kWh",
            "device_class": "energy",
            "icon": "mdi:lightning-bolt",
        },
        # Electricity cost
        {
            "name": "Octopus Strom Kosten Heute",
            "unique_id": "octopus_electricity_cost_today",
            "state_topic": f"{topic_prefix}/cost/electricity/today",
            "unit_of_measurement": "EUR",
            "device_class": "monetary",
            "icon": "mdi:currency-eur",
        },
        {
            "name": "Octopus Strom Kosten Gestern",
            "unique_id": "octopus_electricity_cost_yesterday",
            "state_topic": f"{topic_prefix}/cost/electricity/yesterday",
            "unit_of_measurement": "EUR",
            "device_class": "monetary",
            "icon": "mdi:currency-eur",
        },
        {
            "name": "Octopus Strom Kosten Aktueller Monat",
            "unique_id": "octopus_electricity_cost_current_month",
            "state_topic": f"{topic_prefix}/cost/electricity/current_month",
            "unit_of_measurement": "EUR",
            "device_class": "monetary",
            "icon": "mdi:currency-eur",
        },
        # Electricity export
        {
            "name": "Octopus Strom Einspeisung Heute",
            "unique_id": "octopus_electricity_export_today",
            "state_topic": f"{topic_prefix}/consumption/electricity_export/today",
            "unit_of_measurement": "kWh",
            "device_class": "energy",
            "icon": "mdi:solar-power",
        },
        {
            "name": "Octopus Strom Einspeisung Gestern",
            "unique_id": "octopus_electricity_export_yesterday",
            "state_topic": f"{topic_prefix}/consumption/electricity_export/yesterday",
            "unit_of_measurement": "kWh",
            "device_class": "energy",
            "icon": "mdi:solar-power",
        },
        # Gas consumption
        {
            "name": "Octopus Gas Verbrauch Heute",
            "unique_id": "octopus_gas_today",
            "state_topic": f"{topic_prefix}/consumption/gas/today",
            "unit_of_measurement": "kWh",
            "device_class": "energy",
            "icon": "mdi:fire",
        },
        {
            "name": "Octopus Gas Verbrauch Gestern",
            "unique_id": "octopus_gas_yesterday",
            "state_topic": f"{topic_prefix}/consumption/gas/yesterday",
            "unit_of_measurement": "kWh",
            "device_class": "energy",
            "icon": "mdi:fire",
        },
        {
            "name": "Octopus Gas Verbrauch Aktueller Monat",
            "unique_id": "octopus_gas_current_month",
            "state_topic": f"{topic_prefix}/consumption/gas/current_month",
            "unit_of_measurement": "kWh",
            "device_class": "energy",
            "icon": "mdi:fire",
        },
        # Meter info
        {
            "name": "Octopus Stromzähler Seriennummer",
            "unique_id": "octopus_electricity_meter_serial",
            "state_topic": f"{topic_prefix}/meter/electricity/serial_number",
            "icon": "mdi:counter",
        },
        {
            "name": "Octopus Gaszähler Seriennummer",
            "unique_id": "octopus_gas_meter_serial",
            "state_topic": f"{topic_prefix}/meter/gas/serial_number",
            "icon": "mdi:counter",
        },
        # Payments
        {
            "name": "Octopus Letzte Zahlung",
            "unique_id": "octopus_last_payment",
            "state_topic": f"{topic_prefix}/payments/latest/amount",
            "unit_of_measurement": "EUR",
            "device_class": "monetary",
            "icon": "mdi:bank-transfer",
        },
        {
            "name": "Octopus Letzte Zahlung Datum",
            "unique_id": "octopus_last_payment_date",
            "state_topic": f"{topic_prefix}/payments/latest/date",
            "icon": "mdi:calendar-check",
        },
        # Metadata
        {
            "name": "Octopus Letzter Abruf",
            "unique_id": "octopus_last_updated",
            "state_topic": f"{topic_prefix}/last_updated",
            "device_class": "timestamp",
            "icon": "mdi:clock-check",
        },
    ]

    for sensor in sensors:
        sensor["device"] = device
        discovery_topic = f"homeassistant/sensor/{sensor['unique_id']}/config"
        mqtt_pub.client.publish(discovery_topic, json.dumps(sensor), retain=True)
        log.debug("HA Discovery: %s", discovery_topic)

    log.info("Home Assistant MQTT Discovery: %d Sensoren registriert.", len(sensors))


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def sum_consumption_for_date(entries: list, date_str: str) -> float:
    return sum(float(e.get("value", 0)) for e in entries if e.get("startAt", "").startswith(date_str))


def sum_consumption_for_month(entries: list, year: int, month: int) -> float:
    prefix = f"{year:04d}-{month:02d}"
    return sum(float(e.get("value", 0)) for e in entries if e.get("startAt", "").startswith(prefix))


def sum_consumption_for_year(entries: list, year: int) -> float:
    prefix = f"{year:04d}"
    return sum(float(e.get("value", 0)) for e in entries if e.get("startAt", "").startswith(prefix))


def calculate_cost(kwh: float, unit_rate_ct: float, standing_charge_ct: float, days: float = 1.0) -> float:
    """Calculate cost in EUR from kWh, unit rate (ct/kWh), and standing charge (ct/day)."""
    return round((kwh * unit_rate_ct + standing_charge_ct * days) / 100, 4)


# ---------------------------------------------------------------------------
# Main fetch & publish
# ---------------------------------------------------------------------------

def fetch_and_publish(client: OctopusEnergyClient, mqtt_pub: MQTTPublisher) -> None:
    topic_prefix = mqtt_pub.topic_prefix
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    yesterday_str = (now - timedelta(days=1)).strftime("%Y-%m-%d")

    electricity_unit_rate = 0.0
    electricity_standing_charge = 0.0

    # -- Account & tariff data -----------------------------------------------
    try:
        account = client.get_account()
        balance = account.get("balance", 0)
        overdue = account.get("overdueBalance", 0)

        mqtt_pub.publish("account/balance", round(balance / 100, 2))
        mqtt_pub.publish("account/overdue_balance", round(overdue / 100, 2))
        mqtt_pub.publish("account/details", account)

        for ledger in account.get("ledgers", []):
            ledger_type = ledger.get("ledgerType", "UNKNOWN").lower()
            mqtt_pub.publish(f"account/ledger/{ledger_type}", round(ledger.get("balance", 0) / 100, 2))

        # Electricity tariff
        elec_agreements = account.get("electricityAgreements", [])
        if elec_agreements:
            active = elec_agreements[0]
            tariff = active.get("tariff", {})
            electricity_unit_rate = tariff.get("unitRate", 0.0)
            electricity_standing_charge = tariff.get("standingCharge", 0.0)
            mqtt_pub.publish("tariff/electricity/display_name", tariff.get("displayName", ""))
            mqtt_pub.publish("tariff/electricity/unit_rate_ct", round(electricity_unit_rate, 4))
            mqtt_pub.publish("tariff/electricity/standing_charge_ct", round(electricity_standing_charge, 4))
            mqtt_pub.publish("tariff/electricity/valid_from", active.get("validFrom", ""))
            mqtt_pub.publish("tariff/electricity/valid_to", active.get("validTo", "") or "unbegrenzt")
            mqtt_pub.publish("tariff/electricity/details", active)

        # Gas tariff
        gas_agreements = account.get("gasAgreements", [])
        if gas_agreements:
            active_gas = gas_agreements[0]
            tariff_gas = active_gas.get("tariff", {})
            mqtt_pub.publish("tariff/gas/display_name", tariff_gas.get("displayName", ""))
            mqtt_pub.publish("tariff/gas/unit_rate_ct", round(tariff_gas.get("unitRate", 0.0), 4))
            mqtt_pub.publish("tariff/gas/standing_charge_ct", round(tariff_gas.get("standingCharge", 0.0), 4))
            mqtt_pub.publish("tariff/gas/valid_from", active_gas.get("validFrom", ""))
            mqtt_pub.publish("tariff/gas/valid_to", active_gas.get("validTo", "") or "unbegrenzt")

        # Meter info
        for prop in account.get("properties", []):
            elec_points = prop.get("electricityMeterPoints", [])
            if elec_points:
                mpan = elec_points[0].get("mpan", "")
                mqtt_pub.publish("meter/electricity/mpan", mpan)
                meters = elec_points[0].get("meters", [])
                if meters:
                    mqtt_pub.publish("meter/electricity/serial_number", meters[0].get("serialNumber", ""))
                    has_smart = bool(meters[0].get("smartDevices"))
                    mqtt_pub.publish("meter/electricity/is_smart", has_smart)
                    export_meters = [m for m in meters if m.get("isExport")]
                    if export_meters:
                        mqtt_pub.publish("meter/electricity_export/serial_number", export_meters[0].get("serialNumber", ""))

            gas_points = prop.get("gasMeterPoints", [])
            if gas_points:
                mprn = gas_points[0].get("mprn", "")
                mqtt_pub.publish("meter/gas/mprn", mprn)
                gas_meters = gas_points[0].get("meters", [])
                if gas_meters:
                    mqtt_pub.publish("meter/gas/serial_number", gas_meters[0].get("serialNumber", ""))

        # Payments
        payment_edges = account.get("payments", {}).get("edges", [])
        payments = [e["node"] for e in payment_edges]
        mqtt_pub.publish("payments/all", payments)
        if payments:
            latest_payment = payments[0]
            mqtt_pub.publish("payments/latest/amount", round(latest_payment.get("amount", 0) / 100, 2))
            mqtt_pub.publish("payments/latest/date", latest_payment.get("postedDate", ""))
            mqtt_pub.publish("payments/latest/type", latest_payment.get("transactionType", ""))

        log.info("Kontodaten veröffentlicht. Kontostand: %.2f EUR", balance / 100)
    except Exception as exc:
        log.error("Fehler beim Abrufen der Kontodaten: %s", exc)

    # -- Bills ---------------------------------------------------------------
    try:
        bills = client.get_bills()
        mqtt_pub.publish("bills/all", bills)
        mqtt_pub.publish("bills/count", len(bills))

        if bills:
            latest = bills[0]
            charges = latest.get("totalCharges", {})
            gross = charges.get("grossTotal", 0)
            net = charges.get("netTotal", 0)
            tax = charges.get("taxTotal", 0)
            mqtt_pub.publish("bills/latest/gross_total", round(gross / 100, 2))
            mqtt_pub.publish("bills/latest/net_total", round(net / 100, 2))
            mqtt_pub.publish("bills/latest/tax_total", round(tax / 100, 2))
            mqtt_pub.publish("bills/latest/issued_date", latest.get("issuedDate", ""))
            mqtt_pub.publish("bills/latest/from_date", latest.get("fromDate", ""))
            mqtt_pub.publish("bills/latest/to_date", latest.get("toDate", ""))
            mqtt_pub.publish("bills/latest/bill_type", latest.get("billType", ""))
            mqtt_pub.publish("bills/latest/pdf_url", latest.get("temporaryUrl", ""))
            mqtt_pub.publish("bills/latest/details", latest)

            transactions = [e["node"] for e in latest.get("transactions", {}).get("edges", [])]
            mqtt_pub.publish("bills/latest/transactions", transactions)

            log.info("Rechnungsdaten veröffentlicht. Letzte Rechnung: %.2f EUR, PDF: %s",
                     gross / 100, "verfügbar" if latest.get("temporaryUrl") else "nicht verfügbar")
    except Exception as exc:
        log.error("Fehler beim Abrufen der Rechnungen: %s", exc)

    # -- Daily consumption (last 365 days) -----------------------------------
    try:
        daily = client.get_consumption_daily(days_back=365)
        elec = daily["electricity"]
        elec_export = daily["electricity_export"]
        gas = daily["gas"]

        mqtt_pub.publish("consumption/electricity/last_365_days", elec)
        if elec_export:
            mqtt_pub.publish("consumption/electricity_export/last_365_days", elec_export)
        if gas:
            mqtt_pub.publish("consumption/gas/last_365_days", gas)

        # Electricity - today / yesterday
        elec_today = sum_consumption_for_date(elec, today_str)
        elec_yesterday = sum_consumption_for_date(elec, yesterday_str)
        mqtt_pub.publish("consumption/electricity/today", round(elec_today, 3))
        mqtt_pub.publish("consumption/electricity/yesterday", round(elec_yesterday, 3))

        # Electricity - current & last month
        elec_current_month = sum_consumption_for_month(elec, now.year, now.month)
        last_month = now.replace(day=1) - timedelta(days=1)
        elec_last_month = sum_consumption_for_month(elec, last_month.year, last_month.month)
        mqtt_pub.publish("consumption/electricity/current_month", round(elec_current_month, 3))
        mqtt_pub.publish("consumption/electricity/last_month", round(elec_last_month, 3))

        # Electricity - current year
        elec_current_year = sum_consumption_for_year(elec, now.year)
        mqtt_pub.publish("consumption/electricity/current_year", round(elec_current_year, 3))

        # Export
        export_today = sum_consumption_for_date(elec_export, today_str)
        export_yesterday = sum_consumption_for_date(elec_export, yesterday_str)
        mqtt_pub.publish("consumption/electricity_export/today", round(export_today, 3))
        mqtt_pub.publish("consumption/electricity_export/yesterday", round(export_yesterday, 3))

        # Gas
        if gas:
            gas_today = sum_consumption_for_date(gas, today_str)
            gas_yesterday = sum_consumption_for_date(gas, yesterday_str)
            gas_current_month = sum_consumption_for_month(gas, now.year, now.month)
            mqtt_pub.publish("consumption/gas/today", round(gas_today, 3))
            mqtt_pub.publish("consumption/gas/yesterday", round(gas_yesterday, 3))
            mqtt_pub.publish("consumption/gas/current_month", round(gas_current_month, 3))
            mqtt_pub.publish("consumption/gas/current_year", round(sum_consumption_for_year(gas, now.year), 3))

        # Cost calculations (electricity)
        if electricity_unit_rate > 0:
            cost_today = calculate_cost(elec_today, electricity_unit_rate, electricity_standing_charge)
            cost_yesterday = calculate_cost(elec_yesterday, electricity_unit_rate, electricity_standing_charge)
            cost_current_month = calculate_cost(
                elec_current_month, electricity_unit_rate,
                electricity_standing_charge, days=now.day,
            )
            mqtt_pub.publish("cost/electricity/today", cost_today)
            mqtt_pub.publish("cost/electricity/yesterday", cost_yesterday)
            mqtt_pub.publish("cost/electricity/current_month", cost_current_month)

        log.info(
            "Verbrauch (Strom): Heute %.3f kWh, Gestern %.3f kWh, Monat %.3f kWh, Jahr %.3f kWh",
            elec_today, elec_yesterday, elec_current_month, elec_current_year,
        )
    except Exception as exc:
        log.error("Fehler beim Abrufen der Tagesverbräuche: %s", exc)

    # -- Monthly consumption (12 months) -------------------------------------
    try:
        monthly = client.get_consumption_monthly(months_back=12)
        mqtt_pub.publish("consumption/electricity/monthly_12", monthly["electricity"])
        if monthly["gas"]:
            mqtt_pub.publish("consumption/gas/monthly_12", monthly["gas"])
        log.info("Monatliche Verbrauchsdaten veröffentlicht.")
    except Exception as exc:
        log.error("Fehler beim Abrufen der Monatsverbräuche: %s", exc)

    # -- Half-hour consumption (last 2 days) ---------------------------------
    try:
        halfhour = client.get_consumption_halfhour(days_back=2)
        mqtt_pub.publish("consumption/electricity/halfhour_2days", halfhour["electricity"])
        log.info("15-Minuten-Verbrauchsdaten veröffentlicht.")
    except Exception as exc:
        log.error("Fehler beim Abrufen der 15-Min-Verbräuche: %s", exc)

    mqtt_pub.publish("last_updated", now.isoformat())
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
