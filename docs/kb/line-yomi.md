# Yomi — LINE archive, search & send

Date: 2026-09-27 · consolidated for review

## What it is

LINE message **archive + search + E2EE send** running as the `yomi` MCP
server. Pulls chats via LINE's secondary-device protocol, decrypts E2EE,
summarizes into MDDB, exposes MCP tools. See chaba-docs
`architecture/yomi-architecture-separation.md` (fetch vs process split).

## Capabilities (MCP tools)

- `list_conversations`, `get_chat_messages`, `get_unread_digest`,
  `get_insight` — read/search
- `get_message_media` — decrypted images/video/audio
- **`send_message`** — real E2EE outbound to any chatId (already works —
  the only live LINE-send path in the stack)
- `login`/`login_complete` — passwordless re-auth on Tony's phone

## Status — OFFLINE as of 2026-09-27

`list_conversations` → `Access token refresh required`. Session revoked
(typically when LINE on the phone re-logs elsewhere). Digest→MDDB and
any send path are both blocked until re-login.

**Re-login flow** (Tony, ~3 min): enable 允許自其他裝置登入 on the phone
→ `login` (phone/region) → LINE shows a PIN → `login_complete`
immediately → device approved on the phone.

## Indexed data

- ~489 daily digests in MDDB (`ada-ha-bank-yomi` family)
- Searchable via `ada_memory_search` (bank='yomi') and the MCP tools
- Privacy default: capture-all; excluded chats via `exclude_chats`

## Confusion note for Ada

Yomi ≠ LINE bot. Yomi **reads** (and can send as Tony's account); the
"LINE bot" concept is outbound notifications — currently unbuilt on the
Ada side. See `line-bot` report.
