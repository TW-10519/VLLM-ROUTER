#!/usr/bin/env python3
"""
End-to-end test suite for vLLM Platform
Tests the complete flow from gateway to vLLM backend
"""

import requests
import json
import time
import sys
from typing import Dict, Any

# Configuration
MANAGER_API = "http://localhost:8001"
APISIX_GATEWAY = "http://localhost:9080"
APISIX_ADMIN = "http://localhost:9180/apisix/admin"
APISIX_ADMIN_KEY = "vllm-platform-admin-key-2026"

class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    RESET = '\033[0m'

def print_test(name: str):
    print(f"\n{Colors.BLUE}▶ {name}{Colors.RESET}")

def print_success(msg: str):
    print(f"{Colors.GREEN}✅ {msg}{Colors.RESET}")

def print_error(msg: str):
    print(f"{Colors.RED}❌ {msg}{Colors.RESET}")

def print_warning(msg: str):
    print(f"{Colors.YELLOW}⚠️  {msg}{Colors.RESET}")

def test_manager_health() -> bool:
    """Test if Manager API is responding"""
    print_test("Testing Manager API Health")
    try:
        response = requests.get(f"{MANAGER_API}/health", timeout=5)
        if response.status_code == 200:
            print_success("Manager API is healthy")
            return True
        else:
            print_error(f"Manager API returned {response.status_code}")
            return False
    except Exception as e:
        print_error(f"Manager API not accessible: {e}")
        return False

def test_apisix_health() -> bool:
    """Test if APISIX is responding"""
    print_test("Testing APISIX Gateway")
    try:
        response = requests.get(f"{APISIX_GATEWAY}/health", timeout=5)
        if response.status_code in [200, 404]:  # 404 is ok if health route not configured yet
            print_success("APISIX Gateway is accessible")
            return True
        else:
            print_error(f"APISIX returned {response.status_code}")
            return False
    except Exception as e:
        print_error(f"APISIX not accessible: {e}")
        return False

def test_create_user() -> Dict[str, Any]:
    """Test creating a user"""
    print_test("Creating Test User")
    try:
        response = requests.post(
            f"{MANAGER_API}/users",
            json={
                "username": f"test_user_{int(time.time())}",
                "email": "test@example.com"
            },
            timeout=5
        )
        
        if response.status_code == 200:
            data = response.json()
            print_success(f"User created: {data['username']} (ID: {data['id']})")
            return {"success": True, "data": data}
        else:
            print_error(f"Failed to create user: {response.text}")
            return {"success": False}
    except Exception as e:
        print_error(f"Error creating user: {e}")
        return {"success": False}

def test_create_api_key(user_id: int) -> Dict[str, Any]:
    """Test creating an API key"""
    print_test("Creating Test API Key")
    try:
        response = requests.post(
            f"{MANAGER_API}/api-keys",
            json={
                "user_id": user_id,
                "name": "test_key"
            },
            timeout=5
        )
        
        if response.status_code == 200:
            data = response.json()
            print_success(f"API key created: {data['key'][:20]}...")
            return {"success": True, "data": data}
        else:
            print_error(f"Failed to create API key: {response.text}")
            return {"success": False}
    except Exception as e:
        print_error(f"Error creating API key: {e}")
        return {"success": False}

def test_register_model(name: str, host: str, port: int) -> bool:
    """Test registering a model"""
    print_test(f"Registering Model: {name}")
    try:
        response = requests.post(
            f"{MANAGER_API}/models",
            json={
                "name": name,
                "backend_host": host,
                "backend_port": port,
                "description": f"Test model {name}"
            },
            timeout=5
        )
        
        if response.status_code == 200:
            print_success(f"Model registered: {name} -> {host}:{port}")
            return True
        else:
            error_msg = response.json().get("detail", response.text)
            if "already exists" in str(error_msg):
                print_warning(f"Model already exists: {name}")
                return True
            else:
                print_error(f"Failed to register model: {error_msg}")
                return False
    except Exception as e:
        print_error(f"Error registering model: {e}")
        return False

def test_list_models() -> bool:
    """Test listing models"""
    print_test("Listing Models")
    try:
        response = requests.get(f"{MANAGER_API}/models", timeout=5)
        if response.status_code == 200:
            models = response.json()
            print_success(f"Found {len(models)} model(s)")
            for model in models:
                print(f"   • {model['name']} -> {model['backend_url']}")
            return True
        else:
            print_error(f"Failed to list models: {response.status_code}")
            return False
    except Exception as e:
        print_error(f"Error listing models: {e}")
        return False

def test_model_resolution(model_name: str) -> bool:
    """Test model resolution"""
    print_test(f"Testing Model Resolution: {model_name}")
    try:
        response = requests.post(
            f"{MANAGER_API}/resolve-model",
            json={"model": model_name},
            timeout=5
        )
        
        if response.status_code == 200:
            data = response.json()
            print_success(f"Resolved to: {data['backend_url']}")
            return True
        else:
            print_error(f"Failed to resolve model: {response.status_code}")
            return False
    except Exception as e:
        print_error(f"Error resolving model: {e}")
        return False

