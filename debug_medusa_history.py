
import httpx
import asyncio
import sys

# Configuration - update these with your actual Medusa details
MEDUSA_URL = "http://localhost:8081" # Example, change if needed
API_KEY = "YOUR_ACTUAL_API_KEY" # Replace with your real API key

async def fetch_history():
    async with httpx.AsyncClient(base_url=MEDUSA_URL, timeout=10) as client:
        # Params to mimic the actual request
        params = {
            "page": 1,
            "limit": 10,
            "sort": '[{"field":"date","type":"desc"}]',
            "filter": "{}",
            "compact": "false"
        }
        headers = {"X-API-Key": API_KEY}
        
        try:
            print(f"Fetching from {MEDUSA_URL}/api/v2/history...")
            res = await client.get("/api/v2/history", params=params, headers=headers)
            print(f"Status Code: {res.status_code}")
            if res.status_code == 200:
                data = res.json()
                print(f"Raw Response (first item):")
                if data:
                    print(data[0])
                else:
                    print("No records returned.")
            else:
                print(f"Response: {res.text}")
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(fetch_history())
