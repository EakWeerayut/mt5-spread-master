import urllib.request
import json

# Test version endpoint to check which server instance is responding
try:
    req = urllib.request.urlopen("http://localhost:8080/api/status")
    print(json.loads(req.read().decode("utf-8")))
except Exception as e:
    print(f"Status error: {e}")

# Check if there's a version or ping endpoint
try:
    req2 = urllib.request.urlopen("http://localhost:8080/")
    print("Homepage status:", req2.status)
except Exception as e2:
    print(f"Homepage error: {e2}")
