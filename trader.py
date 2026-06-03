# trader.py
"""
Simulated Paper Execution Engine
Tracks real-time active trades, performs exit audits (after N ticks or on spike capture),
calculates standard trading commission, pip differentials, and manages the virtual cash account.
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
        self.active_trade = None  # Tracks current open transaction dictionaries
        
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
        # 1. Update active open position trackers
        if self.active_trade:
            self._update_active_trade(current_price, analytics)
            return

        # 2. Check for entry conditions
        if decision == "HOLD":
            return

        # Query Risk Manager before entry
        can_trade, risk_reason = self.risk_manager.can_trade(self.balance)
        if not can_trade:
            self.logger.log(f"Entry Blocked by Risk Manager: {risk_reason}", "DEBUG")
            return

        # Establish simulated order parameters
        symbol = config.ACTIVE_SYMBOL
        lot_size = config.DEFAULT_LOT_SIZE
        
        self.active_trade = {
            "trade_id": str(uuid.uuid4())[:8],
            "symbol": symbol,
            "direction": decision,  # BUY or SELL
            "entry_price": current_price,
            "lot_size": lot_size,
            "ticks_held": 0,
            "entry_time": analytics.get("last_change", 0.0) # mock simulation timestamp placeholder
        }
        
        self.logger.log(
            f"OPENED PAPER POSITION: {decision} on {symbol} @ {current_price:.4f} (Lots: {lot_size}) "
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
        
        # Calculate current paper profit
        pnl = 0.0
        if direction == "BUY":
            pnl = (current_price - entry_price) * lot_size
        elif direction == "SELL":
            pnl = (entry_price - current_price) * lot_size
            
        # Determine exit conditions
        should_exit = False
        exit_reason = "Hold limit duration reached"
        spike_captured = False

        # exit limit check
        max_held_ticks = config.BOOM_EXIT_TICKS if "BOOM" in config.ACTIVE_SYMBOL else config.CRASH_EXIT_TICKS

        # 1. Did a spike occur during this tick?
        is_current_spike = analytics.get("is_current_spike", False)
        if is_current_spike:
            # Did the spike move in our expected direction?
            is_win = False
            last_change = analytics.get("last_change", 0.0)
            if direction == "BUY" and last_change > 0:
                is_win = True
            elif direction == "SELL" and last_change < 0:
                is_win = True
                
            if is_win:
                should_exit = True
                spike_captured = True
                exit_reason = "SPIKE CAPTURED! Profitable execution"
                # For spike captures, let's capture the immediate peak profit!
                # Boom/Crash spikes are fast, we simulate exit close to high tick
                pnl = (current_price - entry_price) * lot_size if direction == "BUY" else (entry_price - current_price) * lot_size

        # 2. Check hold threshold timeout
        if not should_exit and ticks_held >= max_held_ticks:
            should_exit = True
            exit_reason = f"Max exit timeout ({max_held_ticks} ticks passed)"

        # 3. If exit holds, close trade out
        if should_exit:
            self.balance += pnl
            self.total_trades += 1
            if pnl > 0:
                self.successful_trades += 1
                self.total_profit += pnl
            
            # Record metrics & logs
            self.risk_manager.record_trade_result(pnl)
            
            # Calculate drawdown metrics
            if self.balance > self.max_balance:
                self.max_balance = self.balance
            drawdown = (self.max_balance - self.balance) / self.max_balance if self.max_balance > 0 else 0.0
            if drawdown > self.max_drawdown:
                self.max_drawdown = drawdown

            # Log to csv/json
            self.logger.log_trade(
                trade_id=trade["trade_id"],
                symbol=trade["symbol"],
                direction=direction,
                entry_price=entry_price,
                exit_price=current_price,
                pnl=pnl,
                balance=self.balance,
                exit_reason=exit_reason,
                ticks_held=ticks_held,
                spike_detected=spike_captured
            )
            
            # Save stats
            win_rate = self.successful_trades / self.total_trades if self.total_trades > 0 else 0.0
            net_profit = self.balance - config.INITIAL_BALANCE
            self.logger.save_session_metrics(
                total_trades=self.total_trades,
                win_rate=win_rate,
                net_profit=net_profit,
                max_drawdown=self.max_drawdown
            )
            
            # Clear active trade
            self.active_trade = None

