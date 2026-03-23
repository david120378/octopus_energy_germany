# Octopus Energy Deutschland – Home Assistant Add-on

Dieses Add-on ruft automatisch Rechnungs- und Verbrauchsdaten von **Octopus Energy Deutschland** ab und veröffentlicht sie via **MQTT** in Home Assistant.

## Installation

1. In Home Assistant: **Einstellungen → Add-ons → Add-on Store → ⋮ → Repositories**
2. URL dieses Repos hinzufügen
3. Add-on installieren und konfigurieren

## Konfiguration

| Option | Beschreibung | Standard |
|--------|-------------|---------|
| `email` | Octopus Energy Login-E-Mail | – |
| `password` | Octopus Energy Passwort | – |
| `account_number` | Kontonummer (z.B. `A-XXXX1234`) | – |
| `mqtt_host` | MQTT Broker Hostname | `core-mosquitto` |
| `mqtt_port` | MQTT Broker Port | `1883` |
| `mqtt_user` | MQTT Benutzername (optional) | – |
| `mqtt_password` | MQTT Passwort (optional) | – |
| `mqtt_topic_prefix` | MQTT Topic Präfix | `octopus_energy` |
| `fetch_interval_minutes` | Abrufintervall in Minuten | `60` |

### Kontonummer finden
Die Kontonummer findet sich im Octopus Energy Kundenportal. Format: `A-XXXX1234`

---

## MQTT Topics

### Konto
| Topic | Beschreibung |
|-------|-------------|
| `octopus_energy/account/balance` | Kontostand in EUR |
| `octopus_energy/account/overdue_balance` | Überfälliger Betrag in EUR |
| `octopus_energy/account/ledger/electricity_ledger` | Strom-Ledger Saldo EUR |
| `octopus_energy/account/ledger/gas_ledger` | Gas-Ledger Saldo EUR |
| `octopus_energy/account/details` | Vollständige Kontodaten (JSON) |

### Tarif – Strom
| Topic | Beschreibung |
|-------|-------------|
| `octopus_energy/tariff/electricity/display_name` | Tarifname |
| `octopus_energy/tariff/electricity/unit_rate_ct` | Arbeitspreis in ct/kWh |
| `octopus_energy/tariff/electricity/standing_charge_ct` | Grundgebühr in ct/Tag |
| `octopus_energy/tariff/electricity/valid_from` | Tarif gültig ab |
| `octopus_energy/tariff/electricity/valid_to` | Tarif gültig bis |

### Tarif – Gas
| Topic | Beschreibung |
|-------|-------------|
| `octopus_energy/tariff/gas/display_name` | Tarifname |
| `octopus_energy/tariff/gas/unit_rate_ct` | Arbeitspreis in ct/kWh |
| `octopus_energy/tariff/gas/standing_charge_ct` | Grundgebühr in ct/Tag |

### Rechnungen
| Topic | Beschreibung |
|-------|-------------|
| `octopus_energy/bills/count` | Anzahl Rechnungen |
| `octopus_energy/bills/all` | Alle Rechnungen (JSON) |
| `octopus_energy/bills/latest/gross_total` | Letzte Rechnung Brutto EUR |
| `octopus_energy/bills/latest/net_total` | Letzte Rechnung Netto EUR |
| `octopus_energy/bills/latest/tax_total` | Letzte Rechnung MwSt EUR |
| `octopus_energy/bills/latest/issued_date` | Rechnungsdatum |
| `octopus_energy/bills/latest/from_date` | Abrechnungszeitraum Von |
| `octopus_energy/bills/latest/to_date` | Abrechnungszeitraum Bis |
| `octopus_energy/bills/latest/pdf_url` | Temporärer PDF-Download-Link |
| `octopus_energy/bills/latest/transactions` | Einzelposten der Rechnung (JSON) |

### Verbrauch – Strom
| Topic | Beschreibung |
|-------|-------------|
| `octopus_energy/consumption/electricity/today` | Heute (kWh) |
| `octopus_energy/consumption/electricity/yesterday` | Gestern (kWh) |
| `octopus_energy/consumption/electricity/current_month` | Aktueller Monat (kWh) |
| `octopus_energy/consumption/electricity/last_month` | Letzter Monat (kWh) |
| `octopus_energy/consumption/electricity/current_year` | Aktuelles Jahr (kWh) |
| `octopus_energy/consumption/electricity/last_365_days` | Tageswerte letzte 365 Tage (JSON) |
| `octopus_energy/consumption/electricity/monthly_12` | Monatswerte letzte 12 Monate (JSON) |
| `octopus_energy/consumption/electricity/halfhour_2days` | 15-Min-Werte letzte 2 Tage (JSON) |

