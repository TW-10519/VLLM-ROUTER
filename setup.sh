#!/bin/bash
# Initialize the vLLM Multi-DGX Platform

set -e

echo "=== vLLM Multi-DGX Platform Setup ==="
echo ""

# Check Docker
if ! command -v docker &> /dev/null; then
    echo "❌ Docker is not installed. Please install Docker first."
    exit 1
fi

echo "✅ Docker is installed"

# Check Docker Compose
if ! command -v docker-compose &> /dev/null; then
    echo "❌ Docker Compose is not installed. Please install Docker Compose first."
    exit 1
fi

echo "✅ Docker Compose is installed"

# Create directory structure
echo ""
echo "Creating directory structure..."
cd /home/nvidia/reap/vllm-platform

# Stop any existing containers
echo ""
echo "Stopping any existing containers..."
docker-compose down 2>/dev/null || true

# Start infrastructure
echo ""
echo "Starting APISIX, etcd, Prometheus, and Grafana..."
docker-compose up -d

echo ""
echo "Waiting for services to be ready..."
sleep 10

# Check if APISIX is ready
echo ""
echo "Checking APISIX status..."
if curl -s http://localhost:9080 > /dev/null; then
    echo "✅ APISIX Gateway is running on port 9080"
else
    echo "❌ APISIX failed to start"
    exit 1
fi

# Check Admin API
if curl -s -H "X-API-KEY: vllm-platform-admin-key-2026" http://localhost:9180/apisix/admin/routes > /dev/null; then
    echo "✅ APISIX Admin API is accessible on port 9180"
else
    echo "❌ APISIX Admin API is not accessible"
    exit 1
fi

# Install Python dependencies for Manager API
echo ""
echo "Installing Manager API dependencies..."
cd /home/nvidia/reap/vllm-platform/manager
pip3 install -q -r requirements.txt

echo ""
echo "✅ Setup complete!"
echo ""
echo "=== Next Steps ==="
echo ""
echo "1. Start the Manager API:"
echo "   cd /home/nvidia/reap/vllm-platform/manager"
echo "   python3 main.py"
echo ""
echo "2. Initialize the database with models and API keys:"
echo "   python3 init_db.py"
echo ""
echo "3. Access the services:"
echo "   - APISIX Gateway: http://localhost:9080"
echo "   - Manager API: http://localhost:8001"
echo "   - Prometheus: http://localhost:9090"
echo "   - Grafana: http://localhost:3000 (admin/admin)"
echo ""
echo "4. Start vLLM on this DGX:"
echo "   See vllm_startup.sh for instructions"
echo ""
