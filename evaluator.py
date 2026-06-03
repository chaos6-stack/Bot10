import json
import pandas as pd


class StrategyEvaluator:

    def __init__(self, data):
        self.trades = []
        self.load_data(data)

    # -----------------------------
    # DATA LOADING (ROBUST LAYER)
    # -----------------------------
    def load_data(self, data):
        try:
            if isinstance(data, str):
                self.trades = json.loads(data)

            elif hasattr(data, "to_dict") and callable(getattr(data, "to_dict")):
                self.trades = data.to_dict(orient="records")

            elif isinstance(data, list):
                self.trades = [t for t in data if isinstance(t, dict)]

            else:
                self.trades = []

        except Exception:
            self.trades = []

    # -----------------------------
    # CORE METRICS
    # -----------------------------
    def win_rate(self):
        if not self.trades:
            return 0.0
        wins = sum(1 for t in self.trades if float(t.get("profit", 0.0)) > 0)
        return wins / len(self.trades)

    def net_profit(self):
        return sum(float(t.get("profit", 0.0)) for t in self.trades)

    def profit_factor(self):
        if not self.trades:
            return 0.0

        wins = sum(float(t.get("profit", 0.0)) for t in self.trades if float(t.get("profit", 0.0)) > 0)
        losses = abs(sum(float(t.get("profit", 0.0)) for t in self.trades if float(t.get("profit", 0.0)) < 0))

        if losses == 0:
            return float(wins) if wins > 0 else 1.0

        return wins / losses

    # -----------------------------
    # RISK METRICS
    # -----------------------------
    def max_drawdown(self):
        if not self.trades:
            return 0.0

        equity = 0.0
        peak = 0.0
        max_dd = 0.0

        for t in self.trades:
            equity += float(t.get("profit", 0.0))
            peak = max(peak, equity)
            max_dd = max(max_dd, peak - equity)

        return max_dd

    def avg_trade_duration(self):
        if not self.trades:
            return 0.0

        durations = [float(t.get("duration", 0)) for t in self.trades]
        return sum(durations) / len(durations)

    # -----------------------------
    # STRATEGY HEALTH METRICS
    # -----------------------------
    def timeout_exit_ratio(self):
        if not self.trades:
            return 0.0

        timeouts = sum(
            1 for t in self.trades
            if str(t.get("exit_reason", "")).lower() == "timeout"
        )
        return timeouts / len(self.trades)

    def trade_frequency(self):
        return len(self.trades)

    def loss_streak(self):
        max_streak = 0
        current = 0

        for t in self.trades:
            if float(t.get("profit", 0.0)) < 0:
                current += 1
                max_streak = max(max_streak, current)
            else:
                current = 0

        return max_streak

    # -----------------------------
    # FINAL SCORE ENGINE (HYBRID)
    # -----------------------------
    def strategy_score(self):
        if not self.trades:
            return 0.0

        wr = self.win_rate()
        pf = min(self.profit_factor(), 5.0) / 5.0
        np = self.net_profit()
        dd = self.max_drawdown()
        to = self.timeout_exit_ratio()

        # Core performance
        score_wr = wr * 40.0
        score_pf = pf * 25.0

        # Profit scaling (stable normalization)
        score_np = max(min(np / 500.0, 1.0), -1.0) * 15.0

        # Risk penalty
        score_dd = -min(dd / 500.0, 1.0) * 15.0

        # Execution quality penalty
        score_to = -to * 10.0

        raw = score_wr + score_pf + score_np + score_dd + score_to

        # Normalize to 0–100
        return float(round(max(0.0, min(100.0, 50.0 + raw)), 2))

    # -----------------------------
    # FULL REPORT
    # -----------------------------
    def full_report(self):
        total = len(self.trades)

        if total == 0:
            return {
                "total_trades": 0,
                "win_rate": 0.0,
                "net_profit": 0.0,
                "profit_factor": 0.0,
                "max_drawdown": 0.0,
                "avg_trade_duration": 0.0,
                "timeout_ratio": 0.0,
                "loss_streak": 0,
                "score": 0.0
            }

        return {
            "total_trades": total,
            "win_rate": round(self.win_rate(), 4),
            "net_profit": round(self.net_profit(), 2),
            "profit_factor": round(self.profit_factor(), 2),
            "max_drawdown": round(self.max_drawdown(), 2),
            "avg_trade_duration": round(self.avg_trade_duration(), 2),
            "timeout_ratio": round(self.timeout_exit_ratio(), 4),
            "loss_streak": self.loss_streak(),
            "score": self.strategy_score()
        }