### Verbrauch – Einspeisung (PV/Export)
| Topic | Beschreibung |
|-------|-------------|
| `octopus_energy/consumption/electricity_export/today` | Einspeisung Heute (kWh) |
| `octopus_energy/consumption/electricity_export/yesterday` | Einspeisung Gestern (kWh) |
| `octopus_energy/consumption/electricity_export/last_365_days` | Tageswerte (JSON) |

### Verbrauch – Gas
| Topic | Beschreibung |
|-------|-------------|
| `octopus_energy/consumption/gas/today` | Heute (kWh) |
| `octopus_energy/consumption/gas/yesterday` | Gestern (kWh) |
| `octopus_energy/consumption/gas/current_month` | Aktueller Monat (kWh) |
| `octopus_energy/consumption/gas/current_year` | Aktuelles Jahr (kWh) |

### Kosten (berechnet aus Tarif × Verbrauch)
| Topic | Beschreibung |
|-------|-------------|
| `octopus_energy/cost/electricity/today` | Strom Kosten Heute (EUR) |
| `octopus_energy/cost/electricity/yesterday` | Strom Kosten Gestern (EUR) |
| `octopus_energy/cost/electricity/current_month` | Strom Kosten Aktueller Monat (EUR) |

### Zähler
| Topic | Beschreibung |
|-------|-------------|
| `octopus_energy/meter/electricity/serial_number` | Stromzähler Seriennummer |
| `octopus_energy/meter/electricity/mpan` | MPAN |
| `octopus_energy/meter/electricity/is_smart` | Smartmeter vorhanden |
| `octopus_energy/meter/gas/serial_number` | Gaszähler Seriennummer |
| `octopus_energy/meter/gas/mprn` | MPRN |

### Zahlungen
| Topic | Beschreibung |
|-------|-------------|
| `octopus_energy/payments/latest/amount` | Letzte Zahlung (EUR) |
| `octopus_energy/payments/latest/date` | Datum der letzten Zahlung |
| `octopus_energy/payments/latest/type` | Art der Zahlung |
| `octopus_energy/payments/all` | Alle Zahlungen (JSON) |

---

## Home Assistant Sensoren (MQTT Discovery)

Das Add-on registriert automatisch **30 Sensoren** in Home Assistant:

- Konto: Kontostand, Überfälliger Betrag
- Tarif: Arbeitspreis & Grundgebühr (Strom + Gas), Tarifname, Gültigkeitsdatum
- Rechnungen: Brutto/Netto, Datum, Zeitraum, Anzahl, PDF-Link
- Strom Verbrauch: Heute, Gestern, Aktueller Monat, Letzter Monat, Aktuelles Jahr
- Strom Kosten: Heute, Gestern, Aktueller Monat
- Einspeisung: Heute, Gestern
- Gas Verbrauch: Heute, Gestern, Aktueller Monat
- Zähler: Seriennummer Strom & Gas
- Zahlungen: Letzter Betrag & Datum
- Letzter Abruf Zeitstempel

---

## API

Das Add-on nutzt die offizielle **OEG Kraken GraphQL API**:
`https://api.oeg-kraken.energy/v1/graphql`

Dokumentation: [docs.oeg-kraken.energy](https://docs.oeg-kraken.energy/)

## Changelog

### 0.2.0
- Tarifdaten (Strom & Gas): Arbeitspreis, Grundgebühr, Tarifname, Gültigkeitszeitraum
- Gaskostenzeiten und Gasverbrauch
- Einspeisedaten (PV/Export)
- Kostenberechnung aus Tarif × Verbrauch (Heute, Gestern, Monat)
- 15-Minuten-Intervallverbrauch (Smartmeter)
- Monatliche Verbrauchsübersicht (12 Monate)
- Jahresverbrauch
- Zählerdaten (Seriennummer, MPAN, MPRN, Smartmeter-Status)
- Zahlungshistorie
- PDF-Download-Link der letzten Rechnung
- Anzahl Rechnungen
- 30 HA Sensoren (vorher: 5)

### 0.1.0
- Erstveröffentlichung
