# trader.py
"""
Simulated Paper Execution Engine
Tracks real-time active trades, performs exit audits (stop-loss, take-profit,
spike capture, or tick timeout), applies cycle-aware lot sizing, and manages
the virtual cash account.
"""

import uuid
import config
from logger import TradeLogger
from risk_manager import RiskManager


class PaperTrader:
    def __init__(self, logger: TradeLogger, risk_manager: RiskManager):
        self.logger       = logger
        self.risk_manager = risk_manager
        self.balance      = config.INITIAL_BALANCE
        self.active_trade = None

        # Session performance
        self.total_trades     = 0
        self.successful_trades = 0
        self.total_profit     = 0.0
        self.max_balance      = self.balance
        self.max_drawdown     = 0.0

        # Post-trade cooldown: prevents immediately re-entering after a close
        self.ticks_since_last_close = config.POST_TRADE_COOLDOWN_TICKS  # start ready

    # ─────────────────────────────────────────────────────────────────────
    #  ENTRY
    # ─────────────────────────────────────────────────────────────────────

    def evaluate_decision(self, decision: str, current_price: float, analytics: dict):
        """Routes tick to position management or entry evaluation."""

        # Always update open trade first
        if self.active_trade:
            self._update_active_trade(current_price, analytics)
            return

        # Increment post-trade cooldown counter when flat
        self.ticks_since_last_close += 1

        if decision == "HOLD":
            return

        # Post-trade cooldown gate
        if self.ticks_since_last_close < config.POST_TRADE_COOLDOWN_TICKS:
            remaining = config.POST_TRADE_COOLDOWN_TICKS - self.ticks_since_last_close
            self.logger.log(
                f"Cooldown: {remaining} ticks remaining before next entry", "DEBUG"
            )
            return

        # Risk Manager gate
        can_trade, risk_reason = self.risk_manager.can_trade(self.balance)
        if not can_trade:
            self.logger.log(f"Entry Blocked by Risk Manager: {risk_reason}", "DEBUG")
            return

        # ── Cycle-aware lot sizing ────────────────────────────────────────
        # When a spike is statistically overdue, we scale up the lot size
        # (up to CYCLE_MAX_LOT_SCALE × DEFAULT_LOT_SIZE) to earn more from
        # the bigger-probability spike capture.
        cycle_scale = analytics.get("cycle_lot_scale", 1.0)
        lot_size    = round(config.DEFAULT_LOT_SIZE * cycle_scale, 2)
        lot_size    = max(config.MIN_LOT_SIZE, lot_size)   # floor at minimum
        cycle_zone  = analytics.get("cycle_zone", "UNKNOWN")
        cycle_ticks = analytics.get("ticks_since_spike", 0)

        self.active_trade = {
            "trade_id":    str(uuid.uuid4())[:8],
            "symbol":      config.ACTIVE_SYMBOL,
            "direction":   decision,
            "entry_price": current_price,
            "lot_size":    lot_size,
            "ticks_held":  0,
            "peak_pnl":    0.0,
        }

        self.logger.log(
            f"OPENED {decision} {config.ACTIVE_SYMBOL} @ {current_price:.4f} | "
            f"Lots: {lot_size} (scale {cycle_scale:.2f}x) | "
            f"Zone: {cycle_zone} ({cycle_ticks} ticks since spike) | "
            f"Reason: {analytics.get('decision_reason', '?')}",
            "ORDER"
        )

    # ─────────────────────────────────────────────────────────────────────
    #  POSITION MANAGEMENT
    # ─────────────────────────────────────────────────────────────────────

    def _update_active_trade(self, current_price: float, analytics: dict):
        """Evaluates exit conditions every tick while a trade is open."""
        trade      = self.active_trade
        trade["ticks_held"] += 1
        ticks_held = trade["ticks_held"]
        direction  = trade["direction"]
        entry      = trade["entry_price"]
        lot        = trade["lot_size"]

        # Current unrealised PnL
        pnl = (current_price - entry) * lot if direction == "BUY" \
              else (entry - current_price) * lot

        if pnl > trade["peak_pnl"]:
            trade["peak_pnl"] = pnl

        max_held     = config.BOOM_EXIT_TICKS if "BOOM" in config.ACTIVE_SYMBOL \
                       else config.CRASH_EXIT_TICKS
        should_exit  = False
        exit_reason  = "Tick timeout"
        spike_cap    = False

        # ── Exit Rule 1: Stop-loss ────────────────────────────────────────
        if pnl <= -config.STOP_LOSS_POINTS * lot:
            should_exit = True
            exit_reason = f"Stop-loss hit ({pnl:.4f})"

        # ── Exit Rule 2: Take-profit ──────────────────────────────────────
        elif pnl >= config.TAKE_PROFIT_POINTS * lot:
            should_exit = True
            exit_reason = f"Take-profit hit ({pnl:.4f})"

        # ── Exit Rule 3: Spike in our direction ───────────────────────────
        elif analytics.get("is_current_spike", False):
            last_chg = analytics.get("last_change", 0.0)
            good_spike = (direction == "BUY"  and last_chg > 0) or \
                         (direction == "SELL" and last_chg < 0)
            if good_spike:
                should_exit = True
                spike_cap   = True
                exit_reason = "SPIKE CAPTURED"
            elif pnl < 0:
                # Spike went the wrong way — cut the loss immediately
                should_exit = True
                exit_reason = "Adverse spike — cutting loss"

        # ── Exit Rule 4: Tick timeout ────────────────────────────────────
        elif ticks_held >= max_held:
            should_exit = True
            exit_reason = f"Timeout ({max_held} ticks)"

        if should_exit:
            self._close_trade(current_price, pnl, exit_reason, spike_cap, ticks_held)

    # ─────────────────────────────────────────────────────────────────────
    #  TRADE CLOSE
    # ─────────────────────────────────────────────────────────────────────

    def _close_trade(self, exit_price: float, pnl: float, exit_reason: str,
                     spike_captured: bool, ticks_held: int):
        """Closes the active trade, updates account, logs everything."""
        trade   = self.active_trade
        is_win  = pnl > 0
        result  = "WIN " if is_win else "LOSS"

        self.balance += pnl
        self.total_trades += 1
        if is_win:
            self.successful_trades += 1
            self.total_profit += pnl

        self.risk_manager.record_trade_result(pnl)

        if self.balance > self.max_balance:
            self.max_balance = self.balance
        drawdown = (self.max_balance - self.balance) / self.max_balance \
                   if self.max_balance > 0 else 0.0
        if drawdown > self.max_drawdown:
            self.max_drawdown = drawdown

        win_rate = self.successful_trades / self.total_trades \
                   if self.total_trades > 0 else 0.0

        self.logger.log(
            f"CLOSED [{result}] {trade['direction']} {trade['symbol']} | "
            f"Entry: {trade['entry_price']:.4f} → {exit_price:.4f} | "
            f"PnL: {pnl:+.4f} (lots {trade['lot_size']}) | "
            f"Ticks: {ticks_held} | {exit_reason} | "
            f"Balance: ${self.balance:.2f} | WR: {win_rate*100:.1f}%",
            "ORDER"
        )

        self.logger.log_trade(
            trade_id      = trade["trade_id"],
            symbol        = trade["symbol"],
            direction     = trade["direction"],
            entry_price   = trade["entry_price"],
            exit_price    = exit_price,
            pnl           = pnl,
            balance       = self.balance,
            exit_reason   = exit_reason,
            ticks_held    = ticks_held,
            spike_detected= spike_captured
        )

        self.logger.save_session_metrics(
            total_trades = self.total_trades,
            win_rate     = win_rate,
            net_profit   = self.balance - config.INITIAL_BALANCE,
            max_drawdown = self.max_drawdown
        )

        self.active_trade = None
        self.ticks_since_last_close = 0   # start post-trade cooldown timer
