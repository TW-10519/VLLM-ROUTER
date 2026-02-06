#!/bin/bash
# Check status of all vLLM Platform services

echo "╔═══════════════════════════════════════════════════════╗"
echo "║          vLLM Platform - Service Status              ║"
echo "╚═══════════════════════════════════════════════════════╝"
echo ""

# Check Docker containers
echo "🐳 Docker Services:"
docker-compose ps
echo ""

# Check Manager API
echo "🔧 Manager API (port 8001):"
if curl -s http://localhost:8001/health > /dev/null; then
    echo "   ✅ Running"
    MANAGER_PID=$(pgrep -f "python3 main.py" | head -1)
    if [ ! -z "$MANAGER_PID" ]; then
        echo "   PID: $MANAGER_PID"
    fi
else
    echo "   ❌ Not running"
fi
echo ""

# Check Admin UI
echo "🎨 Admin Web UI (port 5173):"
if curl -s http://localhost:5173 > /dev/null; then
    echo "   ✅ Running"
    WEB_UI_PID=$(pgrep -f "vite" | head -1)
    if [ ! -z "$WEB_UI_PID" ]; then
        echo "   PID: $WEB_UI_PID"
    fi
else
    echo "   ❌ Not running"
fi
echo ""

# Check APISIX
echo "🌐 APISIX Gateway (port 9080):"
if curl -s http://localhost:9080 > /dev/null; then
    echo "   ✅ Running"
else
    echo "   ❌ Not running"
fi
echo ""

# Check Prometheus
echo "📊 Prometheus (port 9090):"
if curl -s http://localhost:9090 > /dev/null; then
    echo "   ✅ Running"
else
    echo "   ❌ Not running"
fi
echo ""

# Check Grafana
echo "📈 Grafana (port 3001):"
if curl -s http://localhost:3001 > /dev/null; then
    echo "   ✅ Running"
else
    echo "   ❌ Not running"
fi
echo ""

# Quick stats
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

if curl -s http://localhost:8001/models > /dev/null; then
    MODELS=$(curl -s http://localhost:8001/models | python3 -c "import sys, json; print(len(json.load(sys.stdin)))" 2>/dev/null || echo "0")
    USERS=$(curl -s http://localhost:8001/users | python3 -c "import sys, json; print(len(json.load(sys.stdin)))" 2>/dev/null || echo "0")
    KEYS=$(curl -s http://localhost:8001/api-keys | python3 -c "import sys, json; print(len(json.load(sys.stdin)))" 2>/dev/null || echo "0")
    
    echo "📊 Platform Stats:"
    echo "   • Registered Models: $MODELS"
    echo "   • Users: $USERS"
    echo "   • API Keys: $KEYS"
    echo ""
fi

echo "🔗 Access URLs:"
echo "   • Admin UI:   http://localhost:5173"
echo "   • Manager:    http://localhost:8001/docs"
echo "   • Gateway:    http://localhost:9080"
echo "   • Prometheus: http://localhost:9090"
echo "   • Grafana:    http://localhost:3001"
echo ""
