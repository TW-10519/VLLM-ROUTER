# Quick Start - Setup & Deploy

Complete guide to set up and run the vLLM Multi-DGX Platform from scratch.

## 🚀 Fastest Start (2 commands)

```bash
cd /home/nvidia/reap/vllm-platform

# Create clean Python environment and install everything
cd manager && rm -rf venv && python3 -m venv venv && source venv/bin/activate && pip install -q --upgrade pip && pip install -q -r requirements.txt && deactivate && cd ..

# Install web UI packages
cd web-ui && rm -rf node_modules && npm install > /dev/null 2>&1 && cd ..

# Deploy everything
./deploy.sh
```

Then open: **http://localhost:5173**

---

## Step-by-Step Setup

### Step 1: Create Manager API Virtual Environment

```bash
cd /home/nvidia/reap/vllm-platform/manager

# Remove old environment
rm -rf venv

# Create and activate
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Verify
python3 -c "import fastapi; print('✅ FastAPI installed')"
```

### Step 2: Create Web UI Environment

In a new terminal:

```bash
cd /home/nvidia/reap/vllm-platform/web-ui

# Clean install
rm -rf node_modules package-lock.json
npm install
```

### Step 3: Deploy Everything

```bash
cd /home/nvidia/reap/vllm-platform
chmod +x deploy.sh stop.sh
./deploy.sh
```

Wait for completion. Should see URLs like:
```
📊 Services Running:
   • APISIX Gateway:      http://localhost:9080
   • Manager API:         http://localhost:8001
   • Admin Web UI:        http://localhost:5173
```

### Step 4: Open Admin UI

Open in browser: **http://localhost:5173**

---

## Using the Admin UI

### Register vLLM Instance

1. **Start vLLM somewhere** (local or on dgx-01):
   ```bash
   # Local: on this DGX
   python3 -m vllm.entrypoints.openai.api_server --port 8000
   ```

2. **In Admin UI:**
   - Go to "Models" tab
   - Enter host (e.g., `localhost` or `dgx-01`) and port `8000`
   - Click "Test Endpoint"
   - Click "Register"

### Create API Key with Limits

1. Go to "Users" tab → Create user
2. Go to "API Keys" tab → Create key
3. Set limits:
   - Tokens/day: 100000
   - Tokens/month: 1000000
   - Rate limit: 100 req/min
   - Max sessions: 5

### Test Gateway

1. Go to "Test Gateway" tab
2. Select API key and model
3. Enter a message
4. Send request
5. See response with token counts

### Monitor Usage

Go to "Usage" tab to see:
- Tokens used by model
- Tokens used by user
- Request trends

---

## Service Ports

| Service | Port | URL |
|---------|------|-----|
| **Admin Web UI** | 5173 | http://localhost:5173 |
| Manager API | 8001 | http://localhost:8001 |
| APISIX Gateway | 9080 | http://localhost:9080 |
| Prometheus | 9090 | http://localhost:9090 |
| Grafana | 3000 | http://localhost:3000 |

---

## Making API Calls

### From Command Line

```bash
API_KEY="your-api-key"
curl -X POST http://localhost:9080/v1/chat/completions \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "llama-2-7b",
    "messages": [{"role": "user", "content": "Hello!"}],
    "max_tokens": 50
  }'
```

### From Python

```python
import requests

response = requests.post(
    "http://localhost:9080/v1/chat/completions",
    headers={"Authorization": "Bearer YOUR_API_KEY"},
    json={
        "model": "llama-2-7b",
        "messages": [{"role": "user", "content": "Hello!"}],
        "max_tokens": 50
    }
)
print(response.json())
```

---

## Common Tasks

### Stop Everything

```bash
./stop.sh
```

### Restart

```bash
./stop.sh
sleep 3
./deploy.sh
```

### Full Reset

```bash
./stop.sh
rm -rf manager/venv web-ui/node_modules
rm manager/vllm_platform.db
# Then run setup and deploy again
```

### Check Services

```bash
./status.sh

# Or manually
curl http://localhost:8001/health      # Manager
curl http://localhost:5173             # Web UI
curl http://localhost:9080             # Gateway
```

### View Logs

```bash
tail -f logs/manager.log
tail -f logs/web-ui.log
docker-compose logs -f
```

---

## Troubleshooting

### Port already in use

```bash
sudo lsof -i :8001
pkill -f "python3 main.py"
```

### venv issues

```bash
cd manager
rm -rf venv
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### npm issues

```bash
cd web-ui
rm -rf node_modules package-lock.json
npm install
```

### Docker won't start

```bash
docker-compose down
docker-compose up -d
sleep 15
./status.sh
```

### Can't reach vLLM

```bash
# Test connection directly
curl http://dgx-01:8000/v1/models

# Or check if running locally
ps aux | grep vllm
```

---

## Next Steps

1. ✅ Deploy (done with `./deploy.sh`)
2. ✅ Register vLLM instances
3. ✅ Create users and API keys with limits
4. ✅ Test through gateway
5. ✅ Monitor usage in Admin UI
6. ✅ Set up monitoring (Prometheus/Grafana)

For full details, see [README.md](README.md)

---

**Start now:**
```bash
cd /home/nvidia/reap/vllm-platform && ./deploy.sh
```

Open: **http://localhost:5173**
