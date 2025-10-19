#!/bin/bash
# Restart script for viewshed server

# Kill all viewshed_server.py processes
pkill -f "python.*viewshed_server.py"

# Wait for processes to exit (up to 5 seconds)
for i in {1..10}; do
    if ! pgrep -f "python.*viewshed_server.py" > /dev/null; then
        break
    fi
    sleep 0.5
done

# Force kill any remaining processes
if pgrep -f "python.*viewshed_server.py" > /dev/null; then
    echo "Forcing kill of remaining processes..."
    pkill -9 -f "python.*viewshed_server.py"
    sleep 1
fi

# Activate virtual environment and start server
cd "$(dirname "$0")"
source ../../viewshed-test/venv/bin/activate
python viewshed_server.py
