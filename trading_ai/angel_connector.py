from SmartApi import SmartConnect
from dotenv import load_dotenv
import pyotp
import os

load_dotenv()


class AngelConnector:

    def __init__(self):

        self.api_key = os.getenv("API_KEY")
        self.client_code = os.getenv("CLIENT_CODE")
        self.password = os.getenv("PASSWORD")
        self.totp_secret = os.getenv("TOTP_SECRET")

        self.smart = SmartConnect(
            api_key=self.api_key
        )

        self.logged_in = False

    def get_otp(self):

        try:
            return pyotp.TOTP(
                self.totp_secret.strip()
            ).now()

        except Exception:
            return input(
                "Enter OTP manually: "
            )

    def login(self):

        if self.logged_in:
            return True

        otp = self.get_otp()

        session = self.smart.generateSession(
            self.client_code,
            self.password,
            otp
        )

        if not session.get("status"):
            raise Exception(
                f"Login Failed: {session}"
            )

        self.logged_in = True

        print("\n✓ Logged into Angel One")
        print(
            f"Client: {session['data']['clientcode']}"
        )
        print(
            f"Name: {session['data']['name']}"
        )

        return True

    def get_funds(self):

        try:
            return self.smart.rmsLimit()

        except Exception as e:
            print(f"Funds Error: {e}")
            return None

    def get_holdings(self):

        try:
            return self.smart.holding()

        except Exception as e:
            print(f"Holdings Error: {e}")
            return None

    def get_positions(self):

        try:
            return self.smart.position()

        except Exception as e:
            print(f"Positions Error: {e}")
            return None

    def create_summary(self, top_n=5):
        """Build a short, spoken-friendly portfolio checkup.

        Keep it simple (Dad's request): total value, today's move, and the
        biggest gainers/losers today — not a wall of 200+ lines.

        Angel One's holding() gives per-stock: tradingsymbol, quantity,
        averageprice, ltp, close (yesterday's close), profitandloss.
        Today's change = (ltp - close) * quantity.  Overall P&L =
        sum of profitandloss.
        """

        holdings = self.get_holdings()

        if not holdings:
            return "Unable to retrieve holdings."

        if not holdings.get("data"):
            return "No holdings found in portfolio."

        def num(x):
            try:
                return float(x)
            except (TypeError, ValueError):
                return 0.0

        total_value = 0.0
        total_day_change = 0.0
        total_pnl = 0.0
        movers = []  # (symbol, day_pct, day_change_rupees)

        for stock in holdings["data"]:
            symbol = stock.get("tradingsymbol", "Unknown")
            qty = num(stock.get("quantity"))
            ltp = num(stock.get("ltp"))
            prev_close = num(stock.get("close"))

            total_value += ltp * qty
            total_pnl += num(stock.get("profitandloss"))

            if prev_close > 0 and qty > 0:
                day_change = (ltp - prev_close) * qty
                day_pct = (ltp - prev_close) / prev_close * 100
                total_day_change += day_change
                movers.append((symbol, day_pct, day_change))

        movers.sort(key=lambda m: m[1], reverse=True)
        gainers = [m for m in movers if m[1] > 0][:top_n]
        losers = [m for m in movers if m[1] < 0][-top_n:][::-1]

        day_arrow = "up" if total_day_change >= 0 else "down"

        lines = [
            f"Portfolio value: Rs {total_value:,.0f}",
            f"Today: {day_arrow} Rs {abs(total_day_change):,.0f}",
            f"Overall P&L: Rs {total_pnl:,.0f}",
        ]

        if gainers:
            lines.append("")
            lines.append("Top gainers today:")
            for sym, pct, _ in gainers:
                lines.append(f"  {sym}  +{pct:.1f}%")

        if losers:
            lines.append("")
            lines.append("Top losers today:")
            for sym, pct, _ in losers:
                lines.append(f"  {sym}  {pct:.1f}%")

        return "\n".join(lines)

    def portfolio_checkup(self):

        print("\n" + "=" * 60)
        print("ATHENA PORTFOLIO CHECKUP")
        print("=" * 60)

        print(
            self.create_summary()
        )

        print(
            "\n✓ Portfolio check complete"
        )


if __name__ == "__main__":

    angel = AngelConnector()

    angel.login()

    angel.portfolio_checkup()