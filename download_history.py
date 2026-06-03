import asyncio
import json
import os
import csv
from datetime import datetime
import websockets

# Configuration
APP_ID = "1089"  # Deriv standard API AppID
SYMBOL_MAPPING = {
    "BOOM1000": "BOOM1000",
    "CRASH1000": "CRASH1000",
    "BOOM500": "BOOM500",
    "CRASH500": "CRASH500"
}

async def fetch_historical_data(symbol_name, datatype="candles", count=5000, granularity=60):
    """
    datatype: "candles" (for OHLC candles) or "ticks" (for raw transaction price ticks)
    """
    os.makedirs("market_data", exist_ok=True)
    api_symbol = SYMBOL_MAPPING.get(symbol_name, symbol_name)
    uri = f"wss://ws.derivws.com/websockets/v3?app_id={APP_ID}"
    
    all_times = []
    all_prices = []
    all_candles = []
    
    # Deriv limits single requests to 5000. We batch to reach the target count.
    batch_size = 5000
    remaining = count
    end_time = "latest"
    
    print(f"Connecting to Deriv WebSocket to fetch {count} {datatype} for {symbol_name}...")
    
    async with websockets.connect(uri) as websocket:
        while remaining > 0:
            request_count = min(remaining, batch_size)
            request = {
                "ticks_history": api_symbol,
                "adjust_start_time": 1,
                "count": request_count,
                "end": end_time,
                "style": datatype
            }
            
            if datatype == "candles":
                request["granularity"] = granularity
                
            await websocket.send(json.dumps(request))
            response_data = await websocket.recv()
            result = json.loads(response_data)
            
            if "error" in result:
                print(f"❌ Error from Deriv: {result['error']['message']}")
                break

            if datatype == "ticks" and "history" in result:
                times = result["history"]["times"]
                prices = result["history"]["prices"]
                if not times: break
                
                all_times = times + all_times
                all_prices = prices + all_prices
                # Update end_time for the next batch (earliest time in this batch)
                end_time = times[0]
                remaining -= len(times)
                print(f"  > Downloaded {len(all_times)}/{count} ticks...")
                
            elif datatype == "candles" and "candles" in result:
                candles = result["candles"]
                if not candles: break
                all_candles = candles + all_candles
                end_time = candles[0]["epoch"]
                remaining -= len(candles)
                print(f"  > Downloaded {len(all_candles)}/{count} candles...")
            
            # Brief sleep to respect API limits
            await asyncio.sleep(0.5)

        # Save Ticks
        if datatype == "ticks" and all_prices:
            csv_path = f"market_data/{symbol_name}_ticks.csv"
            with open(csv_path, mode="w", newline="") as file:
                writer = csv.writer(file)
                writer.writerow(["Timestamp", "Time_UTC", "Price"])
                for t, p in zip(all_times, all_prices):
                    dt = datetime.utcfromtimestamp(t).strftime('%Y-%m-%d %H:%M:%S')
                    writer.writerow([t, dt, p])
            print(f"✅ Success! Saved {len(all_times)} ticks to: {csv_path}")

# Run the download
if __name__ == "__main__":
    async def main():
        symbols = ["BOOM1000", "CRASH1000", "BOOM500", "CRASH500"]
        tick_count = 50000
        
        for symbol in symbols:
            print(f"\n--- Batch Downloading {symbol} ---")
            try:
                await fetch_historical_data(symbol, datatype="ticks", count=tick_count)
            except Exception as e:
                print(f"⚠️ Failed to download {symbol}: {e}")
            await asyncio.sleep(1)

    asyncio.run(main())
