"""Directive-authorized memory writes (OPS-0567, card
correction-commands-die-at-the-confirm-gate).

Transcript 2026-10-13-cac2984711: 'CRV เป็นรถของกุ้ง ไม่ใช่ของผมนะ
แก้ไขด้วย' — an explicit fix order — got a permission ask instead of a
write, and the correction died when the session ended. The provider now
treats an explicit store/correct/retract order in the user's own turn as
the confirmation for the memory-write seats (ada_remember curated-bank
kinds, ada_forget, ada_ops action='outcome'); confirm-first stays for
inferred/uncertain facts and for every other gated tool.
"""

import unittest

from backend.realtime_provider import (
    GeminiLiveProvider, _memory_directed_call)


class MemoryDirectiveCallTests(unittest.TestCase):
    """_memory_directed_call scopes the authorization to the memory-write
    seats — a directive must never arm actuation or publishes."""

    def test_memory_write_seats(self) -> None:
        self.assertTrue(_memory_directed_call("ada_remember", {"bank": "personal"}))
        self.assertTrue(_memory_directed_call("ada_forget", {"bank": "personal"}))
        self.assertTrue(_memory_directed_call(
            "ada_ops", {"action": "outcome", "bank": "personal"}))

    def test_non_memory_tools_never_directed(self) -> None:
        for name in ("control_entity", "cms_publish_page", "calendar_write",
                     "devin", "cctv_wall", "cast_to_screen",
                     "ada_enroll_speaker", "ada_camera_snapshot"):
            self.assertFalse(_memory_directed_call(name, {}), name)

    def test_ada_ops_read_actions_not_directed(self) -> None:
        for action in ("usage", "health", "check", "research", "report",
                       "acl_explain"):
            self.assertFalse(
                _memory_directed_call("ada_ops", {"action": action}), action)


class UserMemoryDirectiveTests(unittest.TestCase):
    """_user_memory_directive detects the command class — and rejects the
    near-misses that must stay confirm-gated."""

    def setUp(self) -> None:
        self.provider = GeminiLiveProvider()

    def test_incident_turn_authorizes(self) -> None:
        # The exact turn that died at the gate — a negated fact ('ไม่ใช่')
        # inside the correction content must not veto the order.
        self.assertTrue(self.provider._user_memory_directive(
            "CRV เป็นรถของกุ้ง ไม่ใช่ของผมนะ แก้ไขด้วย"))

    def test_thai_directives(self) -> None:
        for text in (
            "จำไว้ว่า CRV เป็นของกุ้ง",
            "จดไว้ ประตูรั้วรหัสใหม่ 4471",
            "บันทึกไว้เลย",
            "เก็บไว้นะ เรื่องนี้",
            "แก้ไขให้ด้วย ของกุ้งไม่ใช่ของผม",
            "เปลี่ยนเป็นของกุ้ง",
            "อัปเดตให้หน่อย",
            "ลืมเรื่องนั้นไป",
            "ลบที่จำไว้ออก",
        ):
            self.assertTrue(
                self.provider._user_memory_directive(text), text)

    def test_english_directives(self) -> None:
        for text in (
            "remember that the CRV is Kung's car",
            "note this — the gate code changed",
            "that's wrong, fix it",
            "correct that please",
            "write that down",
            "record it",
            "save it",
            "update the memory",
            "change the record",
            "forget it",
            "forget about it",
            "jot that down",
        ):
            self.assertTrue(
                self.provider._user_memory_directive(text), text)

    def test_negated_directive_does_not_authorize(self) -> None:
        for text in (
            "อย่าจำเรื่องนี้",
            "อย่าบันทึกอันนั้น",
            "ไม่ต้องแก้",
            "หยุดจดไว้",
            "don't record that",
            "do not remember that",
            "never fix it",
        ):
            self.assertFalse(
                self.provider._user_memory_directive(text), text)

    def test_questions_do_not_authorize(self) -> None:
        for text in (
            "แก้ไขได้ไหม",
            "จำไว้มั้ย",
            "did you remember that?",
            "can you remember it?",
        ):
            self.assertFalse(
                self.provider._user_memory_directive(text), text)

    def test_recollection_is_not_an_order(self) -> None:
        for text in (
            "I remember the CRV was red",
            "i remember it well",
            "do you remember his name",
            "we remember that day",
        ):
            self.assertFalse(
                self.provider._user_memory_directive(text), text)

    def test_no_directive(self) -> None:
        for text in (
            # A correction statement with no order stays confirm-gated —
            # the card reserves auto-authorize for explicit commands.
            "the CRV is Kung's, not mine",
            "that's wrong",
            "yes",
            "ตกลง",
            "",
            "CRV เป็นรถของกุ้ง",
        ):
            self.assertFalse(
                self.provider._user_memory_directive(text), text)


if __name__ == "__main__":
    unittest.main()
