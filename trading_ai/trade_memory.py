import sqlite3
from datetime import datetime


class TradeMemory:

    def __init__(self, db_path="athena.db"):
        self.db_path = db_path
        self.create_tables()

    def create_tables(self):

        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()

        cur.execute("""
        CREATE TABLE IF NOT EXISTS trade_events(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            event_type TEXT,
            symbol TEXT
        )
        """)

        conn.commit()
        conn.close()

    def save_event(self, event):

        if event is None:
            return

        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()

        cur.execute(
            """
            INSERT INTO trade_events(
                timestamp,
                event_type,
                symbol
            )
            VALUES (?, ?, ?)
            """,
            (
                datetime.now().isoformat(),
                event.event_type,
                event.symbol
            )
        )

        conn.commit()
        conn.close()

    def get_all_events(self):

        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()

        cur.execute("""
        SELECT *
        FROM trade_events
        ORDER BY id DESC
        """)

        rows = cur.fetchall()

        conn.close()

        return rows

    def clear_events(self):

        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()

        cur.execute("""
        DELETE FROM trade_events
        """)

        conn.commit()
        conn.close()