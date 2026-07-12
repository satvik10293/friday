from dataclasses import dataclass


@dataclass
class TradeEvent:
    event_type: str
    symbol: str


class TradeDetector:

    def __init__(self):
        self.previous_position = None

    def update(self, current_position):

        if self.previous_position is None:
            self.previous_position = current_position
            return None

        event = None

        old_symbol = self.previous_position.symbol
        new_symbol = current_position.symbol

        if old_symbol is None and new_symbol:

            event = TradeEvent(
                event_type="BUY",
                symbol=new_symbol
            )

        elif old_symbol and new_symbol is None:

            event = TradeEvent(
                event_type="SELL",
                symbol=old_symbol
            )

        self.previous_position = current_position

        return event
if __name__ == "__main__":

    from vision_position_tracker import Position

    detector = TradeDetector()

    print(
        detector.update(
            Position(symbol=None)
        )
    )

    print(
        detector.update(
            Position(symbol="AAPL")
        )
    )

    print(
        detector.update(
            Position(symbol="AAPL")
        )
    )

    print(
        detector.update(
            Position(symbol=None)
        )
    )