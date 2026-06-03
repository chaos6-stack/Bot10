# logger.py
"""
Professional Logger Module for the Synthetic Trading Agent
Persists trade execution logs to CSV and JSON, tracking system performance and balance.
"""

import os
import csv
import json
from datetime import datetime
import config

class TradeLogger:
    def __init__(self):
        # Create logs directory if it doesn't exist
        os.makedirs(config.LOG_DIR, exist_ok=True)
        self.csv_path = config.TRADE_LOG_CSV
        self.json_path = config.TRADE_LOG_JSON
        self.metrics_path = config.BOT_METRICS_JSON
        
        # Initialize CSV header if file doesn't exist
        if not os.path.exists(self.csv_path):
            with open(self.csv_path, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    "timestamp", "trade_id", "symbol", "direction", 
                    "entry_price", "exit_price", "pnl", "balance", 
                    "exit_reason", "ticks_held", "spike_detected"
                ])

    def log(self, message: str, level: str = "INFO"):
        """Prints a standardized, legible logging line to stdout."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{timestamp}] [{level}] {message}")

    def log_trade(self, trade_id: str, symbol: str, direction: str, 
                  entry_price: float, exit_price: float, pnl: float, 
                  balance: float, exit_reason: str, ticks_held: int, 
                  spike_detected: bool):
        """Persists trade data to CSV and appends it to a JSON log file."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Log to CSV
        with open(self.csv_path, 'a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                timestamp, trade_id, symbol, direction, 
                entry_price, exit_price, round(pnl, 2), round(balance, 2), 
                exit_reason, ticks_held, spike_detected
            ])
            
        # Log to JSON
        trade_entry = {
            "timestamp": timestamp,
            "trade_id": trade_id,
            "symbol": symbol,
            "direction": direction,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "pnl": round(pnl, 2),
            "balance": round(balance, 2),
            "exit_reason": exit_reason,
            "ticks_held": ticks_held,
            "spike_detected": spike_detected
        }
        
        trades = []
        if os.path.exists(self.json_path):
            try:
                with open(self.json_path, 'r') as f:
                    content = f.read().strip()
                    if content:
                        trades = json.loads(content)
            except Exception as e:
                self.log(f"Error reading JSON trade log: {e}", "WARNING")
                trades = []
                
        trades.append(trade_entry)
        
        try:
            with open(self.json_path, 'w') as f:
                json.dump(trades, f, indent=4)
        except Exception as e:
            self.log(f"Error writing to JSON trade log: {e}", "ERROR")

        self.log(f"TRADE LOGGED: {direction} on {symbol} -> PnL: ${pnl:.2f}, Balance: ${balance:.2f} ({exit_reason})", "SUCCESS")

    def save_session_metrics(self, total_trades: int, win_rate: float, net_profit: float, max_drawdown: float):
        """Saves current engine session statistics globally for easy state inspection."""
        metrics = {
            "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "total_trades": total_trades,
            "win_rate": round(win_rate, 4),
            "net_profit": round(net_profit, 2),
            "max_drawdown": round(max_drawdown, 2)
        }
        try:
            with open(self.metrics_path, 'w') as f:
                json.dump(metrics, f, indent=4)
        except Exception as e:
            self.log(f"Error saving session metrics: {e}", "ERROR")

