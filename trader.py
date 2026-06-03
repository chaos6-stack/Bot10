# trader.py
"""
Simulated Paper Execution Engine
Tracks real-time active trades, performs exit audits (spike capture, stop-loss,
take-profit, or tick timeout), calculates PnL, and manages the virtual cash account.
"""

import uuid
import config
from logger import TradeLogger
from risk_manager import RiskManager

class PaperTrader:
    def __init__(self, logger: TradeLogger, risk_manager: RiskManager):
        self.logger = logger
        self.risk_manager = risk_manager
        self.balance = config.INITIAL_BALANCE
        self.active_trade = None

        # Performance Tracking
        self.total_trades = 0
        self.successful_trades = 0
        self.total_profit = 0.0
        self.max_balance = self.balance
        self.max_drawdown = 0.0

    def evaluate_decision(self, decision: str, current_price: float, analytics: dict):
        """
        Processes strategy signals and updates any active open paper-trading positions.
        """
        # 1. Update active open position
        if self.active_trade:
            self._update_active_trade(current_price, analytics)
            return

        # 2. Only act on BUY / SELL signals
        if decision == "HOLD":
            return

        # 3. Risk Manager gate
        can_trade, risk_reason = self.risk_manager.can_trade(self.balance)
        if not can_trade:
            self.logger.log(f"Entry Blocked by Risk Manager: {risk_reason}", "DEBUG")
            return

        # 4. Open position
        self.active_trade = {
            "trade_id": str(uuid.uuid4())[:8],
            "symbol": config.ACTIVE_SYMBOL,
            "direction": decision,
            "entry_price": current_price,
            "lot_size": config.DEFAULT_LOT_SIZE,
            "ticks_held": 0,
            "peak_pnl": 0.0,    # tracks best unrealised PnL for reporting
        }

        self.logger.log(
            f"OPENED PAPER POSITION: {decision} on {config.ACTIVE_SYMBOL} "
            f"@ {current_price:.4f} (Lots: {config.DEFAULT_LOT_SIZE}) "
            f"[Reason: {analytics.get('decision_reason', 'Unspecified')}]",
            "ORDER"
        )

    def _update_active_trade(self, current_price: float, analytics: dict):
        """Monitors tick progression while a trade is open."""
        trade = self.active_trade
        trade["ticks_held"] += 1
        ticks_held = trade["ticks_held"]

        direction = trade["direction"]
        entry_price = trade["entry_price"]
        lot_size = trade["lot_size"]

        # Current unrealised PnL
        if direction == "BUY":
            pnl = (current_price - entry_price) * lot_size
        else:
            pnl = (entry_price - current_price) * lot_size

        # Track peak profit for diagnostics
        if pnl > trade["peak_pnl"]:
            trade["peak_pnl"] = pnl

        should_exit = False
        exit_reason = "Tick timeout"
        spike_captured = False

        max_held = config.BOOM_EXIT_TICKS if "BOOM" in config.ACTIVE_SYMBOL else config.CRASH_EXIT_TICKS

        # --- EXIT RULE 1: Stop Loss ---
        stop_loss_threshold = -config.STOP_LOSS_POINTS * lot_size
        if pnl <= stop_loss_threshold:
            should_exit = True
            exit_reason = f"Stop-loss hit (loss: {pnl:.4f})"

        # --- EXIT RULE 2: Take Profit ---
        elif pnl >= config.TAKE_PROFIT_POINTS * lot_size:
            should_exit = True
            exit_reason = f"Take-profit hit (profit: {pnl:.4f})"

        # --- EXIT RULE 3: Spike Captured ---
        elif analytics.get("is_current_spike", False):
            last_change = analytics.get("last_change", 0.0)
            spike_in_our_direction = (
                (direction == "BUY" and last_change > 0) or
                (direction == "SELL" and last_change < 0)
            )
            if spike_in_our_direction:
                should_exit = True
                spike_captured = True
                exit_reason = "SPIKE CAPTURED — profitable execution"
            elif pnl < 0:
                # Spike went against us — cut loss now
                should_exit = True
                exit_reason = "Adverse spike — cutting loss"

        # --- EXIT RULE 4: Tick timeout ---
        elif ticks_held >= max_held:
            should_exit = True
            exit_reason = f"Timeout ({max_held} ticks)"

        if should_exit:
            self._close_trade(current_price, pnl, exit_reason, spike_captured, ticks_held)

    def _close_trade(self, exit_price: float, pnl: float, exit_reason: str,
                     spike_captured: bool, ticks_held: int):
        """Closes the active trade, updates balance and metrics."""
        trade = self.active_trade

        self.balance += pnl
        self.total_trades += 1
        is_win = pnl > 0
        if is_win:
            self.successful_trades += 1
            self.total_profit += pnl

        self.risk_manager.record_trade_result(pnl)

        if self.balance > self.max_balance:
            self.max_balance = self.balance
        drawdown = (self.max_balance - self.balance) / self.max_balance if self.max_balance > 0 else 0.0
        if drawdown > self.max_drawdown:
            self.max_drawdown = drawdown

        win_rate = self.successful_trades / self.total_trades if self.total_trades > 0 else 0.0
        result_tag = "WIN" if is_win else "LOSS"

        self.logger.log(
            f"CLOSED [{result_tag}] {trade['direction']} {trade['symbol']} "
            f"Entry: {trade['entry_price']:.4f} → Exit: {exit_price:.4f} | "
            f"PnL: {pnl:+.4f} | Ticks: {ticks_held} | Reason: {exit_reason} | "
            f"Balance: ${self.balance:.2f} | Win Rate: {win_rate*100:.1f}%",
            "ORDER"
        )

        self.logger.log_trade(
            trade_id=trade["trade_id"],
            symbol=trade["symbol"],
            direction=trade["direction"],
            entry_price=trade["entry_price"],
            exit_price=exit_price,
            pnl=pnl,
            balance=self.balance,
            exit_reason=exit_reason,
            ticks_held=ticks_held,
            spike_detected=spike_captured
        )

        self.logger.save_session_metrics(
            total_trades=self.total_trades,
            win_rate=win_rate,
            net_profit=self.balance - config.INITIAL_BALANCE,
            max_drawdown=self.max_drawdown
        )

        self.active_trade = None
