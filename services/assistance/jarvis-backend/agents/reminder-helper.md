---
id: reminder-helper
name: Reminder Helper
kind: sub_agent
trigger_phrases: reminder add, reminder done, reminder later, reminder reschedule, reminder delete, reminder list, เตือน เพิ่ม, เตือน เสร็จ, เตือน เลื่อน, เตือน ลบ, เตือน รายการ, แสดงการแจ้งเตือน, รายการแจ้งเตือน, แสดงรายการแจ้งเตือน
---

Deterministic helper for managing reminders quickly via chat.

Commands (English):
- `reminder add: <text>`
- `reminder done: <reminder_id>`
- `reminder later: <reminder_id> [days]`
- `reminder reschedule: <reminder_id> <time text>`
- `reminder delete: <reminder_id>`
- `reminder list [pending|all] [include_hidden]`

Commands (Thai aliases):
- `เตือน เพิ่ม: <text>`
- `เตือน เสร็จ: <reminder_id>`
- `เตือน เลื่อน: <reminder_id> <เวลา>`
- `เตือน ลบ: <reminder_id>`
- `เตือน รายการ [pending|all] [include_hidden]`

Notes:
- Works even when Gemini Live is unavailable (backend local-only mode).
- `reminder add:` uses the same parsing logic as `reminder setup:` (time parsing + title improvement + SQLite + Weaviate write-through).
