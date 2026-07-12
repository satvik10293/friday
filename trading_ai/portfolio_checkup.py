from angel_connector import AngelConnector
from datetime import datetime


class PortfolioCheckup:

    def __init__(self):
        self.angel = AngelConnector()

    def run(self):

        print("\n" + "=" * 60)
        print("ATHENA PORTFOLIO CHECKUP")
        print("=" * 60)

        funds = self.angel.get_funds()
        holdings = self.angel.get_holdings()

        cash = 0

        if funds and funds.get("data"):
            cash = float(
                funds["data"].get(
                    "availablecash",
                    0
                )
            )

        print(f"\nCash Available: ₹{cash:,.2f}")

        if not holdings:
            print("\nNo holdings found.")
            return

        data = holdings.get("data", [])

        print(f"\nTotal Holdings: {len(data)}")

        print("\nTop Holdings")
        print("-" * 60)

        total_value = 0

        for item in data[:10]:

            symbol = item.get(
                "tradingsymbol",
                "UNKNOWN"
            )

            qty = float(
                item.get(
                    "quantity",
                    0
                )
            )

            ltp = float(
                item.get(
                    "ltp",
                    0
                )
            )

            value = qty * ltp

            total_value += value

            print(
                f"{symbol:<20}"
                f" Qty:{qty:<8}"
                f" Value: ₹{value:,.2f}"
            )

        print("\n" + "-" * 60)
        print(
            f"Portfolio Value: ₹{total_value:,.2f}"
        )

        print(
            "\nUpdated:",
            datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        )

        print("=" * 60)


if __name__ == "__main__":
    PortfolioCheckup().run()