"""Manual smoke script for PortfolioManager.

Run it explicitly (`python test_portfolio.py`). Its name matches pytest's
test_*.py pattern, so it used to be IMPORTED on every pytest collection —
silently adding RELIANCE/TCS holdings to the portfolio state on each test
run. Everything now lives behind the __main__ guard; pytest collects
nothing here.
"""

from portfolio_manager import PortfolioManager


def main() -> None:
    p = PortfolioManager()
    p.add_holding("RELIANCE", 10, 1400, 1500)
    p.add_holding("TCS", 5, 3800, 3950)
    print(p.get_holdings())
    print(p.summary())


if __name__ == "__main__":
    main()