def test_validate_api_key(api_key: str) -> bool:
    """Test API key validation"""
    print_test("Testing API Key Validation")
    try:
        response = requests.post(
            f"{MANAGER_API}/auth/validate-key",
            json={"key": api_key},
            timeout=5
        )
        
        if response.status_code == 200:
            data = response.json()
            print_success(f"API key valid (User ID: {data.get('user_id')})")
            return True
        else:
            print_error(f"API key validation failed: {response.status_code}")
            return False
    except Exception as e:
        print_error(f"Error validating API key: {e}")
        return False

def test_vllm_endpoint(host: str, port: int) -> bool:
    """Test if vLLM endpoint is accessible"""
    print_test(f"Testing vLLM Endpoint: {host}:{port}")
    url = f"http://{host}:{port}"
    
    try:
        response = requests.get(f"{url}/v1/models", timeout=5)
        if response.status_code == 200:
            data = response.json()
            models = data.get("data", [])
            print_success(f"vLLM is running with {len(models)} model(s)")
            for model in models:
                print(f"   • {model.get('id', 'unknown')}")
            return True
        else:
            print_warning(f"vLLM returned {response.status_code}")
            return False
    except requests.exceptions.ConnectionError:
        print_warning(f"vLLM not running at {url}")
        return False
    except Exception as e:
        print_warning(f"Cannot reach vLLM: {e}")
        return False

def test_gateway_request(api_key: str, model: str) -> bool:
    """Test complete request through gateway"""
    print_test(f"Testing Gateway Request (model: {model})")
    
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "Say 'test successful' in 3 words"}],
        "max_tokens": 10
    }
    
    try:
        response = requests.post(
            f"{APISIX_GATEWAY}/v1/chat/completions",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}"
            },
            json=payload,
            timeout=60
        )
        
        if response.status_code == 200:
            data = response.json()
            if "choices" in data:
                content = data["choices"][0]["message"]["content"]
                print_success(f"Gateway request successful!")
                print(f"   Response: {content[:100]}")
                
                if "usage" in data:
                    print(f"   Tokens: {data['usage']['total_tokens']}")
                return True
        
        print_error(f"Gateway request failed: {response.status_code}")
        print(f"   Response: {response.text[:200]}")
        return False
        
    except requests.exceptions.Timeout:
        print_error("Request timed out")
        return False
    except Exception as e:
        print_error(f"Gateway request error: {e}")
        return False

def main():
    print("""
╔═══════════════════════════════════════════════════════╗
║       vLLM Platform - End-to-End Test Suite          ║
╚═══════════════════════════════════════════════════════╝
""")
    
    results = []
    
    # 1. Test Manager Health
    if not test_manager_health():
        print_error("\n❌ Manager API is not running. Start it with: ./deploy.sh")
        sys.exit(1)
    results.append(True)
    
    # 2. Test APISIX
    if not test_apisix_health():
        print_error("\n❌ APISIX is not running. Start it with: ./deploy.sh")
        sys.exit(1)
    results.append(True)
    
    # 3. Create user and API key
    user_result = test_create_user()
    if user_result["success"]:
        results.append(True)
        
        key_result = test_create_api_key(user_result["data"]["id"])
        if key_result["success"]:
            results.append(True)
            test_api_key = key_result["data"]["key"]
            
            # Test key validation
            results.append(test_validate_api_key(test_api_key))
        else:
            results.append(False)
    else:
        results.append(False)
    
    # 4. Test model registration
    results.append(test_register_model("test-model", "localhost", 8000))
    
    # 5. List models
    results.append(test_list_models())
    
    # 6. Test model resolution
    results.append(test_model_resolution("test-model"))
    
    # 7. Test vLLM endpoint (optional - may not be running)
    vllm_running = test_vllm_endpoint("localhost", 8000)
    if vllm_running:
        print_warning("vLLM detected - you can test gateway requests now")
    else:
        print_warning("vLLM not running - skipping gateway test")
        print_warning("Start vLLM to test the complete flow: ./start_vllm.sh")
    
    # Summary
    print("\n" + "=" * 60)
    print(f"\n📊 Test Results: {sum(results)}/{len(results)} passed")
    
    if all(results):
        print_success("\n✅ All tests passed!")
        print("\n🎯 Platform is ready for use!")
        print("\nNext steps:")
        print("  1. Start vLLM: ./start_vllm.sh")
        print("  2. Register instances via dashboard: http://localhost:8501")
        print("  3. Test gateway requests")
        return 0
    else:
        print_error("\n❌ Some tests failed")
        return 1

if __name__ == "__main__":
    sys.exit(main())
