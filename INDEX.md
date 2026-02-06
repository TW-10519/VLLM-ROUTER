# 📚 Documentation

## Quick Links

**Want to start?** → [GETTING_STARTED.md](GETTING_STARTED.md)

**Full details?** → [README.md](README.md)

**Commands?** → [COMMANDS.md](COMMANDS.md)

### Something not working?

1. **Check service status**
   ```bash
   ./status.sh
   ```

2. **View logs**
   ```bash
   tail -f logs/manager.log
   tail -f logs/dashboard.log
   docker-compose logs -f apisix
   ```

3. **Run tests**
   ```bash
   python3 test_platform.py
   ```

4. **Read troubleshooting**
   - [GETTING_STARTED.md](GETTING_STARTED.md) - "Troubleshooting" section
   - [COMMANDS.md](COMMANDS.md) - "Troubleshooting" section

### Common Issues

| Issue | Solution | Documentation |
|-------|----------|---------------|
| Services won't start | Check ports: `sudo lsof -i :9080` | [COMMANDS.md](COMMANDS.md#troubleshooting) |
| Can't reach vLLM | Test: `curl http://dgx-01:8000/v1/models` | [GETTING_STARTED.md](GETTING_STARTED.md#troubleshooting) |
| API key not working | Check in dashboard → API Keys tab | [GETTING_STARTED.md](GETTING_STARTED.md#create-users-and-api-keys) |
| Database issues | Backup and reset database | [COMMANDS.md](COMMANDS.md#database) |

## 🎯 Key Features

✅ **Cold Start Ready** - No pre-configuration needed  
✅ **Built-in Testing** - Test vLLM before registering  
✅ **OpenAI Compatible** - Drop-in replacement  
✅ **Dynamic Routing** - Add models without restart  
✅ **Token Tracking** - Automatic usage recording  
✅ **Multi-tier Access** - Free, Pro, Enterprise tiers  
✅ **Web Dashboard** - Manage everything via UI  
✅ **Monitoring** - Prometheus + Grafana included  

## 📊 Architecture Overview

```
Client → APISIX → Manager API → vLLM Backend
           ↓          ↓
      Metrics    Database
```

For detailed architecture, see [ARCHITECTURE.md](ARCHITECTURE.md)

## 🚀 What's Next?

After deploying:
1. ✅ Register vLLM instances
2. ✅ Create API keys
3. ✅ Test the gateway
4. ✅ Set up monitoring
5. ✅ Scale to more DGXs

## 💡 Pro Tips

- **Always test before registering** - Dashboard has built-in vLLM testing
- **Use the dashboard** - Easier than manual API calls
- **Check logs regularly** - `tail -f logs/*.log`
- **Monitor from day 1** - Grafana is already configured
- **Start simple** - One model, one user, then scale

## 🤝 Contributing

Want to extend the platform? See [ARCHITECTURE.md](ARCHITECTURE.md) - "Extension Points" section

## 📄 License

Built for your DGX environment. Customize as needed!

---

**Quick Start:** [GETTING_STARTED.md](GETTING_STARTED.md)  
**Full Docs:** [README.md](README.md)  
**Architecture:** [ARCHITECTURE.md](ARCHITECTURE.md)  
**Commands:** [COMMANDS.md](COMMANDS.md)

🎉 **Ready to deploy?** Run: `./deploy.sh`
