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
| `octopus_energy/bills/count` | Anzahl Rechnungen (letzte 2 Jahre) |
| `octopus_energy/bills/all` | Alle Rechnungen als JSON |
| `octopus_energy/bills/latest/gross_total` | Letzte Rechnung Brutto EUR |
| `octopus_energy/bills/latest/net_total` | Letzte Rechnung Netto EUR |
| `octopus_energy/bills/latest/tax_total` | Letzte Rechnung MwSt EUR |
| `octopus_energy/bills/latest/issued_date` | Rechnungsdatum |
| `octopus_energy/bills/latest/from_date` | Abrechnungszeitraum Von |
| `octopus_energy/bills/latest/to_date` | Abrechnungszeitraum Bis |
| `octopus_energy/bills/latest/pdf_url` | Temporärer PDF-Download-Link |
| `octopus_energy/bills/YYYY-MM/gross_total` | Brutto EUR (je Monat) |
| `octopus_energy/bills/YYYY-MM/net_total` | Netto EUR (je Monat) |
| `octopus_energy/bills/YYYY-MM/tax_total` | MwSt EUR (je Monat) |
| `octopus_energy/bills/YYYY-MM/issued_date` | Rechnungsdatum (je Monat) |
| `octopus_energy/bills/YYYY-MM/from_date` | Zeitraum Von (je Monat) |
| `octopus_energy/bills/YYYY-MM/to_date` | Zeitraum Bis (je Monat) |
| `octopus_energy/bills/YYYY-MM/pdf_url` | PDF-Link (je Monat) |
| `octopus_energy/bills/YYYY-MM/transactions` | Einzelposten JSON (je Monat) |

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

### 0.5.12
- Bugfix: `bills/latest/pdf_url` und `bills/YYYY-MM/pdf_url` jetzt als JSON `{"url": "...", "filename": "..."}` — behebt „state exceeds maximum allowed length (255)" Fehler. Sensor-State zeigt nun den kurzen Dateinamen, die vollständige URL ist als Attribut abrufbar

### 0.5.11
- Bugfix: `bills/all` Payload drastisch verkleinert — `temporaryUrl` (lange S3-URL) und `transactions` werden nicht mehr im Aggregat-Topic mitgesendet (sind bereits in `bills/YYYY-MM/*` verfügbar) — behebt HA-Recorder-Fehler „State attributes exceed maximum size of 16384 bytes"

### 0.5.10
- Bugfix: `bills/all` JSON-Key von `"items"` auf `"bills"` umbenannt — verhindert `TypeError: object of type 'builtin_function_or_method' has no len()` im HA-Sensor-Template (Jinja2 behandelt `.items` als Python-Dict-Methode statt als JSON-Key)

### 0.5.9
- `build.yaml` entfernt (deprecated) — Default-Base-Image direkt ins Dockerfile verschoben

### 0.5.8
- Deprecated Architekturen `armhf`, `armv7`, `i386` aus `config.yaml` und `build.yaml` entfernt — bereinigt Supervisor-Warnungen

### 0.5.7
- Bugfix: `build.yaml` hinzugefügt — behebt Docker-Build-Fehler beim "Neu aufbauen" (`BUILD_FROM` war leer)

### 0.5.6
- Bugfix: `last_updated` Timestamp jetzt mit Timezone-Info (`+02:00`) statt naivem Datum — behebt `unknown` Status des Timestamp-Sensors in HA

### 0.5.5
- MQTT Reconnect-Logik: Bei Verbindungsverlust wird sofort ein Neuabruf ausgelöst statt auf den 60-Minuten-Zyklus zu warten
- Sensoren bleiben nach MQTT-Broker-Neustart nicht mehr auf `unknown`

### 0.5.4
- 24 individuelle MQTT-Sensoren für monatlichen Verbrauch (letztes + aktuelles Jahr)
- Basis für zuverlässige Plotly-Balkendiagramme ohne fn-Hacks
- Topic: `consumption/monthly/YYYY-MM`

### 0.5.3
- Neuer Sensor `Octopus Monatsverbrauch` mit kWh + Kosten für alle Monate der letzten 2 Jahre
- Basis für Jahresvergleich-Karten im Dashboard
- 32 HA Sensoren (vorher: 31)

### 0.5.2
- Neuer Sensor `Octopus Alle Rechnungen` mit allen Rechnungen als JSON-Attribute
- Dashboard-Karte mit klickbaren PDF-Download-Links für alle Rechnungen der letzten 2 Jahre
- `bills/all` Topic jetzt als `{"items": [...]}` Objekt für HA JSON-Attribute

### 0.5.1
- Rechnungen der letzten 2 Jahre als eigene MQTT-Topics pro Monat (`bills/YYYY-MM/...`)
- Jede Rechnung veröffentlicht: Brutto/Netto/MwSt, Zeitraum, PDF-Link, Einzelposten
- Abruf auf 30 Rechnungen erhöht

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
