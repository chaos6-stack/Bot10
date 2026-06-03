# main.py
"""
Synthetic Indices Trading Agent - Main Orchestrator
Binds real-time stream ticks, runs indicators, triggers strategies,
enforces risk controls, and executes virtual paper trades.
"""

import sys
import time
from logger import TradeLogger
from risk_manager import RiskManager
from trader import PaperTrader
from strategy import SpikeStrategy
from data_stream import DerivDataStream
import config


class SyntheticTradingBot:
    def __init__(self):
        self.logger       = TradeLogger()
        self.risk_manager = RiskManager(self.logger)
        self.trader       = PaperTrader(self.logger, self.risk_manager)
        self.strategy     = SpikeStrategy(config.ACTIVE_SYMBOL)
        self.stream       = None
        self.tick_buffer  = []
        self.tick_counter = 0

    def print_banner(self):
        banner = f"""
============================================================
   █▀▀ █▄█ █▄░█ ▀█▀ █░█ █▀▀ ▀█▀ █ █▀▀ █▀█ █▀█ ▀█▀
   ▄██ ░█░ █░▀█ ░█░ █▀█ ██▄ ░█░ █ █▄▄ █▀▄ █▄█ ░█░
       AI-ASSISTED SYNTHETIC INDICES TRADING AGENT
============================================================
  Symbol  : {config.ACTIVE_SYMBOL}          Virt Balance : ${self.trader.balance:.2f}
  Risk    : Max Daily Loss ${config.MAX_DAILY_LOSS:.0f}  Drawdown cap {config.MAX_DRAWDOWN_PCT*100:.0f}%
  Cycle   : {config.SPIKE_CYCLE_LENGTH} ticks   Lot Scaling  : {'ON' if config.CYCLE_LOT_SCALING else 'OFF'} (max {config.CYCLE_MAX_LOT_SCALE}x)
  SL/TP   : {config.STOP_LOSS_POINTS} pts / {config.TAKE_PROFIT_POINTS} pts   Exit Ticks   : {config.BOOM_EXIT_TICKS}
============================================================
[SYSTEM] Starting state engines. Press Ctrl+C to stop...
"""
        print(banner)

    def handle_tick(self, price: float, timestamp: int):
        """Callback executed on every incoming tick from the stream."""
        self.tick_counter += 1
        self.tick_buffer.append(price)

        # Rolling buffer — keep 2× window size for indicator accuracy
        if len(self.tick_buffer) > config.TICK_WINDOW_SIZE * 2:
            self.tick_buffer.pop(0)

        # Warm-up period
        if self.tick_counter <= config.TICK_WINDOW_SIZE:
            if self.tick_counter % 5 == 0:
                print(
                    f"[SYSTEM] Warming up indicators... "
                    f"({self.tick_counter}/{config.TICK_WINDOW_SIZE})"
                )
            return

        if len(self.tick_buffer) < config.TICK_WINDOW_SIZE:
            return

        # Run strategy
        decision, analytics = self.strategy.analyze_ticks(self.tick_buffer)

        # ── Console diagnostic every 5 ticks ─────────────────────────────
        if self.tick_counter % 5 == 0:
            zone        = analytics.get("cycle_zone", "?")
            ticks_spike = analytics.get("ticks_since_spike", 0)
            cycle_pct   = analytics.get("cycle_position", 0) * 100
            lot_scale   = analytics.get("cycle_lot_scale", 1.0)
            mult        = analytics.get("cycle_multiplier", 1.0)

            if self.trader.active_trade:
                t = self.trader.active_trade
                pos_str = (
                    f"{t['direction']} x{t['lot_size']} "
                    f"(held {t['ticks_held']}tk @ {t['entry_price']:.3f})"
                )
            else:
                pos_str = "NONE"

            print(
                f"[#{self.tick_counter:>5}] "
                f"Price: {price:.3f}  "
                f"RSI: {analytics.get('rsi', 0):.1f}  "
                f"Sqz: {analytics.get('compression_ratio', 1):.2f}  "
                f"Cycle: {ticks_spike}tk/{cycle_pct:.0f}% [{zone}] {mult:.2f}x"
                + (f" lots:{lot_scale:.2f}" if lot_scale != 1.0 else "")
                + f"  Pos: {pos_str}"
            )

        # ── Execute trade decision ────────────────────────────────────────
        self.trader.evaluate_decision(decision, price, analytics)

    def run(self):
        self.print_banner()
        self.stream = DerivDataStream(
            symbol=config.ACTIVE_SYMBOL,
            on_tick_callback=self.handle_tick
        )
        self.stream.start()

        try:
            while True:
                time.sleep(1)
        except (KeyboardInterrupt, SystemExit):
            self.shutdown()

    def shutdown(self):
        print("\n[SYSTEM] Shutting down safely...")
        if self.stream:
            self.stream.stop()

        # Print final session summary
        wr  = self.trader.successful_trades / self.trader.total_trades \
              if self.trader.total_trades > 0 else 0.0
        pnl = self.trader.balance - config.INITIAL_BALANCE
        print(
            f"\n[SESSION SUMMARY]\n"
            f"  Trades       : {self.trader.total_trades}\n"
            f"  Win Rate     : {wr*100:.1f}%\n"
            f"  Net PnL      : ${pnl:+.2f}\n"
            f"  Final Balance: ${self.trader.balance:.2f}\n"
            f"  Spikes seen  : {self.strategy.total_spikes_observed}\n"
        )
        sys.exit(0)


if __name__ == "__main__":
    bot = SyntheticTradingBot()
    bot.run()
