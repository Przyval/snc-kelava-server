import json
import time

import requests

# Configuration
API_URL = "http://localhost:5001/api/v1/enterprise/tracking/position"


def test_tracking_endpoint():
    print(f"Testing Tracking Endpoint: {API_URL}")

    payload = {
        "lat": -7.2575,
        "lng": 112.7521,
        "tech_id": 392,
        "timestamp": "2026-02-10T10:00:00+07:00",
    }

    try:
        start_time = time.time()
        response = requests.post(API_URL, json=payload, timeout=5)
        duration = time.time() - start_time

        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.text}")
        print(f"Duration: {duration:.3f}s")

        if response.status_code == 201:
            print("✅ SUCCESS: Data accepted and inserted.")
        else:
            print("❌ FAILED: Unexpected status code.")

    except Exception as e:
        print(f"❌ ERROR: Could not connect to API. Is the server running? ({e})")


if __name__ == "__main__":
    test_tracking_endpoint()
