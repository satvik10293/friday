import sqlite3


class TradeJournal:

    def __init__(self, db_path="athena.db"):
        self.db_path = db_path
        self.create_tables()

    def create_tables(self):

        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()

        cur.execute("""
        CREATE TABLE IF NOT EXISTS trades(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT,
            entry_time TEXT,
            exit_time TEXT,
            entry_price REAL,
            exit_price REAL,
            pnl REAL
        )
        """)

        conn.commit()
        conn.close()

    def add_trade(
        self,
        symbol,
        entry_time,
        exit_time,
        entry_price,
        exit_price,
        pnl
    ):

        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()

        cur.execute(
            """
            INSERT INTO trades(
                symbol,
                entry_time,
                exit_time,
                entry_price,
                exit_price,
                pnl
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                symbol,
                entry_time,
                exit_time,
                entry_price,
                exit_price,
                pnl
            )
        )

        conn.commit()
        conn.close()

    def get_trades(self):

        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()

        cur.execute("""
        SELECT *
        FROM trades
        ORDER BY id DESC
        """)

        rows = cur.fetchall()

        conn.close()

        return rows

    def delete_all(self):

        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()

        cur.execute("""
        DELETE FROM trades
        """)

        conn.commit()
        conn.close()