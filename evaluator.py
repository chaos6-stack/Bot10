# evaluator.py
"""
Strategy Evaluation Engine
Scores a completed backtest result set using a composite metric that weighs
win rate, profit factor, net profit, drawdown, and timeout ratio.
No external dependencies — pure Python.
"""

import json


class StrategyEvaluator:

    def __init__(self, data):
        self.trades = []
        self.load_data(data)

    def load_data(self, data):
        try:
            if isinstance(data, str):
                self.trades = json.loads(data)
            elif isinstance(data, list):
                self.trades = [t for t in data if isinstance(t, dict)]
            else:
                self.trades = []
        except Exception:
            self.trades = []

    # --- Core metrics ---

    def win_rate(self) -> float:
        if not self.trades:
            return 0.0
        wins = sum(1 for t in self.trades if float(t.get("pnl", 0.0)) > 0)
        return wins / len(self.trades)

    def net_profit(self) -> float:
        return sum(float(t.get("pnl", 0.0)) for t in self.trades)

    def profit_factor(self) -> float:
        gross_wins = sum(float(t.get("pnl", 0.0)) for t in self.trades if float(t.get("pnl", 0.0)) > 0)
        gross_losses = abs(sum(float(t.get("pnl", 0.0)) for t in self.trades if float(t.get("pnl", 0.0)) < 0))
        if gross_losses == 0:
            return float(gross_wins) if gross_wins > 0 else 1.0
        return gross_wins / gross_losses

    # --- Risk metrics ---

    def max_drawdown(self) -> float:
        equity = 0.0
        peak = 0.0
        max_dd = 0.0
        for t in self.trades:
            equity += float(t.get("pnl", 0.0))
            peak = max(peak, equity)
            max_dd = max(max_dd, peak - equity)
        return max_dd

    def avg_ticks_held(self) -> float:
        if not self.trades:
            return 0.0
        return sum(float(t.get("ticks_held", 0)) for t in self.trades) / len(self.trades)

    def timeout_exit_ratio(self) -> float:
        if not self.trades:
            return 0.0
        timeouts = sum(1 for t in self.trades if "timeout" in str(t.get("exit_reason", "")).lower())
        return timeouts / len(self.trades)

    def spike_capture_ratio(self) -> float:
        if not self.trades:
            return 0.0
        spikes = sum(1 for t in self.trades if t.get("spike_detected", False))
        return spikes / len(self.trades)

    def loss_streak(self) -> int:
        max_streak = 0
        current = 0
        for t in self.trades:
            if float(t.get("pnl", 0.0)) < 0:
                current += 1
                max_streak = max(max_streak, current)
            else:
                current = 0
        return max_streak

    # --- Composite scoring (0–100) ---

    def strategy_score(self) -> float:
        """
        Composite score weighing:
          Win Rate        40 pts  — most important
          Profit Factor   25 pts  — quality of wins vs losses
          Net Profit      15 pts  — absolute result
          Max Drawdown   -15 pts  — risk penalty
          Timeout Ratio  -10 pts  — too many timeouts = bad entries
          Spike Captures  +5 pts  — bonus for actual spike catches
        """
        if not self.trades:
            return 0.0

        wr = self.win_rate()
        pf = min(self.profit_factor(), 5.0) / 5.0
        np_ = self.net_profit()
        dd = self.max_drawdown()
        to = self.timeout_exit_ratio()
        sc = self.spike_capture_ratio()

        score_wr = wr * 40.0
        score_pf = pf * 25.0
        score_np = max(min(np_ / 500.0, 1.0), -1.0) * 15.0
        score_dd = -min(dd / 500.0, 1.0) * 15.0
        score_to = -to * 10.0
        score_sc = sc * 5.0

        raw = score_wr + score_pf + score_np + score_dd + score_to + score_sc
        return float(round(max(0.0, min(100.0, 50.0 + raw)), 2))

    def full_report(self) -> dict:
        total = len(self.trades)
        if total == 0:
            return {k: 0 for k in [
                "total_trades", "win_rate", "net_profit", "profit_factor",
                "max_drawdown", "avg_ticks_held", "timeout_ratio",
                "spike_capture_ratio", "loss_streak", "score"
            ]}
        return {
            "total_trades": total,
            "win_rate": round(self.win_rate(), 4),
            "net_profit": round(self.net_profit(), 2),
            "profit_factor": round(self.profit_factor(), 2),
            "max_drawdown": round(self.max_drawdown(), 2),
            "avg_ticks_held": round(self.avg_ticks_held(), 1),
            "timeout_ratio": round(self.timeout_exit_ratio(), 4),
            "spike_capture_ratio": round(self.spike_capture_ratio(), 4),
            "loss_streak": self.loss_streak(),
            "score": self.strategy_score()
        }
