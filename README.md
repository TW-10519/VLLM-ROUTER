# vLLM Multi-DGX Platform

A production-ready API gateway and management system for running multiple vLLM models across multiple DGX machines.

## 🎯 Quick Start

```bash
cd /home/nvidia/reap/vllm-platform
chmod +x deploy.sh
./deploy.sh
```

Then open: `http://localhost:5173` (Admin Web UI)

📖 **New here?** Read [GETTING_STARTED.md](GETTING_STARTED.md) for complete walkthrough!

## ✅ Full-Scale Management Features

The platform provides complete management through a modern React web interface:

- **User Management**: Create, update, disable users
- **API Keys**: Create, update, disable API keys with full visibility
- **Token Quotas**: Daily/monthly limits enforced
- **Rate Limits**: Configurable requests per window
- **Session Management**: Session limits + TTL per API key
- **Usage Analytics**: Track by model and by user
- **Endpoint Testing**: Test vLLM endpoints before registration
- **Gateway Ops**: Start/Stop/Reset Docker stack from UI
- **Configuration**: Edit .env file via UI for cold start setup

**React Admin UI** (port 5173): Full-featured single-page application in `web-ui/` with modern dark theme and real-time updates.

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Client Applications                      │
└────────────────────────────┬────────────────────────────────┘
                             │
                             ▼
                    ┌────────────────┐
                    │  APISIX Gateway│  (Port 9080)
                    │   (Docker)     │
                    └────────┬───────┘
                             │
                             ▼
                    ┌────────────────┐
                    │  Manager API   │  (Port 8001)
                    │   (FastAPI)    │  - Auth
                    │                │  - Routing
                    │   [SQLite DB]  │  - Tracking
                    └────────┬───────┘
                             │
           ┌─────────────────┼─────────────────┐
           ▼                 ▼                 ▼
    ┌──────────┐      ┌──────────┐      ┌──────────┐
    │  vLLM    │      │  vLLM    │      │  vLLM    │
    │ DGX-01   │      │ DGX-02   │      │ Manager  │
    │:8000     │      │:8000     │      │:8000     │
    └──────────┘      └──────────┘      └──────────┘
```

## 📋 Current Setup

- **Manager DGX**: `edgexpert-003f` (172.30.140.142)
  - Runs APISIX Gateway
  - Runs Manager API
  - Can also run a vLLM model
  
- **Worker DGX-01**: `gx10-a55b` (172.30.140.53)
  - Runs vLLM models

## 🚀 Quick Start

### Step 1: Setup Infrastructure

```bash
cd /home/nvidia/reap/vllm-platform
chmod +x setup.sh
./setup.sh
```

This will:
- Start APISIX Gateway (Docker)
- Start etcd, Prometheus, Grafana
- Install Manager API dependencies

### Step 2: Start Manager API

In a new terminal:

```bash
cd /home/nvidia/reap/vllm-platform/manager
python3 main.py
```

The Manager API will start on port 8001.

### Step 3: Initialize Database

In another terminal:

```bash
cd /home/nvidia/reap/vllm-platform/manager
python3 init_db.py
```

This creates:
- Model registrations
- Sample users
- API keys
- APISIX routes

### Step 4: Start vLLM (Optional - for testing)

On this DGX:

```bash
cd /home/nvidia/reap/vllm-platform
chmod +x start_vllm.sh
./start_vllm.sh meta-llama/Llama-2-7b-chat-hf 8000 1
```

Or on the other DGX (gx10-a55b), SSH in and run:

```bash
python3 -m vllm.entrypoints.openai.api_server \
    --model meta-llama/Llama-2-7b-chat-hf \
    --host 0.0.0.0 \
    --port 8000 \
    --tensor-parallel-size 1
```

## 🔑 Using the Platform

### Get Your API Key

After running `init_db.py`, you'll see API keys printed. Example:

```
🔑 API Key: vllm-xxxxxxxxxxxxxxxxxxxxxxxxx
```

### Make Requests

```bash
# Get available models
curl http://localhost:8001/models

# Chat completion request
curl -X POST http://localhost:9080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_KEY" \

### Tool Calling

OpenAI-compatible tool calling is supported. See [TOOL_CALLING.md](TOOL_CALLING.md) for
normalization rules, streaming behavior, debug endpoint usage, and testing checklist.
  -d '{
    "model": "mistral-7b",
    "messages": [
      {"role": "user", "content": "What is machine learning?"}
    ],
    "max_tokens": 100
  }'
