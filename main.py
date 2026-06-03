# main.py
"""
Synthetic Indices Trading Agent - Main Orchestrator
Binds real-time stream ticks, runs indicators, triggers strategies,
enforces risk controls, and executes virtual paper trades on Termux / Android CLI.
"""

import sys
import time
import signal
from logger import TradeLogger
from risk_manager import RiskManager
from trader import PaperTrader
from strategy import SpikeStrategy
from data_stream import DerivDataStream
import config

class SyntheticTradingBot:
    def __init__(self):
        self.logger = TradeLogger()
        self.risk_manager = RiskManager(self.logger)
        self.trader = PaperTrader(self.logger, self.risk_manager)
        self.strategy = SpikeStrategy(config.ACTIVE_SYMBOL)
        self.stream = None
        self.tick_buffer = []
        self.tick_counter = 0

    def print_banner(self):
        """Displays decorative systems architect ASCI engineering banner."""
        banner = f"""
============================================================
   █▀▀ █▄█ █▄░█ ▀█▀ █░█ █▀▀ ▀█▀ █ █▀▀ █▀█ █▀█ ▀█▀
   ▄██ ░█░ █░▀█ ░█░ █▀█ ██▄ ░█░ █ █▄▄ █▀▄ █▄█ ░█░
       AI-ASSISTED SYNTHETIC INDICES TRADING AGENT
============================================================
  🎯 Symbol: {config.ACTIVE_SYMBOL} | Virt Balance: ${self.trader.balance:.2f}
  🛡️ Risk Guard: Max Daily Loss = ${config.MAX_DAILY_LOSS:.2f}
  🔧 Strategy: Multi-Squeeze Spike Breakout Detector
  📱 Target: Android Termux / WebView CLI Architecture
============================================================
[SYSTEM] Starting state engines. Press Ctrl+C to stop...
"""
        print(banner)

    def handle_tick(self, price: float, timestamp: int):
        """
        Callback handler executed upon receiving a new tick from the stream.
        """
        self.tick_counter += 1
        self.tick_buffer.append(price)
        
        # Enforce memory constraint limits on the buffer
        if len(self.tick_buffer) > config.TICK_WINDOW_SIZE * 2:
            self.tick_buffer.pop(0)

        # Skip logic until buffer has warmed up sufficiently
        if self.tick_counter <= config.TICK_WINDOW_SIZE:
            if self.tick_counter % 5 == 0:
                print(f"[SYSTEM] Warming up tick indicators... ({len(self.tick_buffer)}/{config.TICK_WINDOW_SIZE})")
            return

        # Double check types to be ultra sturdy
        if len(self.tick_buffer) < config.TICK_WINDOW_SIZE:
            return

        # Feed prices to standard technical analysis strategy
        decision, analytics = self.strategy.analyze_ticks(self.tick_buffer)
        
        # Output silent diagnostics to CLI every 5 ticks to avoid flood
        if self.tick_counter % 5 == 0:
            active_pos = "NONE"
            if self.trader.active_trade:
                t = self.trader.active_trade
                active_pos = f"{t['direction']} (Held {t['ticks_held']} ticks, Entry: {t['entry_price']:.3f})"
            
            print(
                f"[TICK #{self.tick_counter}] Price: {price:.3f} | "
                f"RSI: {analytics.get('rsi', 0.0):.1f} | "
                f"Squeeze Coeff: {analytics.get('compression_ratio', 1.0):.2f} | "
                f"Position: {active_pos}"
            )

        # Dispatch indicators and strategy verdicts to paper trader
        self.trader.evaluate_decision(decision, price, analytics)

    def run(self):
        self.print_banner()
        
        # Establish subscription ticks connection
        self.stream = DerivDataStream(
            symbol=config.ACTIVE_SYMBOL,
            on_tick_callback=self.handle_tick
        )
        
        # Launch websocket listener thread
        self.stream.start()
        
        # Keep main thread alive & listen for console signals
        try:
            while True:
                time.sleep(1)
        except (KeyboardInterrupt, SystemExit):
            self.shutdown()

    def shutdown(self):
        print("\n\n[SYSTEM] Received termination request. Gritting down sockets safely...")
        if self.stream:
            self.stream.stop()
        print("[SYSTEM] Trading system shutdown complete. Fair winds!")
        sys.exit(0)

if __name__ == "__main__":
    # Standard executable hook
    bot = SyntheticTradingBot()
    bot.run()

