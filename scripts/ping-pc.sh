#!/bin/bash
# PC Status — check if PC is reachable via ping
# Configure PC_IP below for your desktop

PC_IP="192.168.1.100"

if ping -c 1 -W 2 "$PC_IP" &>/dev/null; then
    echo "✅ PC is ON"
else
    echo "❌ PC is OFF (or not reachable)"
fi
