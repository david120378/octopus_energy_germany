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
| `octopus_energy/account/details` | Vollständige Kontodaten (JSON) |

### Verbrauch (kWh)
| Topic | Beschreibung |
|-------|-------------|
| `octopus_energy/consumption/today` | Stromverbrauch heute (kWh) |
| `octopus_energy/consumption/yesterday` | Stromverbrauch gestern (kWh) |
| `octopus_energy/consumption/current_week` | Stromverbrauch aktuelle Woche (kWh) |
| `octopus_energy/consumption/last_week` | Stromverbrauch letzte Woche (kWh) |
| `octopus_energy/consumption/current_month` | Stromverbrauch aktueller Monat (kWh) |
| `octopus_energy/consumption/last_month` | Stromverbrauch letzter Monat (kWh) |
| `octopus_energy/consumption/current_year` | Stromverbrauch aktuelles Jahr (kWh) |
| `octopus_energy/consumption/last_year` | Stromverbrauch letztes Jahr (kWh) |

### Kosten (EUR inkl. MwSt)
| Topic | Beschreibung |
|-------|-------------|
| `octopus_energy/cost/today` | Stromkosten heute (EUR) |
| `octopus_energy/cost/yesterday` | Stromkosten gestern (EUR) |
| `octopus_energy/cost/current_week` | Stromkosten aktuelle Woche (EUR) |
| `octopus_energy/cost/last_week` | Stromkosten letzte Woche (EUR) |
| `octopus_energy/cost/current_month` | Stromkosten aktueller Monat (EUR) |
| `octopus_energy/cost/last_month` | Stromkosten letzter Monat (EUR) |
| `octopus_energy/cost/current_year` | Stromkosten aktuelles Jahr (EUR) |
| `octopus_energy/cost/last_year` | Stromkosten letztes Jahr (EUR) |
| `octopus_energy/tariff/unit_rate` | Arbeitspreis (EUR/kWh, aus Verbrauchsdaten berechnet) |

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

### Zahlungen
| Topic | Beschreibung |
|-------|-------------|
| `octopus_energy/payments/latest/amount` | Letzte Zahlung (EUR) |
| `octopus_energy/payments/latest/date` | Datum der letzten Zahlung |
| `octopus_energy/payments/latest/type` | Art der Zahlung |
| `octopus_energy/payments/all` | Alle Zahlungen (JSON) |

---

## Home Assistant Sensoren (MQTT Discovery)

Das Add-on registriert automatisch **28 Sensoren** in Home Assistant:

- Konto: Kontostand, Überfälliger Betrag
- Verbrauch: Heute/Gestern/Aktuelle Woche/Letzte Woche/Aktueller Monat/Letzter Monat/Aktuelles Jahr/Letztes Jahr (kWh)
- Kosten: Heute/Gestern/Aktuelle Woche/Letzte Woche/Aktueller Monat/Letzter Monat/Aktuelles Jahr/Letztes Jahr (EUR inkl. MwSt)
- Tarif: Arbeitspreis (EUR/kWh)
- Rechnungen: Brutto/Netto, Datum (Von/Bis), Anzahl, PDF-Link
- Zahlungen: Letzter Betrag & Datum
- Letzter Abruf Zeitstempel

---

## API

Das Add-on nutzt die offizielle **OEG Kraken GraphQL API**:
`https://api.oeg-kraken.energy/v1/graphql`

Dokumentation: [docs.oeg-kraken.energy](https://docs.oeg-kraken.energy/)

## Changelog

### 0.5.0
- Verbrauch & Kosten für alle Zeiträume: Tag, Woche, Monat, Jahr (jeweils aktuell + vorherig)
- Arbeitspreis-Sensor (EUR/kWh, aus Tagesverbrauch berechnet)
- Datenabruf jetzt 400 Tage (für vollständige Jahresauswertung)
- 28 HA Sensoren (vorher: 20)

### 0.4.0
- Verbrauchsdaten via `property(id) { measurements(...) }` GraphQL-Endpoint
- Neue MQTT-Topics: Verbrauch heute/gestern/aktueller Monat/letzter Monat (kWh)
- Neue MQTT-Topics: Kosten heute/gestern/aktueller Monat/letzter Monat (EUR inkl. MwSt)
- Property-ID wird einmalig aus Account-Query gecacht
- 20 HA Sensoren (vorher: 12)

### 0.3.0
- Stabile Version: Verbrauchsdaten entfernt (kein zugänglicher Pfad im deutschen OEG-Schema)
- Funktioniert vollständig: Kontostand, Rechnungen (inkl. PDF-Link), Zahlungen
- 12 HA Sensoren

### 0.2.9
- Bugfix: consumption direkt auf account.electricityMalos-Ebene (mit maloId)

### 0.2.8
- Bugfix: `transactions(first: 50)` Pagination in Bills-Query
- Bugfix: `consumption` auf `properties`-Ebene verschoben (nicht auf MaLo)

### 0.2.7
- Bugfix: `consumption` direkt auf `electricityMalos` (nicht auf `meter`)
- Bugfix: `bills(first: 10)` Pagination hinzugefügt
- Meter-Info-Query entfernt (Felder nicht im deutschen Schema verfügbar)

### 0.2.6
- Gas komplett entfernt (Queries, Sensoren, MQTT Topics, Parsing)

### 0.2.5
- Bugfix: `meters` → `meter` (Singular) auf MaLo-Typ
- Bugfix: `marketLocationId` entfernt (existiert nicht auf MaLo)
- Bugfix: Payments-Query mit `first: 20` Pagination
- Bugfix: `isCredit` / `isExport` aus Bill-Transaktionen entfernt

### 0.2.4
- Bugfix: Deutsche API-Feldnamen korrigiert (von UK-Schema auf OEG-Schema)
  - `electricityMeterPoints` → `electricityMalos`
  - `gasMeterPoints` → `gasMalos`
  - `electricityAgreements` / `gasAgreements` entfernt (nicht im deutschen Schema)
  - `postedDate` → `paymentDate` bei Zahlungen
  - Bills-Query mit `... on InvoiceType` / `... on StatementType` Inline-Fragmenten
  - `HalfHourlyTariff` / `StandardTariff` entfernt (unbekannte Typen im deutschen Schema)

### 0.2.3
- Bugfix: Trailing Slash in GraphQL-URL (`/graphql/`) — verhindert Redirect-Verlust des POST-Body

### 0.2.2
- Bugfix: 400-Fehler behoben durch vereinfachte Token-Query (nur `token` statt `refreshToken`)
- Bugfix: Jede Query-Gruppe einzeln abgesichert — Fehler in einer Gruppe blockiert nicht die anderen
- Verbessertes Error-Logging: API-Antworttext wird bei Fehler geloggt
- Gas-Tarif, Zahlungen und Zählerdaten als separate Queries (robuster gegen fehlende Felder)
- Authentifizierung einmalig am Anfang des Abrufzyklus

### 0.2.1
- Bugfix: Dockerfile `--break-system-packages` für Alpine Linux pip-Kompatibilität

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
