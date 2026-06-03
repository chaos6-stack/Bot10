# risk_manager.py
"""
Risk Manager Module for the Synthetic Indices trading system.
Controls max trades, daily losses, consecutive streak limits, and cooldown timers
to ensure statistical discipline rather than gambling behaviors.
"""

from datetime import datetime, timedelta
import config
from logger import TradeLogger

class RiskManager:
    def __init__(self, logger: TradeLogger):
        self.logger = logger
        self.max_daily_loss = config.MAX_DAILY_LOSS
        self.max_trades = config.MAX_TRADES_PER_SESSION
        self.cooldown_streak = config.COOLDOWN_AFTER_LOSS_STREAK
        self.cooldown_minutes = config.COOLDOWN_MINUTES
        
        # Operational State
        self.session_trades_count = 0
        self.daily_pnl = 0.0
        self.consecutive_losses = 0
        self.cooldown_until = None
        self.loss_streak_active = False

    def record_trade_result(self, pnl: float):
        """Updates internal risk limits when a trade concludes."""
        self.session_trades_count += 1
        self.daily_pnl += pnl
        
        if pnl < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0
            # Reset cooldown if active and we won a trade (e.g. manually cleared or streak broken)
            self.loss_streak_active = False
            self.cooldown_until = None

        # Check for loss streak threshold
        if self.consecutive_losses >= self.cooldown_streak:
            self.cooldown_until = datetime.now() + timedelta(minutes=self.cooldown_minutes)
            self.loss_streak_active = True
            self.logger.log(
                f"LOSS STREAK PROTECTION TRIGGERED! {self.consecutive_losses} consecutive losses. "
                f"Trading locked out until {self.cooldown_until.strftime('%H:%M:%S')}", 
                "WARNING"
            )

    def is_in_cooldown(self) -> bool:
        """Helper to evaluate active streak locks."""
        if self.cooldown_until:
            if datetime.now() < self.cooldown_until:
                return True
            else:
                self.cooldown_until = None
                self.consecutive_losses = 0
                self.loss_streak_active = False
                self.logger.log("Cooldown period successfully ended. Trading re-enabled.", "INFO")
        return False

    def can_trade(self, current_balance: float) -> tuple[bool, str]:
        """
        Determines if a trade entry is globally permitted.
        Returns: (bool, reason)
        """
        # 1. Cooldown streak check
        if self.is_in_cooldown():
            time_left = self.cooldown_until - datetime.now()
            return False, f"Cooldown active: {time_left.seconds}s remaining"

        # 2. Limit maximum trades per session
        if self.session_trades_count >= self.max_trades:
            return False, f"Maximum session trades reached: {self.max_trades}"

        # 3. Limit daily dollar loss
        if self.daily_pnl <= -self.max_daily_loss:
            return False, f"Maximum daily loss exceeded: -${abs(self.daily_pnl):.2f} (Limit: -${self.max_daily_loss:.2f})"

        # 4. Check balance crash protection
        initial_balance = config.INITIAL_BALANCE
        drawdown_limit = initial_balance * config.MAX_DRAWDOWN_PCT
        current_drawdown = initial_balance - current_balance
        
        if current_drawdown >= drawdown_limit:
            return False, f"Maximum drawdown protection tripped: -${current_drawdown:.2f} (Limit: -${drawdown_limit:.2f})"

        # All clear!
        return True, "Trading permits active"

    def reset_daily_metrics(self):
        """Clears state for the next session or daily standard rollover."""
        self.session_trades_count = 0
        self.daily_pnl = 0.0
        self.consecutive_losses = 0
        self.cooldown_until = None
        self.loss_streak_active = False
        self.logger.log("Risk manager state reset completed.", "INFO")

