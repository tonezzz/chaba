from main import _extract_note_text, _is_note_trigger


def test_extract_note_text_english_prefix() -> None:
    assert _extract_note_text("make a note: buy milk") == "buy milk"


def test_extract_note_text_english_contains() -> None:
    assert _extract_note_text("please make a note - call mom") == "call mom"


def test_extract_note_text_thai_prefix() -> None:
    assert _extract_note_text("จดบันทึก: ไปธนาคาร") == "ไปธนาคาร"


def test_extract_note_text_thai_contains() -> None:
    assert _extract_note_text("ช่วย สร้างบันทึก - ต่ออายุพาสปอร์ต") == "ต่ออายุพาสปอร์ต"


def test_extract_note_text_thai_spaced_words() -> None:
    assert _extract_note_text("จด บันทึก: ไปธนาคาร") == "ไปธนาคาร"


def test_extract_note_text_thai_note_variants() -> None:
    assert _extract_note_text("สร้าง เป็น โน้ต - อย่าลืม ต่อพาสปอร์ต") == "อย่าลืม ต่อพาสปอร์ต"
    assert _extract_note_text("จด โน้ต: โทรหาแม่") == "โทรหาแม่"


def test_extract_note_text_missing_payload() -> None:
    assert _extract_note_text("make a note") is None
    assert _extract_note_text("จดบันทึก") is None


def test_is_note_trigger_thai_without_payload() -> None:
    assert _is_note_trigger("จดบันทึก") is True
    assert _is_note_trigger("สร้างบันทึก") is True
    assert _is_note_trigger("จด บันทึก") is True
    assert _is_note_trigger("ช่วย จด บันทึก") is True
