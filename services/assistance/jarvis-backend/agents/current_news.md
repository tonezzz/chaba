---
id: current-news
name: Current News / ข่าวปัจจุบัน
kind: sub_agent
version: 1
trigger_phrases: ข่าวล่าสุด, ข่าววันนี้, ข่าวตอนนี้, current news, news today, latest news, ข่าว, news
---

## Purpose
ดึงข่าวล่าสุดจากแหล่งข่าวต่างๆ และสรุปเป็น brief ที่อ่านง่ายสำหรับผู้ใช้.

Get the latest news from various news sources and summarize it into an easy-to-read brief for the user.

## Behavior
- เรียกใช้ MCP-News server ผ่าน news_1mcp_news_run tool
- ดึงข่าวล่าสุดและสรุปเป็น brief สั้นๆ 
- แสดงผลลัพธ์เป็นข้อความที่อ่านง่าย
- รองรับทั้งภาษาไทยและอังกฤษ

- Calls MCP-News server via news_1mcp_news_run tool
- Fetches latest news and summarizes into a brief format
- Displays results as easy-to-read text
- Supports both Thai and English

## Commands (Thai)
- "ข่าวล่าสุด" / "ข่าววันนี้" / "ข่าวตอนนี้"
- "ข่าว" (simple trigger)

## Commands (English)
- `current news` / `news today` / `latest news`
- `news` (simple trigger)

## Status Payload Contract
- `last_brief`: string - The latest news brief content
- `last_updated`: unix timestamp - When the news was last fetched
- `source`: string - Always "mcp-news" for this agent

## Integration Notes
- Uses MCP-News server with tool name: `news_1mcp_news_run`
- Parameters: `{"start_at": "fetch", "stop_after": "render"}`
- Fallback: Returns error message if MCP server is unavailable
