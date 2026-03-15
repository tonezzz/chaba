from main import _extract_note_text


def test_extract_note_text_english_prefix() -> None:
    assert _extract_note_text("make a note: buy milk") == "buy milk"


def test_extract_note_text_english_contains() -> None:
    assert _extract_note_text("please make a note - call mom") == "call mom"


def test_extract_note_text_thai_prefix() -> None:
    assert _extract_note_text("จดบันทึก: ไปธนาคาร") == "ไปธนาคาร"


def test_extract_note_text_thai_contains() -> None:
    assert _extract_note_text("ช่วย สร้างบันทึก - ต่ออายุพาสปอร์ต") == "ต่ออายุพาสปอร์ต"


def test_extract_note_text_missing_payload() -> None:
    assert _extract_note_text("make a note") is None
    assert _extract_note_text("จดบันทึก") is None
