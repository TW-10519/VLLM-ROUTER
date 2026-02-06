#!/bin/bash
# Stop all vLLM Platform services

PLATFORM_DIR="/home/nvidia/reap/vllm-platform"
cd "$PLATFORM_DIR"

echo "🛑 Stopping vLLM Platform..."
echo ""

# Stop Manager API
echo "Stopping Manager API..."
pkill -f "python3 main.py" 2>/dev/null || true
pkill -f "uvicorn" 2>/dev/null || true
if command -v ss &> /dev/null; then
	ss -ltnp 2>/dev/null | awk '/:8001/ {print $7}' | sed -n 's/.*pid=\([0-9]*\).*/\1/p' | xargs -r kill -9 2>/dev/null || true
elif command -v lsof &> /dev/null; then
	timeout 2 lsof -t -i:8001 2>/dev/null | xargs -r kill -9 2>/dev/null || true
fi
echo "✅ Manager API stopped"

# Stop Web UI
echo "Stopping Web UI..."
pkill -f "vite" 2>/dev/null || true
echo "✅ Web UI stopped"

# Stop Docker containers
echo "Stopping Docker services..."
docker-compose down
echo "✅ Docker services stopped"

echo ""
echo "✅ All services stopped"
