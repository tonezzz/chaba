---
id: follow_news
name: Follow News / ติดตามข่าว
kind: sub_agent
version: 1
trigger_phrases: ติดตามข่าว, โฟกัสข่าว, เพิ่มโฟกัสข่าว, ลบโฟกัสข่าว, รายการโฟกัสข่าว, สรุปข่าวติดตาม, follow news, follow_news, news follow, track news
---

## Purpose
ติดตามข่าวตาม “โฟกัส” ที่ผู้ใช้กำหนด (เพิ่ม/ลบ/ปรับทิศทางได้) จากหลายแหล่งข่าว และเก็บสรุปไว้เพื่อรายงานภายหลัง.

## Behavior
- จำรายการโฟกัส (focus) แบบถาวรในระบบ.
- ดึง RSS หลายแหล่ง และคัดหัวข้อที่เกี่ยวข้องกับโฟกัส.
- สร้างสรุปแบบสั้นและเก็บเป็นรายการ “สรุปที่พร้อมรายงาน”.
- เมื่อผู้ใช้พิมพ์ “ติดตามข่าว” ให้เช็คสรุปที่มีอยู่ก่อน และถามผู้ใช้ว่าจะรายงานอันไหน.

## Commands (Thai)
- “ติดตามข่าว” (ดูรายการสรุปที่มีอยู่)
- “ติดตามข่าว รีเฟรช” (ดึงข่าวใหม่และสร้างสรุปใหม่)
- “โฟกัสข่าว” / “รายการโฟกัสข่าว” (ดูโฟกัสปัจจุบัน)
- “โฟกัสข่าว เพิ่ม: <คำ/หัวข้อ>”
- “โฟกัสข่าว ลบ: <คำ/หัวข้อ>”
- “รายงานข่าว: <summary_id>”

## Commands (English)
- `follow news` (list available stored summaries)
- `follow news refresh`
- `focus list`
- `focus add: <topic>`
- `focus remove: <topic>`
- `report: <summary_id>`

## Status Payload Contract
- `focus`: list of focus strings
- `summaries`: list of stored summary objects
- `updated_at`: unix timestamp (seconds)
