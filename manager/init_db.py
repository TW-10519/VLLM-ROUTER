#!/usr/bin/env python3
"""
Initialize database with sample data
"""

import requests
import json
import time

MANAGER_API = "http://localhost:8001"

def wait_for_manager():
    """Wait for Manager API to be ready"""
    print("Waiting for Manager API...")
    for i in range(30):
        try:
            response = requests.get(f"{MANAGER_API}/health", timeout=2)
            if response.status_code == 200:
                print("✅ Manager API is ready")
                return True
        except:
            pass
        time.sleep(1)
    print("❌ Manager API did not start")
    return False


def create_models():
    """Create model registrations"""
    print("\n=== Creating Models ===")
    
    models = [
        {
            "name": "llama-2-7b",
            "backend_host": "dgx-01",
            "backend_port": 8000,
            "description": "Llama 2 7B model on DGX-01"
        },
        {
            "name": "mistral-7b",
            "backend_host": "172.30.140.142",
            "backend_port": 8000,
            "description": "Mistral 7B model on local DGX (Manager)"
        }
    ]
    
    for model in models:
        try:
            response = requests.post(f"{MANAGER_API}/models", json=model)
            if response.status_code == 200:
                print(f"✅ Created model: {model['name']} -> {model['backend_host']}")
            else:
                print(f"⚠️  Model {model['name']}: {response.json()}")
        except Exception as e:
            print(f"❌ Error creating model {model['name']}: {e}")


def create_users_and_keys():
    """Create users and API keys"""
    print("\n=== Creating Users and API Keys ===")
    
    users = [
        {"username": "admin", "email": "admin@example.com"},
        {"username": "test_user", "email": "test@example.com"},
        {"username": "enterprise_user", "email": "enterprise@example.com"}
    ]
    
    for user in users:
        try:
            response = requests.post(f"{MANAGER_API}/users", json=user)
            if response.status_code == 200:
                user_data = response.json()
                user_id = user_data["id"]
                print(f"✅ Created user: {user['username']} (ID: {user_id})")
                
                # Create API key for this user
                if user["username"] == "admin":
                    key_config = {
                        "user_id": user_id,
                        "name": f"{user['username']}_key"
                    }
                elif user["username"] == "enterprise_user":
                    key_config = {
                        "user_id": user_id,
                        "name": f"{user['username']}_key"
                    }
                else:
                    key_config = {
                        "user_id": user_id,
                        "name": f"{user['username']}_key"
                    }
                
                key_response = requests.post(f"{MANAGER_API}/api-keys", json=key_config)
                if key_response.status_code == 200:
                    key_data = key_response.json()
                    print(f"   🔑 API Key: {key_data['key']}")
            else:
                print(f"⚠️  User {user['username']}: {response.json()}")
        except Exception as e:
            print(f"❌ Error creating user {user['username']}: {e}")


