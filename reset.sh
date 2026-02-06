#!/bin/bash
# Cold start reset: stop services and remove Docker volumes

set -e

PLATFORM_DIR="/home/nvidia/reap/vllm-platform"
cd "$PLATFORM_DIR"

echo "🧊 Cold start reset (stop + remove containers/volumes)"

# Stop python services
pkill -f "python3 main.py" 2>/dev/null || true
pkill -f "streamlit run" 2>/dev/null || true

# Stop and remove containers/volumes
if [ -f docker-compose.yml ]; then
  docker-compose down -v || true
fi

# Optional: prune dangling containers/images (safe)
docker container prune -f >/dev/null 2>&1 || true

echo "✅ Reset complete"
