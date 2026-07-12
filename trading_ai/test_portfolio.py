from portfolio_manager import PortfolioManager

p = PortfolioManager()

p.add_holding(
    "RELIANCE",
    10,
    1400,
    1500
)

p.add_holding(
    "TCS",
    5,
    3800,
    3950
)

print(p.get_holdings())

print(p.summary())



