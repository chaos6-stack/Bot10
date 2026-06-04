# evaluator.py
"""
Strategy Evaluation Engine — v2 (Recalibrated Score Formula)
Scores a completed backtest result set using a composite metric.

v2 changes vs v1:
  - Removed the 50-point base offset that kept ALL strategies near 50.
    The old formula: return 50 + raw  made the effective search range ~45–60,
    meaning the optimizer was differentiating noise, not real edge.
  - Recalibrated normalisation constants to match actual achievable ranges
    on an 8,000-tick BOOM/CRASH1000 run so the score spans a meaningful 0–100.
  - A random-entry strategy now scores ~8–12; a good cycle strategy ~45–65.
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

    # ── Core metrics ──────────────────────────────────────────────────────────

    def win_rate(self) -> float:
        if not self.trades:
            return 0.0
        wins = sum(1 for t in self.trades if float(t.get("pnl", 0.0)) > 0)
        return wins / len(self.trades)

    def net_profit(self) -> float:
        return sum(float(t.get("pnl", 0.0)) for t in self.trades)

    def profit_factor(self) -> float:
        gross_wins   = sum(float(t.get("pnl", 0.0)) for t in self.trades if float(t.get("pnl", 0.0)) > 0)
        gross_losses = abs(sum(float(t.get("pnl", 0.0)) for t in self.trades if float(t.get("pnl", 0.0)) < 0))
        if gross_losses == 0:
            return float(gross_wins) if gross_wins > 0 else 1.0
        return gross_wins / gross_losses

    # ── Risk metrics ──────────────────────────────────────────────────────────

    def max_drawdown(self) -> float:
        equity = 0.0
        peak   = 0.0
        max_dd = 0.0
        for t in self.trades:
            equity += float(t.get("pnl", 0.0))
            peak    = max(peak, equity)
            max_dd  = max(max_dd, peak - equity)
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
        current    = 0
        for t in self.trades:
            if float(t.get("pnl", 0.0)) < 0:
                current   += 1
                max_streak = max(max_streak, current)
            else:
                current = 0
        return max_streak

    # ── Composite score (0–100) ───────────────────────────────────────────────

    def strategy_score(self) -> float:
        """
        Recalibrated composite score (v2).

        Normalisation constants are calibrated to achievable ranges on an
        8,000-tick BOOM/CRASH1000 run (~100–250 trades depending on params):

          Win Rate   (0–50 pts)  — practical BOOM range 0.10–0.30
          Profit Factor (0–25)   — practical range 0.3–3.0; PF=1.0 = breakeven
          Net Profit (−15–+15)   — normalised to ±$150 over the run
          Max Drawdown (−15–0)   — penalised up to $300 drawdown
          Timeout Ratio (−15–0)  — high timeouts = poor entry timing
          Spike Captures (0–10)  — bonus for actual spike catches

        Score interpretation:
          0 – 10  : worse than random entry
          10 – 25 : marginal / likely overfitting
          25 – 45 : reasonable but needs improvement
          45 – 65 : good — genuine edge
          65+     : excellent (rare on BOOM/CRASH without real data)

        Formula change vs v1:
          NO 50-point base. Zero score now actually means zero edge.
          This spreads the optimizer search space from ~45–55 (near-constant)
          to a meaningful 0–100 range so parameter differences are detectable.
        """
        if not self.trades:
            return 0.0

        wr  = self.win_rate()
        pf  = self.profit_factor()
        np_ = self.net_profit()
        dd  = self.max_drawdown()
        to  = self.timeout_exit_ratio()
        sc  = self.spike_capture_ratio()

        # Win rate: normalised so 0.10 = 16.7pts, 0.25 = 41.7pts, 0.30 = 50pts
        score_wr = min(wr / 0.30, 1.0) * 50.0

        # Profit factor: PF=1.0 → 8.3pts, PF=2.0 → 16.7pts, PF=3.0 → 25pts
        score_pf = min(pf / 3.0, 1.0) * 25.0

        # Net profit: +$150 → +15pts, −$150 → −15pts
        score_np = max(min(np_ / 150.0, 1.0), -1.0) * 15.0

        # Max drawdown penalty: $300 → −15pts
        score_dd = -min(dd / 300.0, 1.0) * 15.0

        # Timeout penalty: 100% timeouts → −15pts (indicates bad entry timing)
        score_to = -to * 15.0

        # Spike capture bonus: 50% captures → +5pts
        score_sc = sc * 10.0

        raw = score_wr + score_pf + score_np + score_dd + score_to + score_sc
        return float(round(max(0.0, min(100.0, raw)), 2))

    def full_report(self) -> dict:
        total = len(self.trades)
        if total == 0:
            return {k: 0 for k in [
                "total_trades", "win_rate", "net_profit", "profit_factor",
                "max_drawdown", "avg_ticks_held", "timeout_ratio",
                "spike_capture_ratio", "loss_streak", "score"
            ]}
        return {
            "total_trades":        total,
            "win_rate":            round(self.win_rate(),            4),
            "net_profit":          round(self.net_profit(),          2),
            "profit_factor":       round(self.profit_factor(),       2),
            "max_drawdown":        round(self.max_drawdown(),        2),
            "avg_ticks_held":      round(self.avg_ticks_held(),      1),
            "timeout_ratio":       round(self.timeout_exit_ratio(),  4),
            "spike_capture_ratio": round(self.spike_capture_ratio(), 4),
            "loss_streak":         self.loss_streak(),
            "score":               self.strategy_score(),
        }
