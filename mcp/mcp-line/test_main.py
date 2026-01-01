#!/usr/bin/env python3
"""
Test suite for mcp-line webhook service
"""
import base64
import hashlib
import hmac
import json
import requests
import time
from typing import Dict, Any

# Test configuration
BASE_URL = "http://127.0.0.1:8088"
LINE_CHANNEL_SECRET = "43af9b639dbe4693cd04faef7a62229e"

def _create_line_signature(body: str, secret: str) -> str:
    """Create LINE signature for webhook testing"""
    mac = hmac.new(secret.encode("utf-8"), body.encode("utf-8"), hashlib.sha256).digest()
    return base64.b64encode(mac).decode("utf-8")

def test_health_endpoint():
    """Test the health check endpoint"""
    print("Testing health endpoint...")
    response = requests.get(f"{BASE_URL}/health")
    
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    data = response.json()
    assert data["status"] == "ok"
    assert data["signatureConfigured"] == True
    assert data["accessTokenConfigured"] == True
    
    print("✅ Health endpoint working correctly")
    return True

def test_webhook_without_signature():
    """Test webhook without signature (should fail)"""
    print("Testing webhook without signature...")
    payload = {"events": []}
    
    response = requests.post(
        f"{BASE_URL}/webhook/line",
        json=payload,
        headers={"Content-Type": "application/json"}
    )
    
    assert response.status_code == 401, f"Expected 401, got {response.status_code}"
    data = response.json()
    assert data["detail"] == "invalid_signature"
    
    print("✅ Webhook correctly rejects requests without signature")
    return True

def test_webhook_with_invalid_signature():
    """Test webhook with invalid signature (should fail)"""
    print("Testing webhook with invalid signature...")
    payload = {"events": []}
    
    response = requests.post(
        f"{BASE_URL}/webhook/line",
        json=payload,
        headers={
            "Content-Type": "application/json",
            "X-Line-Signature": "invalid_signature_base64"
        }
    )
    
    assert response.status_code == 401, f"Expected 401, got {response.status_code}"
    data = response.json()
    assert data["detail"] == "invalid_signature"
    
    print("✅ Webhook correctly rejects requests with invalid signature")
    return True

def test_webhook_with_valid_signature():
    """Test webhook with valid signature (should succeed)"""
    print("Testing webhook with valid signature...")
    
    # Create a test message event
    payload = {
        "events": [
            {
                "type": "message",
                "message": {
                    "type": "text",
                    "text": "Hello test"
                },
                "source": {
                    "type": "user",
                    "userId": "test-user-id"
                },
                "replyToken": "test-reply-token"
            }
        ]
    }
    
    body_str = json.dumps(payload, separators=(',', ':'))
    signature = _create_line_signature(body_str, LINE_CHANNEL_SECRET)
    
    response = requests.post(
        f"{BASE_URL}/webhook/line",
        data=body_str,
        headers={
            "Content-Type": "application/json",
            "X-Line-Signature": signature
        }
    )
    
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    data = response.json()
    assert data["status"] == "ok"
    assert "events" in data
    assert data["events"] == 1
    
    print("✅ Webhook correctly processes valid requests")
    return True

def test_webhook_with_empty_events():
    """Test webhook with empty events array"""
    print("Testing webhook with empty events...")
    
    payload = {"events": []}
    body_str = json.dumps(payload, separators=(',', ':'))
    signature = _create_line_signature(body_str, LINE_CHANNEL_SECRET)
    
    response = requests.post(
        f"{BASE_URL}/webhook/line",
        data=body_str,
        headers={
            "Content-Type": "application/json",
            "X-Line-Signature": signature
        }
    )
    
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    data = response.json()
    assert data["status"] == "ok"
    assert data["events"] == 0
    
    print("✅ Webhook correctly handles empty events")
    return True

def run_all_tests():
    """Run all test cases"""
    print("🧪 Running mcp-line test suite...\n")
    
    tests = [
        test_health_endpoint,
        test_webhook_without_signature,
        test_webhook_with_invalid_signature,
        test_webhook_with_valid_signature,
        test_webhook_with_empty_events
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            if test():
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"❌ {test.__name__} failed: {e}")
            failed += 1
        print()
    
    print(f"📊 Test Results: {passed} passed, {failed} failed")
    
    if failed == 0:
        print("🎉 All tests passed!")
        return True
    else:
        print("💥 Some tests failed!")
        return False

if __name__ == "__main__":
    # Wait a moment for service to start
    time.sleep(2)
    run_all_tests()
