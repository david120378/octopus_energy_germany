#!/usr/bin/with-contenv bashio

export EMAIL=$(bashio::config 'email')
export PASSWORD=$(bashio::config 'password')
export ACCOUNT_NUMBER=$(bashio::config 'account_number')
export MQTT_HOST=$(bashio::config 'mqtt_host')
export MQTT_PORT=$(bashio::config 'mqtt_port')
export MQTT_USER=$(bashio::config 'mqtt_user')
export MQTT_PASSWORD=$(bashio::config 'mqtt_password')
export MQTT_TOPIC_PREFIX=$(bashio::config 'mqtt_topic_prefix')
export FETCH_INTERVAL=$(bashio::config 'fetch_interval_minutes')

bashio::log.info "Starte Octopus Energy Deutschland Add-on..."

python3 /app/octopus_energy.py
