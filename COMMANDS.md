# vLLM Platform - Command Reference

## Quick Commands

### Deployment
```bash
./deploy.sh          # Deploy entire platform
./stop.sh            # Stop all services
./status.sh          # Check service status
./reset.sh           # Cold reset (stop + remove docker volumes)
```

### Testing
```bash
python3 test_platform.py      # Run test suite
./start_vllm.sh               # Start local vLLM for testing
```

### Monitoring
```bash
# View logs
tail -f logs/manager.log      # Manager API logs
tail -f logs/dashboard.log    # Dashboard logs
docker-compose logs -f apisix # APISIX logs

# Check processes
ps aux | grep "python3 main.py"    # Manager API
ps aux | grep "streamlit run"      # Dashboard
docker-compose ps                  # Docker services
```

### Service Management
```bash
# Restart individual services
pkill -f "python3 main.py" && cd manager && python3 main.py &   # Manager
pkill -f "streamlit run" && cd dashboard && streamlit run app.py &  # Dashboard
docker-compose restart apisix      # APISIX only

# Full restart
./stop.sh && ./deploy.sh
```

### Database
```bash
# Backup database
cp manager/vllm_platform.db manager/vllm_platform.db.backup.$(date +%Y%m%d)

# View database
sqlite3 manager/vllm_platform.db
# Then: .tables, .schema, SELECT * FROM models;

# Reset database (WARNING: deletes all data!)
rm manager/vllm_platform.db
# Restart Manager to recreate: cd manager && python3 main.py
```

### Network Testing
```bash
# Test connectivity to other DGX
ping dgx-01
ping 172.30.140.53

# Test vLLM endpoints
curl http://dgx-01:8000/v1/models
curl http://localhost:8000/v1/models

# Test Manager API
curl http://localhost:8001/health
curl http://localhost:8001/models

# Test APISIX
curl http://localhost:9080/health
```

### API Usage
```bash
# List models (no auth needed)
curl http://localhost:8001/models

# Create user
curl -X POST http://localhost:8001/users \
  -H "Content-Type: application/json" \
  -d '{"username":"testuser","email":"test@example.com"}'

# Create API key (replace USER_ID)
curl -X POST http://localhost:8001/api-keys \
  -H "Content-Type: application/json" \
  -d '{"user_id":1,"name":"test_key","max_tokens_per_day":100000,"max_tokens_per_month":1000000,"rate_limit_per_minute":100}'

# Test gateway (replace API_KEY and MODEL)
curl -X POST http://localhost:9080/v1/chat/completions \
  -H "Authorization: Bearer API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"MODEL_NAME","messages":[{"role":"user","content":"Hello"}],"max_tokens":10}'
```

### Prometheus Queries
```bash
# Open Prometheus: http://localhost:9090

# Useful queries:
rate(apisix_http_requests_total[5m])        # Request rate
manager_requests_total                       # Total Manager requests
tokens_processed_total                       # Total tokens
rate(request_duration_seconds_sum[5m])      # Avg response time
```

### Docker Commands
```bash
docker-compose up -d              # Start services
docker-compose down               # Stop services
docker-compose ps                 # List services
docker-compose logs -f            # View all logs
docker-compose logs -f apisix     # View specific service
docker-compose restart apisix     # Restart service
docker-compose pull               # Update images
```

### Troubleshooting
```bash
# Check ports in use
sudo lsof -i :9080    # APISIX Gateway
sudo lsof -i :8001    # Manager API
sudo lsof -i :8501    # Dashboard
sudo lsof -i :8000    # vLLM

# Check disk space
df -h

# Check memory usage
free -h

# Check GPU usage (if running vLLM locally)
nvidia-smi

# View all processes
ps aux | grep -E "python3|streamlit|docker"

# Network interfaces
ip addr
```

## Access URLs

### Local Access
```
Dashboard:      http://localhost:8501
Manager API:    http://localhost:8001
Manager Docs:   http://localhost:8001/docs
APISIX Gateway: http://localhost:9080
Prometheus:     http://localhost:9090
Grafana:        http://localhost:3000
```

### Network Access (from other machines)
```
Dashboard:      http://172.30.140.142:8501
Manager API:    http://172.30.140.142:8001
APISIX Gateway: http://172.30.140.142:9080
Prometheus:     http://172.30.140.142:9090
Grafana:        http://172.30.140.142:3000
```

## Environment Variables

Edit `.env` file to customize:
```bash
MANAGER_API_HOST=0.0.0.0
MANAGER_API_PORT=8001
APISIX_GATEWAY_PORT=9080
APISIX_ADMIN_KEY=vllm-platform-admin-key-2026
MANAGER_IP=172.30.140.142
DGX_01_IP=172.30.140.53
```

## File Locations

```
Platform:              /home/nvidia/reap/vllm-platform/
Database:              /home/nvidia/reap/vllm-platform/manager/vllm_platform.db
Logs:                  /home/nvidia/reap/vllm-platform/logs/
APISIX Config:         /home/nvidia/reap/vllm-platform/apisix_conf/
Prometheus Config:     /home/nvidia/reap/vllm-platform/prometheus.yml
```

## Keyboard Shortcuts

### In Dashboard
- `Ctrl+C` in terminal to stop
- `R` in browser to refresh/rerun
- `Ctrl+Shift+R` to clear cache

### In Terminal
- `Ctrl+C` to stop process
- `Ctrl+Z` to suspend (then `bg` to background)
- `Ctrl+D` to exit