```

### From Other Machines on the Network

Replace `localhost` with `172.30.140.142`:

```bash
curl -X POST http://172.30.140.142:9080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -d '{
    "model": "llama-2-7b",
    "messages": [{"role": "user", "content": "Hello!"}]
  }'
```

## 📊 Monitoring

### Prometheus

Access at: `http://localhost:9090`

Metrics available:
- Request counts
- Token usage
- Response times
- Error rates

### Grafana

Access at: `http://localhost:3000`
- Username: `admin`
- Password: `admin`

### Manager API Metrics

```bash
curl http://localhost:8001/metrics
```

## 🛠️ Management

### Add a New Model

```bash
curl -X POST http://localhost:8001/models \
  -H "Content-Type: application/json" \
  -d '{
    "name": "llama-3-8b",
    "backend_host": "dgx-01",
    "backend_port": 8000,
    "description": "Llama 3 8B on DGX-01"
  }'
```

### Create a New User

```bash
curl -X POST http://localhost:8001/users \
  -H "Content-Type: application/json" \
  -d '{
    "username": "newuser",
    "email": "newuser@example.com"
  }'
```

### Generate API Key

```bash
curl -X POST http://localhost:8001/api-keys \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": 1,
    "name": "production_key",
    "max_tokens_per_day": 1000000,
    "max_tokens_per_month": 10000000,
    "rate_limit_per_minute": 500
  }'
```

### View Usage Statistics

```bash
# Overall stats
curl http://localhost:8001/usage/stats

# Stats for specific API key
curl "http://localhost:8001/usage/stats?api_key_value=YOUR_API_KEY"
```

## 🔧 Configuration

### Ports

- **9080**: APISIX Gateway (HTTP)
- **9443**: APISIX Gateway (HTTPS)
- **9180**: APISIX Admin API
- **8001**: Manager API
- **8000**: vLLM servers
- **9090**: Prometheus
- **3000**: Grafana
- **2379**: etcd

### Admin Key

APISIX Admin API key: `vllm-platform-admin-key-2026`

Access admin API:

```bash
curl -H "X-API-KEY: vllm-platform-admin-key-2026" \
  http://localhost:9180/apisix/admin/routes
```

## 📁 Project Structure

```
vllm-platform/
├── docker-compose.yml          # Infrastructure services
├── apisix_conf/
│   └── config.yaml             # APISIX configuration
├── prometheus.yml              # Prometheus config
├── manager/
│   ├── main.py                 # Manager API
│   ├── init_db.py              # Database initialization
│   ├── requirements.txt        # Python dependencies
│   └── vllm_platform.db        # SQLite database (created)
├── setup.sh                    # Setup script
└── start_vllm.sh              # vLLM startup script
```

## 🐛 Troubleshooting

### Check Service Status

```bash
cd /home/nvidia/reap/vllm-platform
docker-compose ps
```

### View Logs

```bash
# APISIX logs
docker-compose logs -f apisix

# All services
docker-compose logs -f
```

### Restart Services

```bash
docker-compose restart
```

### Check vLLM is Accessible

```bash
curl http://localhost:8000/v1/models
```

### Test Manager API

```bash
curl http://localhost:8001/health
```

### Verify APISIX Routes

```bash
curl -H "X-API-KEY: vllm-platform-admin-key-2026" \
  http://localhost:9180/apisix/admin/routes
```

## 🚧 Next Steps

### Phase 2 Features (To Be Implemented)

1. **Admin UI** - React + Vite web interface (port 5173)
2. **Advanced Routing** - Load balancing, fallback models
3. **Caching** - Redis-based response caching
4. **Logging** - Centralized request logging
5. **Alerts** - Prometheus alerting rules
6. **HTTPS** - SSL/TLS configuration
7. **Authentication** - JWT tokens, OAuth

## 📚 API Documentation

Full API documentation available at: `http://localhost:8001/docs` (FastAPI auto-generated)

## 🔒 Security Notes

- Change default admin passwords in production
- Use HTTPS for external access
- Rotate API keys regularly
- Set appropriate token limits
- Monitor for suspicious activity
- Keep vLLM endpoints on internal network only

## 📞 Support

For issues or questions:
1. Check logs: `docker-compose logs -f`
2. Verify connectivity: `ping dgx-01`
3. Test individual services: `curl http://localhost:8001/health`
