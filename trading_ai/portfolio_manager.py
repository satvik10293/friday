import sqlite3


class PortfolioManager:

    def __init__(self, db_path="athena.db"):

        self.db_path = db_path

        self.create_tables()

    def create_tables(self):

        conn = sqlite3.connect(self.db_path)

        conn.execute("""
        CREATE TABLE IF NOT EXISTS holdings(

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            symbol TEXT NOT NULL,

            quantity REAL NOT NULL,

            buy_price REAL NOT NULL,

            current_price REAL NOT NULL
        )
        """)

        conn.commit()
        conn.close()

    def add_holding(
        self,
        symbol,
        quantity,
        buy_price,
        current_price
    ):

        conn = sqlite3.connect(self.db_path)

        conn.execute(
            """
            INSERT INTO holdings(
                symbol,
                quantity,
                buy_price,
                current_price
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                symbol.upper(),
                quantity,
                buy_price,
                current_price
            )
        )

        conn.commit()
        conn.close()

    def get_holdings(self):

        conn = sqlite3.connect(self.db_path)

        rows = conn.execute(
            """
            SELECT *
            FROM holdings
            ORDER BY symbol
            """
        ).fetchall()

        conn.close()

        return rows

    def summary(self):

        holdings = self.get_holdings()

        invested = 0
        current = 0

        for h in holdings:

            qty = h[2]

            buy = h[3]

            market = h[4]

            invested += qty * buy

            current += qty * market

        pnl = current - invested

        return {
            "invested": round(invested, 2),
            "current": round(current, 2),
            "pnl": round(pnl, 2)
        }