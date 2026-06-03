# backtester.py
"""
Backtesting Simulation Engine
Generates synthetic tick datasets with realistic Crash/Boom physics (steady drift + sudden spikes)
to safely evaluate Strategy and Risk settings offline before live virtual deployment.
"""

import csv
import os
import config
from logger import TradeLogger
from risk_manager import RiskManager
from strategy import SpikeStrategy
from trader import PaperTrader

def load_ticks_from_csv(file_path: str) -> list[float]:
    """Loads raw price ticks from a CSV file."""
    prices = []
    if not os.path.exists(file_path):
        print(f"⚠️ Warning: File {file_path} not found.")
        return []
    
    with open(file_path, mode='r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            prices.append(float(row['Price']))
    return prices

def run_backtest(symbol: str, tick_series: list[float] = None, 
                 spike_factor: float = None, rsi_buy: float = None) -> dict:
    """
    Simulates a session and tracks hypothetical performance metrics.
    Allows overriding key parameters for optimization.
    """
    # Temporarily override config for optimization if provided
    original_factor = config.SPIKE_THRESHOLD_FACTOR
    if spike_factor:
        config.SPIKE_THRESHOLD_FACTOR = spike_factor
    
    logger = TradeLogger()
    risk_manager = RiskManager(logger)
    trader = PaperTrader(logger, risk_manager)
    strategy = SpikeStrategy(symbol)
    
    if tick_series is None:
        csv_path = f"market_data/{symbol}_ticks.csv"
        tick_series = load_ticks_from_csv(csv_path)
        if not tick_series:
            return {}

    tick_buffer = []
    for current_price in tick_series:
        tick_buffer.append(current_price)
        if len(tick_buffer) < config.TICK_WINDOW_SIZE:
            continue
            
        decision, analytics = strategy.analyze_ticks(tick_buffer)
        
        # Override RSI if needed for optimization
        # (This is a simplified hook for optimization)
        
        trader.evaluate_decision(decision, current_price, analytics)
        
        if len(tick_buffer) > config.TICK_WINDOW_SIZE * 2:
            tick_buffer.pop(0)
            
    win_rate = trader.successful_trades / trader.total_trades if trader.total_trades > 0 else 0.0
    net_pnl = trader.balance - config.INITIAL_BALANCE
    
    # Restore original config
    config.SPIKE_THRESHOLD_FACTOR = original_factor
    
    return {
        "symbol": symbol,
        "total_trades": trader.total_trades,
        "win_rate": win_rate,
        "final_balance": trader.balance,
        "net_pnl": net_pnl,
        "max_drawdown": trader.max_drawdown
    }

def optimize_parameters(symbol: str):
    """Simple grid search for optimal Spike Threshold Factor."""
    print(f"\n--- Optimizing {symbol} ---")
    csv_path = f"market_data/{symbol}_ticks.csv"
    ticks = load_ticks_from_csv(csv_path)
    
    best_pnl = -9999
    best_params = {}
    
    # Search range for Spike Threshold Factor
    for factor in [3.5, 4.0, 4.5, 5.0, 5.5, 6.0]:
        res = run_backtest(symbol, tick_series=ticks, spike_factor=factor)
        pnl = res.get("net_pnl", 0)
        
        print(f"Factor: {factor:.1f} | Trades: {res['total_trades']} | PnL: ${pnl:+.2f} | WR: {res['win_rate']:.1%}")
        
        if pnl > best_pnl:
            best_pnl = pnl
            best_params = {"factor": factor, "results": res}
            
    print(f"\n✅ BEST FOR {symbol}: Factor {best_params['factor']} (PnL: ${best_pnl:+.2f})")
    return best_params

if __name__ == "__main__":
    for sym in ["BOOM1000", "CRASH1000"]:
        if os.path.exists(f"market_data/{sym}_ticks.csv"):
            optimize_parameters(sym)

