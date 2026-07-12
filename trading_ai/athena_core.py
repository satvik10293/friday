from vision_screen_capture import ScreenCapture
from vision_ocr_reader import OCRReader
from vision_ui_detector import UIDetector
from vision_position_tracker import PositionTracker
from vision_trade_detector import TradeDetector

from trade_memory import TradeMemory

import time


class AthenaCore:

    def __init__(self):

        self.capture = ScreenCapture()

        self.ocr = OCRReader()

        self.ui = UIDetector()

        self.position_tracker = PositionTracker()

        self.trade_detector = TradeDetector()

        self.memory = TradeMemory()

    def process_frame(self, frame):

        raw_boxes = self.ocr.read_with_boxes(
            frame.image
        )

        elements = self.ui.parse_ocr_boxes(
            raw_boxes
        )

        position = self.position_tracker.extract(
            elements
        )

        print("\n[POSITION]")
        print(position)

        event = self.trade_detector.update(
            position
        )

        if event:

            print("\n[TRADE EVENT]")
            print(event)

            self.memory.save_event(
                event
            )

    def run(self):

        print("\nATHENA STARTED\n")

        for frame in self.capture.stream(
            interval_seconds=3
        ):

            try:

                self.process_frame(
                    frame
                )

            except Exception as e:

                print(
                    f"\n[ERROR] {e}"
                )

                time.sleep(1)


if __name__ == "__main__":

    athena = AthenaCore()

    athena.run()