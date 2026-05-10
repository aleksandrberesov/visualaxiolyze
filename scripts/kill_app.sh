#!/bin/bash

echo "Searching for application processes..."

# Find and kill main python process
MAIN_PIDS=$(pgrep -f "python bridge_layer/main.py")
if [ -n "$MAIN_PIDS" ]; then
    echo "Killing main app processes: $MAIN_PIDS"
    kill -9 $MAIN_PIDS
fi

# Find and kill any reflex processes
REFLEX_PIDS=$(pgrep -f "reflex")
if [ -n "$REFLEX_PIDS" ]; then
    echo "Killing reflex processes: $REFLEX_PIDS"
    kill -9 $REFLEX_PIDS
fi

echo "Done."
