from vision_ocr_reader import OCRReader


def test_parse_extracts_prices_and_symbols():
    reader = OCRReader()
    raw = ["AAPL", "182.45", "Volume: 23,451,200", "RELIANCE.NS", "2,845.10"]
    result = reader.parse(raw)
    assert "AAPL" in result.symbols
    assert 182.45 in result.prices
    assert 2845.10 in result.prices


def test_parse_detects_pnl_candidates():
    reader = OCRReader()
    raw = ["P&L: +$245.30", "Position: LONG 100 shares", "+2.4%"]
    result = reader.parse(raw)
    assert any("245.30" in c for c in result.pnl_candidates)
    assert "+2.4%" in result.pnl_candidates


def test_parse_handles_empty_and_garbage_strings():
    reader = OCRReader()
    raw = ["", "   ", "###", "----"]
    result = reader.parse(raw)
    assert result.prices == []
    assert result.symbols == []


def test_parse_does_not_crash_on_malformed_numbers():
    reader = OCRReader()
    raw = ["..", "-.", "1..2.3"]
    result = reader.parse(raw)  # should not raise
    assert isinstance(result.prices, list)
