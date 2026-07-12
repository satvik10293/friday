from dataclasses import dataclass
import re


@dataclass
class Position:
    symbol: str | None = None
    quantity: int | None = None
    entry_price: float | None = None
    pnl: float | None = None


class PositionTracker:

    SYMBOL_RE = re.compile(r"^[A-Z]{1,5}$")
    NUMBER_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")

    def extract(self, elements):

        position = Position()

        for e in elements:

            text = e.text.strip()

            # symbol candidate
            if (
                position.symbol is None
                and self.SYMBOL_RE.match(text)
            ):
                position.symbol = text

            # pnl detection
            lower = text.lower()

            if "p&l" in lower or "pnl" in lower:

                matches = self.NUMBER_RE.findall(text)

                if matches:
                    try:
                        position.pnl = float(matches[-1])
                    except:
                        pass

            # standalone money value
            if position.entry_price is None:

                try:
                    value = float(text.replace(",", ""))

                    if 1 <= value <= 100000:
                        position.entry_price = value

                except:
                    pass

        return position
if __name__ == "__main__":

    from vision_ui_detector import UIElement

    sample = [

        UIElement(
            text="AAPL",
            confidence=0.98,
            x=10,
            y=10,
            width=50,
            height=20
        ),

        UIElement(
            text="298.01",
            confidence=0.99,
            x=10,
            y=40,
            width=80,
            height=20
        ),

        UIElement(
            text="P&L +214.30",
            confidence=0.97,
            x=10,
            y=70,
            width=100,
            height=20
        )
    ]

    tracker = PositionTracker()

    pos = tracker.extract(sample)

    print(pos)