"""Who has actually been right.

The council argues about every trade and then forgets it. This file is the
memory the desk keeps instead: for each cabin, every settled call it made, what
it was worth in R, and whether its last few calls were right.

Three things read it:

* the head of desk, which gets the summary in its prompt (a desk that has been
  wrong about this regime should not out-shout one that has been right);
* the council, which discounts the confidence of a split decision when the
  desks voting for it are the ones with the poor record — the size comes down
  before the conviction does;
* the floor, which shows each cabin its own record next to its name.

Only *settled* trades count. A desk whose APPROVE made money is right; a desk
whose APPROVE lost money is wrong; the same the other way for REJECT. R is
measured against what the desk put at risk on that trade, not the account, so a
small position cannot flatter or damn a desk.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

#: Below this many settled calls a desk is simply unproven: no weight, no
#: penalty, no argument from history.
MIN_EVIDENCE = 4


class Scoreboard:
    def __init__(self) -> None:
        self.desk: Dict[str, Dict[str, float]] = {}

    # ------------------------------------------------------------------
    def _row(self, key: str) -> Dict[str, float]:
        return self.desk.setdefault(key, {
            "calls": 0.0, "right": 0.0, "approvals": 0.0,
            "wins": 0.0, "losses": 0.0, "r_sum": 0.0, "pnl": 0.0, "streak": 0.0,
        })

    def settle(self, key: str, verdict: str, pnl: float, risk: float = 0.0) -> None:
        """One closed trade, seen from one desk's point of view."""
        if verdict not in ("APPROVE", "REJECT") or not key:
            return
        row = self._row(key)
        r = (pnl / risk) if risk and risk > 0 else 0.0
        right = (verdict == "APPROVE") == (pnl > 0)
        row["calls"] += 1
        row["right"] += 1 if right else 0
        row["streak"] = row["streak"] + 1 if right else 0
        if verdict == "APPROVE":
            row["approvals"] += 1
            row["r_sum"] += r
            row["pnl"] += pnl
            if pnl > 0:
                row["wins"] += 1
            else:
                row["losses"] += 1

    # ------------------------------------------------------------------
    def hit_rate(self, key: str) -> Optional[float]:
        row = self.desk.get(key)
        if not row or row["calls"] < MIN_EVIDENCE:
            return None
        return row["right"] / row["calls"]

    def weight(self, key: str) -> float:
        """How much this desk's confidence is worth, 0.75..1.25.

        Unproven desks sit exactly at 1.0: the desk trusts nobody's history it
        has not seen, including a desk's *good* history.
        """
        rate = self.hit_rate(key)
        if rate is None:
            return 1.0
        return max(0.75, min(1.25, 0.75 + 0.5 * rate))

    def book_weight(self, keys: List[str]) -> float:
        """Average weight over the desks that carried a decision."""
        keys = [k for k in keys if k]
        if not keys:
            return 1.0
        return sum(self.weight(k) for k in keys) / len(keys)

    # ------------------------------------------------------------------
    def summary(self, keys: Optional[List[str]] = None) -> List[str]:
        """One line per desk, for the head of desk's prompt."""
        out: List[str] = []
        for key, row in self.desk.items():
            if keys and key not in keys:
                continue
            if row["calls"] < MIN_EVIDENCE:
                continue
            rate = row["right"] / row["calls"] * 100
            out.append(
                f"{key}: right on {row['right']:.0f}/{row['calls']:.0f} settled calls "
                f"({rate:.0f}%), approvals {row['approvals']:.0f} "
                f"({row['wins']:.0f}W/{row['losses']:.0f}L), {row['r_sum']:+.1f}R"
            )
        return out

    def snapshot(self) -> Dict[str, Any]:
        rows: Dict[str, Any] = {}
        for key, row in self.desk.items():
            calls = row["calls"] or 1
            rows[key] = {
                "calls": int(row["calls"]),
                "right": int(row["right"]),
                "hit_rate": round(row["right"] / calls, 3),
                "approvals": int(row["approvals"]),
                "wins": int(row["wins"]),
                "losses": int(row["losses"]),
                "r_sum": round(row["r_sum"], 2),
                "pnl": round(row["pnl"], 2),
                "streak": int(row["streak"]),
                "weight": round(self.weight(key), 3),
                "proven": row["calls"] >= MIN_EVIDENCE,
            }
        return {"desks": rows, "min_evidence": MIN_EVIDENCE}
