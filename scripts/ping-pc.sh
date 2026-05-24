#!/bin/bash
# PC Status — check if PC is reachable via ping
# Reads PC_IP_ADDRESS from environment (set via .env / systemd EnvironmentFile)
# Falls back to placeholder if not set

PC_IP="${PC_IP_ADDRESS:-192.168.1.100}"

if [ "$PC_IP" = "192.168.1.100" ] && [ -z "${PC_IP_ADDRESS+x}" ]; then
    echo "❌ PC_IP_ADDRESS not set in .env — update it before using PC control."
    exit 1
fi

if ping -c 1 -W 2 "$PC_IP" &>/dev/null; then
    echo "✅ PC is ON"
else
    echo "❌ PC is OFF (or not reachable)"
fi
