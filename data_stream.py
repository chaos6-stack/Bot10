# data_stream.py
"""
Deriv WebSocket Stream Integration Module
Establishes a connection to the high-frequency Deriv API, handles subscriptions
to real-time prices, and offers fallback mock stream generators for high-continuity offline testing.
"""

import json
import time
import threading
import random
import config

# Try importing websocket-client library
try:
    import websocket
    HAS_WEBSOCKET_LIB = True
except ImportError:
    HAS_WEBSOCKET_LIB = False

class DerivDataStream:
    def __init__(self, symbol: str = config.ACTIVE_SYMBOL, on_tick_callback=None):
        self.raw_symbol = symbol.upper()
        # Translate symbol to standard Deriv WS API subscription identifiers
        # Deriv symbols typically use "R_BOOM1000" or similar
        self.symbol = self.raw_symbol
            
        self.on_tick_callback = on_tick_callback
        self.ws = None
        self.is_running = False
        self.reconnect_delay = 5  # seconds
        self.use_fallback = not HAS_WEBSOCKET_LIB

    def start(self):
        """Starts stream monitoring on a background thread."""
        self.is_running = True
        if self.use_fallback:
            print("[STREAM] 'websocket-client' module not found or fallback active. Running in simulated streaming mode.")
            threading.Thread(target=self._simulate_stream, daemon=True).start()
        else:
            threading.Thread(target=self._connect_websocket_loop, daemon=True).start()

    def stop(self):
        """Halts background listening loops safely."""
        self.is_running = False
        if self.ws:
            try:
                self.ws.close()
            except Exception:
                pass

    def _connect_websocket_loop(self):
        """Continuous supervisor that reconnects websocket upon networking failures."""
        url = f"wss://ws.derivws.com/websockets/v3?app_id={config.APP_ID}"
        
        while self.is_running:
            try:
                print(f"[STREAM] Connecting to live Deriv WebSocket for symbol: {self.symbol}...")
                
                # Setup App WebSocket callback protocols
                self.ws = websocket.WebSocketApp(
                    url,
                    on_open=self._on_open,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close
                )
                
                self.ws.run_forever(ping_interval=15, ping_timeout=10)
            except Exception as e:
                print(f"[STREAM] Connection error: {e}")
                
            if not self.is_running:
                break
                
            print(f"[STREAM] Disconnected. Retrying in {self.reconnect_delay} seconds...")
            time.sleep(self.reconnect_delay)

    def _on_open(self, ws):
        print(f"[STREAM] Web Socket connection active. Subscribing to {self.symbol} ticks.")
        # Craft subscription request payload
        req = {
            "ticks": self.symbol,
            "subscribe": 1
        }
        ws.send(json.dumps(req))

    def _on_message(self, ws, msg):
        try:
            data = json.loads(msg)
            if "tick" in data:
                tick_info = data["tick"]
                price = float(tick_info["quote"])
                timestamp = int(tick_info["epoch"])
                
                if self.on_tick_callback:
                    self.on_tick_callback(price, timestamp)
            elif "error" in data:
                err_msg = data["error"].get("message", "Unknown Deriv API error")
                print(f"[STREAM] Deriv API returned error: {err_msg}")
                # If symbol is invalid, let's gracefully load fallback simulator
                if "invalid symbol" in err_msg.lower():
                    print("[STREAM] Switching to high-fidelity market simulator to sustain operation.")
                    self.stop()
                    self.use_fallback = True
                    self.start()
        except Exception as e:
            print(f"[STREAM] Error parsing WS payload message: {e}")

    def _on_error(self, ws, err):
         print(f"[STREAM] WebSocket protocol error triggered: {err}")

    def _on_close(self, ws, close_status_code, close_msg):
        print(f"[STREAM] Connection closed. Code: {close_status_code}, Msg: {close_msg}")

    def _simulate_stream(self):
        """
        Creates automated, clean offline tick price feed replicating
        synthetic index behaviors (1.5-second frequency, with drift and spikes).
        """
        price = 1000.00
        is_boom = "BOOM" in self.raw_symbol
        drift = -0.05 if is_boom else 0.05
        noise = 0.02
        spike_prob = 0.03
        
        while self.is_running:
            # 1. Simulate tick movement style
            change = drift + random.uniform(-noise, noise)
            
            # Formulate spikes
            if random.random() < spike_prob:
                spike_size = random.uniform(8.0, 24.0)
                if is_boom:
                    change += spike_size
                else:
                    change -= spike_size
                    
            price += change
            curr_time = int(time.time())
            
            # Feed current price ticks to orchestrator asynchronously
            if self.on_tick_callback:
                self.on_tick_callback(price, curr_time)
                
            # Deriv synthetic tick feeds usually update every 1 to 2 seconds
            time.sleep(random.uniform(1.2, 1.8))

