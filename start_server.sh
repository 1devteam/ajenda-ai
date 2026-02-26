#!/bin/bash
# Start Omnipath V2 Server
# Usage: ./start_server.sh

echo "🚀 Starting Omnipath V2 Server..."
echo ""

# Check if we're in the right directory
if [ ! -f "backend/main.py" ]; then
    echo "❌ Error: backend/main.py not found"
    echo "   Please run this script from the omnipath_v2 directory"
    exit 1
fi

# Check if virtual environment exists
if [ ! -d "venv_clean" ]; then
    echo "⚠️  Warning: venv_clean not found"
    echo "   Using system Python"
else
    echo "✅ Activating virtual environment..."
    source venv_clean/bin/activate
fi

# Check if .env file exists
if [ ! -f ".env" ]; then
    echo "⚠️  Warning: .env file not found"
    echo "   Server may not work correctly without API keys"
fi

# Kill any existing processes on port 8000
PORT_8000=$(sudo lsof -ti:8000 2>/dev/null)
if [ -n "$PORT_8000" ]; then
    echo "⚠️  Port 8000 is in use (PID: $PORT_8000)"
    echo "   Killing existing process..."
    sudo kill -9 $PORT_8000
    sleep 1
fi

echo ""
echo "🌟 Starting FastAPI server on http://0.0.0.0:8000"
echo "📚 API Docs: http://localhost:8000/docs"
echo "📊 Jaeger UI: http://localhost:16686"
echo "📈 Prometheus: http://localhost:9090"
echo ""
echo "Press CTRL+C to stop the server"
echo ""

# Start the server
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
