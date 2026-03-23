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

GRAPHQL_URL = "https://api.oeg-kraken.energy/v1/graphql/"


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
  }
}
"""

QUERY_PAYMENTS = """
query Payments($accountNumber: String!) {
  account(accountNumber: $accountNumber) {
    payments {
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

QUERY_METER_INFO = """
query MeterInfo($accountNumber: String!) {
  account(accountNumber: $accountNumber) {
    properties {
      electricityMalos {
        marketLocationId
        meters {
          serialNumber
          isExport
          smartDevices {
            deviceId
          }
        }
      }
      gasMalos {
        marketLocationId
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
      electricityMalos {
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
      gasMalos {
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
      electricityMalos {
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
      electricityMalos {
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
      gasMalos {
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
          ... on InvoiceType {
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
          ... on StatementType {
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
        # Reset token before authenticating (no Authorization header)
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
        return data.get("account", {})

    def get_payments(self) -> list:
        data = self._query(QUERY_PAYMENTS, {"accountNumber": self.account_number})
        edges = data.get("account", {}).get("payments", {}).get("edges", [])
        return [e["node"] for e in edges]

    def get_meter_info(self) -> dict:
        data = self._query(QUERY_METER_INFO, {"accountNumber": self.account_number})
        return data.get("account", {})

    def get_consumption_daily(self, days_back: int = 365) -> dict:
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
        data = self._query(
            QUERY_METER_CONSUMPTION_DAILY,
            {"accountNumber": self.account_number, "startDate": start_date, "endDate": end_date},
        )
        return self._parse_consumption(data)

    def get_consumption_halfhour(self, days_back: int = 2) -> dict:
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
        data = self._query(
            QUERY_METER_CONSUMPTION_HALFHOUR,
            {"accountNumber": self.account_number, "startDate": start_date, "endDate": end_date},
        )
        return self._parse_consumption(data)

    def get_consumption_monthly(self, months_back: int = 12) -> dict:
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=months_back * 31)).strftime("%Y-%m-%d")
        data = self._query(
            QUERY_METER_CONSUMPTION_MONTHLY,
            {"accountNumber": self.account_number, "startDate": start_date, "endDate": end_date},
        )
        return self._parse_consumption(data)

    def get_bills(self) -> list:
        data = self._query(QUERY_BILLS, {"accountNumber": self.account_number})
        edges = data.get("account", {}).get("bills", {}).get("edges", [])
        return [edge["node"] for edge in edges]

    def _parse_consumption(self, data: dict) -> dict:
        result = {"electricity": [], "electricity_export": [], "gas": []}
        for prop in data.get("account", {}).get("properties", []):
            for mp in prop.get("electricityMalos", []):
                for meter in mp.get("meters", []):
                    serial = meter.get("serialNumber", "unknown")
                    is_export = meter.get("isExport", False)
                    key = "electricity_export" if is_export else "electricity"
                    for entry in meter.get("consumption", []):
                        result[key].append({"serial_number": serial, **entry})
            for mp in prop.get("gasMalos", []):
                for meter in mp.get("meters", []):
                    serial = meter.get("serialNumber", "unknown")
                    for entry in meter.get("consumption", []):
                        result["gas"].append({"serial_number": serial, **entry})
        return result


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
        "sw_version": "0.2.4",
    }

    sensors = [
        # Account
        {"name": "Octopus Kontostand", "unique_id": "octopus_account_balance",
         "state_topic": f"{topic_prefix}/account/balance", "unit_of_measurement": "EUR",
         "device_class": "monetary", "icon": "mdi:cash"},
        {"name": "Octopus Überfälliger Betrag", "unique_id": "octopus_overdue_balance",
         "state_topic": f"{topic_prefix}/account/overdue_balance", "unit_of_measurement": "EUR",
         "device_class": "monetary", "icon": "mdi:cash-alert"},
        # Tariff electricity
        {"name": "Octopus Strom Arbeitspreis", "unique_id": "octopus_electricity_unit_rate",
         "state_topic": f"{topic_prefix}/tariff/electricity/unit_rate_ct",
         "unit_of_measurement": "ct/kWh", "icon": "mdi:lightning-bolt"},
        {"name": "Octopus Strom Grundgebühr", "unique_id": "octopus_electricity_standing_charge",
         "state_topic": f"{topic_prefix}/tariff/electricity/standing_charge_ct",
         "unit_of_measurement": "ct/Tag", "icon": "mdi:calendar-today"},
        {"name": "Octopus Strom Tarifname", "unique_id": "octopus_electricity_tariff_name",
         "state_topic": f"{topic_prefix}/tariff/electricity/display_name", "icon": "mdi:tag"},
        {"name": "Octopus Strom Tarif gültig bis", "unique_id": "octopus_electricity_tariff_valid_to",
         "state_topic": f"{topic_prefix}/tariff/electricity/valid_to", "icon": "mdi:calendar-end"},
        # Tariff gas
        {"name": "Octopus Gas Arbeitspreis", "unique_id": "octopus_gas_unit_rate",
         "state_topic": f"{topic_prefix}/tariff/gas/unit_rate_ct",
         "unit_of_measurement": "ct/kWh", "icon": "mdi:fire"},
        {"name": "Octopus Gas Grundgebühr", "unique_id": "octopus_gas_standing_charge",
         "state_topic": f"{topic_prefix}/tariff/gas/standing_charge_ct",
         "unit_of_measurement": "ct/Tag", "icon": "mdi:calendar-today"},
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
        # Electricity consumption
        {"name": "Octopus Strom Verbrauch Heute", "unique_id": "octopus_electricity_today",
         "state_topic": f"{topic_prefix}/consumption/electricity/today",
         "unit_of_measurement": "kWh", "device_class": "energy",
         "state_class": "total_increasing", "icon": "mdi:lightning-bolt"},
        {"name": "Octopus Strom Verbrauch Gestern", "unique_id": "octopus_electricity_yesterday",
         "state_topic": f"{topic_prefix}/consumption/electricity/yesterday",
         "unit_of_measurement": "kWh", "device_class": "energy", "icon": "mdi:lightning-bolt-outline"},
        {"name": "Octopus Strom Verbrauch Aktueller Monat", "unique_id": "octopus_electricity_current_month",
         "state_topic": f"{topic_prefix}/consumption/electricity/current_month",
         "unit_of_measurement": "kWh", "device_class": "energy", "icon": "mdi:lightning-bolt"},
        {"name": "Octopus Strom Verbrauch Letzter Monat", "unique_id": "octopus_electricity_last_month",
         "state_topic": f"{topic_prefix}/consumption/electricity/last_month",
         "unit_of_measurement": "kWh", "device_class": "energy", "icon": "mdi:lightning-bolt-outline"},
        {"name": "Octopus Strom Verbrauch Aktuelles Jahr", "unique_id": "octopus_electricity_current_year",
         "state_topic": f"{topic_prefix}/consumption/electricity/current_year",
         "unit_of_measurement": "kWh", "device_class": "energy", "icon": "mdi:lightning-bolt"},
        # Electricity cost
        {"name": "Octopus Strom Kosten Heute", "unique_id": "octopus_electricity_cost_today",
         "state_topic": f"{topic_prefix}/cost/electricity/today", "unit_of_measurement": "EUR",
         "device_class": "monetary", "icon": "mdi:currency-eur"},
        {"name": "Octopus Strom Kosten Gestern", "unique_id": "octopus_electricity_cost_yesterday",
         "state_topic": f"{topic_prefix}/cost/electricity/yesterday", "unit_of_measurement": "EUR",
         "device_class": "monetary", "icon": "mdi:currency-eur"},
        {"name": "Octopus Strom Kosten Aktueller Monat", "unique_id": "octopus_electricity_cost_current_month",
         "state_topic": f"{topic_prefix}/cost/electricity/current_month", "unit_of_measurement": "EUR",
         "device_class": "monetary", "icon": "mdi:currency-eur"},
        # Export
        {"name": "Octopus Strom Einspeisung Heute", "unique_id": "octopus_electricity_export_today",
         "state_topic": f"{topic_prefix}/consumption/electricity_export/today",
         "unit_of_measurement": "kWh", "device_class": "energy", "icon": "mdi:solar-power"},
        {"name": "Octopus Strom Einspeisung Gestern", "unique_id": "octopus_electricity_export_yesterday",
         "state_topic": f"{topic_prefix}/consumption/electricity_export/yesterday",
         "unit_of_measurement": "kWh", "device_class": "energy", "icon": "mdi:solar-power"},
        # Gas
        {"name": "Octopus Gas Verbrauch Heute", "unique_id": "octopus_gas_today",
         "state_topic": f"{topic_prefix}/consumption/gas/today",
         "unit_of_measurement": "kWh", "device_class": "energy", "icon": "mdi:fire"},
        {"name": "Octopus Gas Verbrauch Gestern", "unique_id": "octopus_gas_yesterday",
         "state_topic": f"{topic_prefix}/consumption/gas/yesterday",
         "unit_of_measurement": "kWh", "device_class": "energy", "icon": "mdi:fire"},
        {"name": "Octopus Gas Verbrauch Aktueller Monat", "unique_id": "octopus_gas_current_month",
         "state_topic": f"{topic_prefix}/consumption/gas/current_month",
         "unit_of_measurement": "kWh", "device_class": "energy", "icon": "mdi:fire"},
        # Meter
        {"name": "Octopus Stromzähler Seriennummer", "unique_id": "octopus_electricity_meter_serial",
         "state_topic": f"{topic_prefix}/meter/electricity/serial_number", "icon": "mdi:counter"},
        {"name": "Octopus Gaszähler Seriennummer", "unique_id": "octopus_gas_meter_serial",
         "state_topic": f"{topic_prefix}/meter/gas/serial_number", "icon": "mdi:counter"},
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
# Helper functions
# ---------------------------------------------------------------------------

def sum_for_date(entries: list, date_str: str) -> float:
    return sum(float(e.get("value", 0)) for e in entries if e.get("startAt", "").startswith(date_str))

def sum_for_month(entries: list, year: int, month: int) -> float:
    prefix = f"{year:04d}-{month:02d}"
    return sum(float(e.get("value", 0)) for e in entries if e.get("startAt", "").startswith(prefix))

def sum_for_year(entries: list, year: int) -> float:
    prefix = f"{year:04d}"
    return sum(float(e.get("value", 0)) for e in entries if e.get("startAt", "").startswith(prefix))

def calc_cost(kwh: float, unit_rate_ct: float, standing_charge_ct: float, days: float = 1.0) -> float:
    return round((kwh * unit_rate_ct + standing_charge_ct * days) / 100, 4)


# ---------------------------------------------------------------------------
# Fetch & publish
# ---------------------------------------------------------------------------

def try_fetch(label: str, fn):
    """Run fn(), log errors, return result or None."""
    try:
        return fn()
    except Exception as exc:
        log.error("Fehler beim Abrufen von %s: %s", label, exc)
        return None


def fetch_and_publish(client: OctopusEnergyClient, mqtt_pub: MQTTPublisher) -> None:
    p = mqtt_pub.publish
    prefix = mqtt_pub.topic_prefix
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")

    electricity_unit_rate = 0.0
    electricity_standing_charge = 0.0

    # -- Authenticate once upfront ------------------------------------------
    try:
        client.ensure_authenticated()
    except Exception as exc:
        log.error("Authentifizierung fehlgeschlagen: %s", exc)
        return

    # -- Account -------------------------------------------------------------
    account = try_fetch("Kontodaten", client.get_account)
    if account:
        p("account/balance", round(account.get("balance", 0) / 100, 2))
        p("account/overdue_balance", round(account.get("overdueBalance", 0) / 100, 2))
        p("account/details", account)
        for ledger in account.get("ledgers", []):
            p(f"account/ledger/{ledger.get('ledgerType','').lower()}", round(ledger.get("balance", 0) / 100, 2))
        log.info("Kontodaten veröffentlicht. Kontostand: %.2f EUR", account.get("balance", 0) / 100)

    # -- Meter info ----------------------------------------------------------
    meter_info = try_fetch("Zählerdaten", client.get_meter_info)
    if meter_info:
        for prop in meter_info.get("properties", []):
            elec_malos = prop.get("electricityMalos", [])
            if elec_malos:
                p("meter/electricity/malo_id", elec_malos[0].get("marketLocationId", ""))
                meters = elec_malos[0].get("meters", [])
                if meters:
                    p("meter/electricity/serial_number", meters[0].get("serialNumber", ""))
                    p("meter/electricity/is_smart", bool(meters[0].get("smartDevices")))
            gas_malos = prop.get("gasMalos", [])
            if gas_malos:
                p("meter/gas/malo_id", gas_malos[0].get("marketLocationId", ""))
                gas_meters = gas_malos[0].get("meters", [])
                if gas_meters:
                    p("meter/gas/serial_number", gas_meters[0].get("serialNumber", ""))

    # -- Payments ------------------------------------------------------------
    payments = try_fetch("Zahlungen", client.get_payments)
    if payments:
        p("payments/all", payments)
        p("payments/latest/amount", round(payments[0].get("amount", 0) / 100, 2))
        p("payments/latest/date", payments[0].get("paymentDate", ""))
        p("payments/latest/type", payments[0].get("transactionType", ""))

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
            p("bills/latest/transactions", [e["node"] for e in latest.get("transactions", {}).get("edges", [])])
            log.info("Rechnungen veröffentlicht. Letzte: %.2f EUR", charges.get("grossTotal", 0) / 100)

    # -- Daily consumption ---------------------------------------------------
    daily = try_fetch("Tagesverbräuche", lambda: client.get_consumption_daily(days_back=365))
    if daily:
        elec = daily["electricity"]
        elec_export = daily["electricity_export"]
        gas = daily["gas"]

        p("consumption/electricity/last_365_days", elec)

        elec_today = sum_for_date(elec, today)
        elec_yesterday = sum_for_date(elec, yesterday)
        elec_cur_month = sum_for_month(elec, now.year, now.month)
        last_mo = now.replace(day=1) - timedelta(days=1)
        elec_last_month = sum_for_month(elec, last_mo.year, last_mo.month)
        elec_year = sum_for_year(elec, now.year)

        p("consumption/electricity/today", round(elec_today, 3))
        p("consumption/electricity/yesterday", round(elec_yesterday, 3))
        p("consumption/electricity/current_month", round(elec_cur_month, 3))
        p("consumption/electricity/last_month", round(elec_last_month, 3))
        p("consumption/electricity/current_year", round(elec_year, 3))

        if elec_export:
            p("consumption/electricity_export/last_365_days", elec_export)
            p("consumption/electricity_export/today", round(sum_for_date(elec_export, today), 3))
            p("consumption/electricity_export/yesterday", round(sum_for_date(elec_export, yesterday), 3))

        if gas:
            p("consumption/gas/last_365_days", gas)
            p("consumption/gas/today", round(sum_for_date(gas, today), 3))
            p("consumption/gas/yesterday", round(sum_for_date(gas, yesterday), 3))
            p("consumption/gas/current_month", round(sum_for_month(gas, now.year, now.month), 3))
            p("consumption/gas/current_year", round(sum_for_year(gas, now.year), 3))

        if electricity_unit_rate > 0:
            p("cost/electricity/today", calc_cost(elec_today, electricity_unit_rate, electricity_standing_charge))
            p("cost/electricity/yesterday", calc_cost(elec_yesterday, electricity_unit_rate, electricity_standing_charge))
            p("cost/electricity/current_month", calc_cost(elec_cur_month, electricity_unit_rate, electricity_standing_charge, days=now.day))

        log.info("Strom: Heute %.3f kWh, Monat %.3f kWh, Jahr %.3f kWh", elec_today, elec_cur_month, elec_year)

    # -- Monthly consumption -------------------------------------------------
    monthly = try_fetch("Monatsverbräuche", lambda: client.get_consumption_monthly(months_back=12))
    if monthly:
        p("consumption/electricity/monthly_12", monthly["electricity"])
        if monthly["gas"]:
            p("consumption/gas/monthly_12", monthly["gas"])

    # -- Half-hour consumption -----------------------------------------------
    halfhour = try_fetch("15-Min-Verbräuche", lambda: client.get_consumption_halfhour(days_back=2))
    if halfhour:
        p("consumption/electricity/halfhour_2days", halfhour["electricity"])

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
