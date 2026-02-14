#!/bin/bash
# Nanobot monitoring and auto-restart script
# Usage: nohup ./monitor_nanobot.sh &

NANOBOT_CMD="nanobot serve"
CHECK_INTERVAL=60  # Check every 60 seconds
LOG_FILE="/tmp/nanobot_monitor.log"

echo "$(date): Nanobot monitor started" >> "$LOG_FILE"

while true; do
    if ! pgrep -f "$NANOBOT_CMD" > /dev/null; then
        echo "$(date): Nanobot not running, restarting..." >> "$LOG_FILE"

        # Change to nanobot directory if needed
        # cd /path/to/nanobot

        # Start nanobot in background
        nohup $NANOBOT_CMD >> "$LOG_FILE" 2>&1 &

        echo "$(date): Nanobot restarted (PID: $!)" >> "$LOG_FILE"
    fi

    sleep $CHECK_INTERVAL
done