def configure_apisix_route():
    """Configure APISIX route to proxy through Manager"""
    print("\n=== Configuring APISIX Routes ===")
    
    admin_key = "vllm-platform-admin-key-2026"
    apisix_admin = "http://localhost:9180/apisix/admin"
    
    # Create route for /v1/chat/completions
    route_config = {
        "uri": "/v1/chat/completions",
        "methods": ["POST"],
        "plugins": {
            "serverless-pre-function": {
                "phase": "rewrite",
                "functions": [
                    """
                    return function(conf, ctx)
                        local core = require("apisix.core")
                        local http = require("resty.http")
                        local cjson = require("cjson")
                        
                        -- Get API key from header
                        local auth_header = core.request.header(ctx, "Authorization")
                        local api_key_header = core.request.header(ctx, "X-API-Key")
                        if not auth_header and not api_key_header then
                            core.response.exit(401, {error = "Missing Authorization or X-API-Key header"})
                        end
                        
                        -- Extract key
                        local api_key = nil
                        if api_key_header then
                            api_key = api_key_header
                        else
                            api_key = auth_header:match("Bearer%s+(.+)")
                            if not api_key then
                                api_key = auth_header
                            end
                        end
                        
                        -- Capture session identifier (optional)
                        local session_id = core.request.header(ctx, "X-Session-Id")
                        if not session_id then
                            session_id = core.request.header(ctx, "X-Forwarded-For")
                        end

                        -- Validate key with Manager
                        local httpc = http.new()
                        local res, err = httpc:request_uri("http://172.30.140.142:8001/auth/validate-key", {
                            method = "POST",
                            body = cjson.encode({key = api_key, session_id = session_id}),
                            headers = {["Content-Type"] = "application/json"}
                        })
                        
                        if not res or res.status ~= 200 then
                            core.response.exit(401, {error = "Invalid API key"})
                        end
                        
                        -- Get request body to extract model
                        local body, err = core.request.get_body()
                        if not body then
                            core.response.exit(400, {error = "Missing request body"})
                        end
                        
                        local data = cjson.decode(body)
                        local model = data.model
                        
                        if not model then
                            core.response.exit(400, {error = "Missing model parameter"})
                        end
                        
                        -- Resolve model to backend
                        local res2, err2 = httpc:request_uri("http://172.30.140.142:8001/resolve-model", {
                            method = "POST",
                            body = cjson.encode({model = model}),
                            headers = {["Content-Type"] = "application/json"}
                        })
                        
                        if not res2 or res2.status ~= 200 then
                            core.response.exit(404, {error = "Model not found"})
                        end
                        
                        local backend_data = cjson.decode(res2.body)
                        local backend_url = backend_data.backend_url
                        
                        -- Set upstream
                        ctx.var.upstream_uri = backend_url .. "/v1/chat/completions"
                        
                        -- Store api_key and model for response logging
                        ctx.var.api_key = api_key
                        ctx.var.model = model
                    end
                    """
                ]
            },
            "serverless-post-function": {
                "phase": "log",
                "functions": [
                    """
                    return function(conf, ctx)
                        local core = require("apisix.core")
                        local http = require("resty.http")
                        local cjson = require("cjson")

                        if not ctx.var.api_key or not ctx.var.model then
                            return
                        end

                        local body = ctx.var.resp_body
                        if not body then
                            return
                        end

                        local ok, data = pcall(cjson.decode, body)
                        if not ok or not data then
                            return
                        end

                        local usage = data.usage or {}
                        local payload = {
                            api_key = ctx.var.api_key,
                            model = ctx.var.model,
                            prompt_tokens = usage.prompt_tokens or 0,
                            completion_tokens = usage.completion_tokens or 0,
                            total_tokens = usage.total_tokens or 0
                        }

                        local httpc = http.new()
                        httpc:request_uri("http://172.30.140.142:8001/usage/report", {
                            method = "POST",
                            body = cjson.encode(payload),
                            headers = { ["Content-Type"] = "application/json" }
                        })
                    end
                    """
                ]
            },
            "proxy-rewrite": {
                "regex_uri": ["^/v1/chat/completions$", "/v1/chat/completions"]
            },
            "prometheus": {}
        },
        "upstream": {
            "type": "roundrobin",
            "nodes": {
                "172.30.140.142:8000": 1
            },
            "timeout": {
                "connect": 60,
                "send": 60,
                "read": 60
            }
        }
    }
    
    try:
        response = requests.put(
            f"{apisix_admin}/routes/1",
            headers={"X-API-KEY": admin_key, "Content-Type": "application/json"},
            json=route_config
        )
        if response.status_code in [200, 201]:
            print("✅ Created route: /v1/chat/completions")
        else:
            print(f"⚠️  Route creation: {response.text}")
    except Exception as e:
        print(f"❌ Error creating route: {e}")
    
    # Create health check route (no auth required)
    health_route = {
        "uri": "/health",
        "methods": ["GET"],
        "plugins": {
            "prometheus": {}
        },
        "upstream": {
            "type": "roundrobin",
            "nodes": {
                "172.30.140.142:8001": 1
            }
        }
    }
    
    try:
        response = requests.put(
            f"{apisix_admin}/routes/2",
            headers={"X-API-KEY": admin_key, "Content-Type": "application/json"},
            json=health_route
        )
        if response.status_code in [200, 201]:
            print("✅ Created route: /health")
        else:
            print(f"⚠️  Health route creation: {response.text}")
    except Exception as e:
        print(f"❌ Error creating health route: {e}")


def main():
    print("=== vLLM Platform Database Initialization ===\n")
    
    # Wait for Manager API
    if not wait_for_manager():
        return
    
    # Create models
    create_models()
    
    # Create users and API keys
    create_users_and_keys()
    
    # Configure APISIX
    configure_apisix_route()
    
    print("\n=== Initialization Complete ===")
    print("\nYou can now:")
    print("1. Start vLLM on this DGX (port 8000)")
    print("2. Test the gateway with: curl -X POST http://localhost:9080/v1/chat/completions")
    print("3. View logs: docker-compose logs -f apisix")
    print("4. Access Grafana: http://localhost:3000 (admin/admin)")


if __name__ == "__main__":
    main()
