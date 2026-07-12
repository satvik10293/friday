import sqlite3


class StatsEngine:

    def __init__(self, db_path="athena.db"):
        self.db_path = db_path

    def get_summary(self):

        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()

        cur.execute("""
        SELECT COUNT(*)
        FROM trades
        """)
        total = cur.fetchone()[0]

        cur.execute("""
        SELECT COUNT(*)
        FROM trades
        WHERE pnl > 0
        """)
        wins = cur.fetchone()[0]

        losses = total - wins

        cur.execute("""
        SELECT AVG(pnl)
        FROM trades
        WHERE pnl > 0
        """)
        avg_win = cur.fetchone()[0] or 0

        cur.execute("""
        SELECT AVG(pnl)
        FROM trades
        WHERE pnl <= 0
        """)
        avg_loss = cur.fetchone()[0] or 0

        cur.execute("""
        SELECT MAX(pnl)
        FROM trades
        """)
        best_trade = cur.fetchone()[0] or 0

        cur.execute("""
        SELECT MIN(pnl)
        FROM trades
        """)
        worst_trade = cur.fetchone()[0] or 0

        conn.close()

        win_rate = 0

        if total > 0:
            win_rate = round(
                wins / total * 100,
                2
            )

        return {
            "total_trades": total,
            "wins": wins,
            "losses": losses,
            "win_rate": win_rate,
            "average_win": round(avg_win, 2),
            "average_loss": round(avg_loss, 2),
            "best_trade": round(best_trade, 2),
            "worst_trade": round(worst_trade, 2)
        }


if __name__ == "__main__":

    stats = StatsEngine()

    result = stats.get_summary()

    print("\nATHENA STATS\n")

    for key, value in result.items():
        print(f"{key}: {value}")