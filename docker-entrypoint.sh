#!/bin/sh
# Run agent every 15 minutes, output goes to stdout (visible in Coolify logs)
echo "OSINT Agent started. Running every 15 minutes."
while true; do
    echo "--- $(date '+%Y-%m-%d %H:%M:%S') --- running agent ---"
    cd /app && /usr/local/bin/python3 agent.py
    echo "--- $(date '+%Y-%m-%d %H:%M:%S') --- sleeping 15 min ---"
    sleep 900
done
