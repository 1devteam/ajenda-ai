#!/bin/bash
# Kill processes on ports 8000 and 8001
# Usage: ./kill_ports.sh

echo "🔍 Checking for processes on ports 8000 and 8001..."

# Check port 8000
PORT_8000=$(sudo lsof -ti:8000)
if [ -n "$PORT_8000" ]; then
    echo "⚠️  Found process on port 8000 (PID: $PORT_8000)"
    sudo kill -9 $PORT_8000
    echo "✅ Killed process on port 8000"
else
    echo "✅ Port 8000 is free"
fi

# Check port 8001
PORT_8001=$(sudo lsof -ti:8001)
if [ -n "$PORT_8001" ]; then
    echo "⚠️  Found process on port 8001 (PID: $PORT_8001)"
    sudo kill -9 $PORT_8001
    echo "✅ Killed process on port 8001"
else
    echo "✅ Port 8001 is free"
fi

echo ""
echo "✨ Done! Ports 8000 and 8001 are now available."
