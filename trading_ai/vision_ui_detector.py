from dataclasses import dataclass


@dataclass
class UIElement:
    text: str
    confidence: float
    x: int
    y: int
    width: int
    height: int


class UIDetector:
    def find_text(self, elements, keyword):

        keyword = keyword.lower()

        for element in elements:

            if keyword in element.text.lower():
                return element

        return None
    
    def parse_ocr_boxes(self, ocr_results):

        elements = []

        for box, text, confidence in ocr_results:

            if confidence < 0.50:
                continue

            xs = [p[0] for p in box]
            ys = [p[1] for p in box]

            xs = [p[0] for p in box]
            ys = [p[1] for p in box]

            x = int(min(xs))
            y = int(min(ys))

            width = int(max(xs) - min(xs))
            height = int(max(ys) - min(ys))

            elements.append(
                UIElement(
                    text=text,
                    confidence=float(confidence),
                    x=x,
                    y=y,
                    width=width,
                    height=height
                )
            )

        return elements
if __name__ == "__main__":

    sample = [
        (
            [[10,20],[100,20],[100,40],[10,40]],
            "AAPL",
            0.98
        ),
        (
            [[10,60],[100,60],[100,80],[10,80]],
            "298.01",
            0.97
        )
    ]

    detector = UIDetector()

    elements = detector.parse_ocr_boxes(sample)

    for e in elements:
        print(e)