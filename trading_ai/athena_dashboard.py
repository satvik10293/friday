from flask import Flask
from stats_engine import StatsEngine
from trade_journal import TradeJournal
from portfolio_manager import PortfolioManager

app = Flask(__name__)

stats_engine = StatsEngine()
journal = TradeJournal()
portfolio = PortfolioManager()


@app.route("/")
def dashboard():

    stats = stats_engine.get_summary()
    trades = journal.get_trades()

    portfolio_summary = portfolio.summary()
    holdings = portfolio.get_holdings()

    holdings_rows = ""

    if holdings:
        for h in holdings:

            symbol = h[1]
            qty = h[2]
            buy = h[3]
            current = h[4]

            pnl = (current - buy) * qty

            pnl_class = "profit" if pnl >= 0 else "loss"

            holdings_rows += f"""
            <tr>
                <td>{symbol}</td>
                <td>{qty}</td>
                <td>₹{buy:.2f}</td>
                <td>₹{current:.2f}</td>
                <td class="{pnl_class}">₹{pnl:.2f}</td>
            </tr>
            """
    else:
        holdings_rows = """
        <tr>
            <td colspan="5" style="text-align:center;">
                No holdings found
            </td>
        </tr>
        """

    trade_rows = ""

    if trades:
        for trade in trades:

            pnl = trade[6]

            pnl_class = "profit" if pnl >= 0 else "loss"

            trade_rows += f"""
            <tr>
                <td>{trade[0]}</td>
                <td>{trade[1]}</td>
                <td>{trade[4]}</td>
                <td>{trade[5]}</td>
                <td class="{pnl_class}">
                    ₹{pnl:.2f}
                </td>
            </tr>
            """
    else:
        trade_rows = """
        <tr>
            <td colspan="5" style="text-align:center;">
                No trades recorded
            </td>
        </tr>
        """

    return f"""
<!DOCTYPE html>
<html>

<head>

<title>ATHENA Portfolio Intelligence</title>

<meta http-equiv="refresh" content="5">

<style>

* {{
    margin:0;
    padding:0;
    box-sizing:border-box;
}}

body {{
    background:#0b0f14;
    color:#d6dce3;
    font-family:'Segoe UI',sans-serif;
}}

.container {{
    max-width:1700px;
    margin:auto;
    padding:30px;
}}

.header {{
    display:flex;
    justify-content:space-between;
    align-items:center;
    margin-bottom:30px;
}}

.logo {{
    font-size:34px;
    font-weight:700;
    letter-spacing:2px;
}}

.subtitle {{
    color:#8d99a8;
}}

.status {{
    color:#22c55e;
    font-weight:bold;
}}

.grid {{
    display:grid;
    grid-template-columns:repeat(6,1fr);
    gap:15px;
    margin-bottom:25px;
}}

.card {{
    background:#11161d;
    border:1px solid #202832;
    border-radius:10px;
    padding:20px;
}}

.label {{
    color:#8894a3;
    font-size:12px;
    text-transform:uppercase;
    margin-bottom:10px;
}}

.value {{
    font-size:28px;
    font-weight:700;
}}

.section {{
    background:#11161d;
    border:1px solid #202832;
    border-radius:10px;
    margin-bottom:25px;
    overflow:hidden;
}}

.section-title {{
    padding:18px;
    border-bottom:1px solid #202832;
    font-size:18px;
    font-weight:600;
}}

table {{
    width:100%;
    border-collapse:collapse;
}}

th {{
    padding:15px;
    text-align:left;
    color:#8894a3;
    border-bottom:1px solid #202832;
}}

td {{
    padding:15px;
    border-bottom:1px solid #1a222c;
}}

tr:hover {{
    background:#141b23;
}}

.profit {{
    color:#22c55e;
    font-weight:600;
}}

.loss {{
    color:#ef4444;
    font-weight:600;
}}

.bottom {{
    display:grid;
    grid-template-columns:1fr 1fr;
    gap:20px;
}}

.row {{
    display:flex;
    justify-content:space-between;
    padding:10px 0;
}}

@media(max-width:1200px) {{
    .grid {{
        grid-template-columns:repeat(2,1fr);
    }}

    .bottom {{
        grid-template-columns:1fr;
    }}
}}

</style>

</head>

<body>

<div class="container">

<div class="header">

<div>
<div class="logo">ATHENA</div>
<div class="subtitle">
Portfolio & Trade Intelligence
</div>
</div>

<div class="status">
SYSTEM ONLINE
</div>

</div>

<div class="grid">

<div class="card">
<div class="label">Total Trades</div>
<div class="value">{stats["total_trades"]}</div>
</div>

<div class="card">
<div class="label">Wins</div>
<div class="value profit">{stats["wins"]}</div>
</div>

<div class="card">
<div class="label">Losses</div>
<div class="value loss">{stats["losses"]}</div>
</div>

<div class="card">
<div class="label">Win Rate</div>
<div class="value">{stats["win_rate"]}%</div>
</div>

<div class="card">
<div class="label">Best Trade</div>
<div class="value profit">₹{stats["best_trade"]}</div>
</div>

<div class="card">
<div class="label">Worst Trade</div>
<div class="value loss">₹{stats["worst_trade"]}</div>
</div>

</div>

<div class="section">

<div class="section-title">
Portfolio Overview
</div>

<div class="grid" style="padding:20px;">

<div class="card">
<div class="label">Invested Capital</div>
<div class="value">
₹{portfolio_summary["invested"]}
</div>
</div>

<div class="card">
<div class="label">Current Value</div>
<div class="value">
₹{portfolio_summary["current"]}
</div>
</div>

<div class="card">
<div class="label">Total P&L</div>
<div class="value {'profit' if portfolio_summary['pnl'] >= 0 else 'loss'}">
₹{portfolio_summary["pnl"]}
</div>
</div>

</div>

</div>

<div class="section">

<div class="section-title">
Current Holdings
</div>

<table>

<tr>
<th>Symbol</th>
<th>Quantity</th>
<th>Buy Price</th>
<th>Current Price</th>
<th>P&L</th>
</tr>

{holdings_rows}

</table>

</div>

<div class="section">

<div class="section-title">
Trade Journal
</div>

<table>

<tr>
<th>ID</th>
<th>Symbol</th>
<th>Entry</th>
<th>Exit</th>
<th>P&L</th>
</tr>

{trade_rows}

</table>

</div>

<div class="bottom">

<div class="card">

<div class="label">
Performance
</div>

<div class="row">
<span>Average Win</span>
<span class="profit">
₹{stats["average_win"]}
</span>
</div>

<div class="row">
<span>Average Loss</span>
<span class="loss">
₹{stats["average_loss"]}
</span>
</div>

</div>

<div class="card">

<div class="label">
System Status
</div>

<div class="row">
<span>Portfolio Manager</span>
<span class="profit">ONLINE</span>
</div>

<div class="row">
<span>Trade Journal</span>
<span class="profit">ONLINE</span>
</div>

<div class="row">
<span>Statistics Engine</span>
<span class="profit">ONLINE</span>
</div>

<div class="row">
<span>Database</span>
<span class="profit">ONLINE</span>
</div>

</div>

</div>

</div>

</body>
</html>
"""


if __name__ == "__main__":
    # Localhost only, debug off: 0.0.0.0 + debug=True exposed the Werkzeug
    # debug console (arbitrary code execution) and the portfolio data to the
    # entire local network.
    app.run(
        host="127.0.0.1",
        port=5000,
        debug=False
    )