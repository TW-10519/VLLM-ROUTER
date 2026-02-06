#!/bin/bash
# Deploy the complete vLLM Platform

set -e

PLATFORM_DIR="/home/nvidia/reap/vllm-platform"
cd "$PLATFORM_DIR"

echo "╔═══════════════════════════════════════════════════════╗"
echo "║     vLLM Multi-DGX Platform - Complete Deployment    ║"
echo "╚═══════════════════════════════════════════════════════╝"
echo ""

# Check prerequisites
echo "📋 Checking prerequisites..."
echo ""

if ! command -v docker &> /dev/null; then
    echo "❌ Docker not found. Please install Docker first."
    exit 1
fi
echo "✅ Docker: $(docker --version | cut -d' ' -f3)"

if ! command -v docker-compose &> /dev/null; then
    echo "❌ Docker Compose not found. Please install Docker Compose first."
    exit 1
fi
echo "✅ Docker Compose: $(docker-compose --version | cut -d' ' -f4)"

if ! command -v python3 &> /dev/null; then
    echo "❌ Python3 not found. Please install Python3 first."
    exit 1
fi
echo "✅ Python3: $(python3 --version | cut -d' ' -f2)"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Step 1: Infrastructure
echo "🐳 Step 1/5: Starting infrastructure (APISIX, etcd, Prometheus, Grafana)..."
echo ""

docker-compose down 2>/dev/null || true
docker-compose up -d

echo ""
echo "⏳ Waiting for services to initialize..."
sleep 15

# Check APISIX
if curl -s http://localhost:9080 > /dev/null; then
    echo "✅ APISIX Gateway started (port 9080)"
else
    echo "❌ APISIX failed to start"
    exit 1
fi

# Check Admin API
if curl -s -H "X-API-KEY: vllm-platform-admin-key-2026" http://localhost:9180/apisix/admin/routes > /dev/null; then
    echo "✅ APISIX Admin API accessible (port 9180)"
else
    echo "❌ APISIX Admin API not accessible"
    exit 1
fi

echo "✅ Prometheus started (port 9090)"
echo "✅ Grafana started (port 3000)"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Step 2: Manager API Dependencies
echo "📦 Step 2/5: Installing Manager API dependencies..."
echo ""

cd manager
if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo "✅ Created virtual environment"
fi

source venv/bin/activate
pip install -q --upgrade pip
pip install -q -r requirements.txt
echo "✅ Dependencies installed"

cd ..

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Step 3: Web UI Dependencies
echo "🎨 Step 3/5: Installing Web UI dependencies..."
echo ""

cd web-ui
if [ ! -d "node_modules" ]; then
    npm install
    echo "✅ Web UI dependencies installed"
else
    echo "✅ Web UI dependencies already installed"
fi

cd ..

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Step 4: Start Manager API
echo "🚀 Step 4/5: Starting Manager API..."
echo ""

cd manager
source venv/bin/activate

# Kill any existing manager process
pkill -f "python3 main.py" 2>/dev/null || true
sleep 2

# Kill anything bound to port 8001
if command -v lsof &> /dev/null; then
    lsof -t -i:8001 | xargs -r kill -9 2>/dev/null || true
fi

nohup python3 main.py > ../logs/manager.log 2>&1 &
MANAGER_PID=$!

echo "⏳ Waiting for Manager API to start..."
for i in {1..30}; do
    if curl -s http://localhost:8001/health > /dev/null; then
        echo "✅ Manager API started (PID: $MANAGER_PID, port 8001)"
        break
    fi
    sleep 1
done

if ! curl -s http://localhost:8001/health > /dev/null; then
    echo "❌ Manager API failed to start. Check logs: logs/manager.log"
    exit 1
fi

cd ..

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Step 5: Start Web UI
echo "🎨 Step 5/5: Starting React Web UI..."
echo ""

cd web-ui

# Kill any existing vite process
pkill -f "vite" 2>/dev/null || true
sleep 2

nohup npm run dev > ../logs/web-ui.log 2>&1 &
WEB_UI_PID=$!

echo "⏳ Waiting for Web UI to start..."
sleep 5

if curl -s http://localhost:5173 > /dev/null; then
    echo "✅ Web UI started (PID: $WEB_UI_PID, port 5173)"
else
    echo "⚠️  Web UI may still be starting..."
fi

cd ..

echo ""
echo "╔═══════════════════════════════════════════════════════╗"
echo "║              🎉  DEPLOYMENT COMPLETE!  🎉             ║"
echo "╚═══════════════════════════════════════════════════════╝"
echo ""
echo "📊 Services Running:"
echo "   • APISIX Gateway:      http://localhost:9080"
echo "   • Manager API:         http://localhost:8001"
echo "   • Admin Web UI:        http://localhost:5173"
echo "   • Prometheus:          http://localhost:9090"
echo "   • Grafana:             http://localhost:3000 (admin/admin)"
echo ""
echo "📱 Access from network:"
echo "   • Gateway:   http://172.30.140.142:9080"
echo "   • Admin UI:  http://172.30.140.142:5173"
echo ""
echo "🔧 Process IDs:"
echo "   • Manager API: $MANAGER_PID"
echo "   • Web UI:      $WEB_UI_PID"
echo ""
echo "📝 Logs:"
echo "   • Manager:    tail -f logs/manager.log"
echo "   • Web UI:     tail -f logs/web-ui.log"
echo "   • APISIX:     docker-compose logs -f apisix"
echo ""
echo "🎯 Next Steps:"
echo "   1. Open Admin UI: http://localhost:5173"
echo "   2. Register your vLLM instances (test before registering)"
echo "   3. Create users and API keys"
echo "   4. Start testing!"
echo ""
echo "🛑 To stop all services:"
echo "   ./stop.sh"
echo ""
