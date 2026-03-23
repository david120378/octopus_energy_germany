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

Die Kontonummer findet sich im Octopus Energy Kundenportal unter **Mein Konto**.
Format: `A-XXXX1234`

## MQTT Topics

| Topic | Beschreibung |
|-------|-------------|
| `octopus_energy/account/balance` | Kontostand in EUR |
| `octopus_energy/account/overdue_balance` | Überfälliger Betrag in EUR |
| `octopus_energy/account/details` | Vollständige Kontodaten (JSON) |
| `octopus_energy/bills/all` | Alle Rechnungen (JSON) |
| `octopus_energy/bills/latest/gross_total` | Letzte Rechnung Bruttobetrag EUR |
| `octopus_energy/bills/latest/issued_date` | Datum der letzten Rechnung |
| `octopus_energy/consumption/today` | Verbrauch heute in kWh |
| `octopus_energy/consumption/yesterday` | Verbrauch gestern in kWh |
| `octopus_energy/consumption/last_30_days` | Verbrauch letzte 30 Tage (JSON) |
| `octopus_energy/last_updated` | Zeitstempel des letzten Abrufs |

## Home Assistant Sensoren

Das Add-on registriert automatisch folgende Sensoren via MQTT Discovery:

- **Octopus Kontostand** (EUR)
- **Octopus Überfälliger Betrag** (EUR)
- **Octopus Letzte Rechnung (Brutto)** (EUR)
- **Octopus Letzte Rechnung Datum**
- **Octopus Verbrauch Heute** (kWh)

## API

Das Add-on nutzt die offizielle **OEG Kraken GraphQL API**:
`https://api.oeg-kraken.energy/v1/graphql`

Dokumentation: [docs.oeg-kraken.energy](https://docs.oeg-kraken.energy/)
