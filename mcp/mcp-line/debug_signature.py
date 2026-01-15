#!/usr/bin/env python3
import base64
import hashlib
import hmac
import json

secret = '43af9b639dbe4693cd04faef7a62229e'

# Test with different body formats
payload = {"events": [{"type": "message", "message": {"type": "text", "text": "Hello test"}, "source": {"type": "user", "userId": "test-user-id"}, "replyToken": "test-reply-token"}]}

# Method 1: JSON string with compact separators
body_str = json.dumps(payload, separators=(',', ':'))
print("Method 1 - JSON dumps:")
print("Body:", repr(body_str))
mac1 = hmac.new(secret.encode('utf-8'), body_str.encode('utf-8'), hashlib.sha256).digest()
sig1 = base64.b64encode(mac1).decode('utf-8')
print("Signature:", sig1)
print()

# Method 2: What curl might send (different spacing)
body_str2 = '{"events":[{"type":"message","message":{"type":"text","text":"Hello test"},"source":{"type":"user","userId":"test-user-id"},"replyToken":"test-reply-token"}]}'
print("Method 2 - Manual string:")
print("Body:", repr(body_str2))
mac2 = hmac.new(secret.encode('utf-8'), body_str2.encode('utf-8'), hashlib.sha256).digest()
sig2 = base64.b64encode(mac2).decode('utf-8')
print("Signature:", sig2)
print()

# Test if they're the same
print("Signatures match:", sig1 == sig2)
print("Bodies match:", body_str == body_str2)
