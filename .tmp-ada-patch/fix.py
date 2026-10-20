from pathlib import Path
p = Path("/home/tony/CascadeProjects/ada-pi/backend/tg_relay.py")
s = p.read_text()

# 1) give send_photo its body back (docstring + original logic), before send_voice
s = s.replace(
    '''    async def send_photo(self, chat_id: int, url: str, caption: str) -> None:
    async def send_voice(self, chat_id: int, ogg: bytes,''',
    '''    async def send_photo(self, chat_id: int, url: str, caption: str) -> None:
        """Fetch image bytes (tailnet-reachable) and sendPhoto them."""
        assert self.http is not None
        try:
            r = await self.http.get(url, timeout=120)
            if r.status_code != 200 or len(r.content) < 500:
                raise RuntimeError(f"fetch {r.status_code} {len(r.content)}B")
            ct = r.headers.get("content-type", "image/png")
            ext = ".jpg" if "jpeg" in ct else ".png"
            resp = await self.http.post(
                f"{TG_API}/bot{BOT_TOKEN}/sendPhoto",
                data={"chat_id": str(chat_id), "caption": caption[:1000]},
                files={"photo": (f"cam{ext}", r.content, ct)})
            if not resp.json().get("ok"):
                raise RuntimeError(str(resp.json()))
        except Exception as exc:
            logger.warning("chat %s photo %s failed: %s", chat_id, url, exc)
            await self.send_text(chat_id, f"(image failed: {caption or url})")

    async def send_voice(self, chat_id: int, ogg: bytes,''',
    1)

# 2) delete the orphaned docstring + duplicate body after _wav_to_ogg
s = s.replace(
    '''        return buf.getvalue()

    """Fetch image bytes (tailnet-reachable) and sendPhoto them."""
        assert self.http is not None
        try:
            r = await self.http.get(url, timeout=120)
            if r.status_code != 200 or len(r.content) < 500:
                raise RuntimeError(f"fetch {r.status_code} {len(r.content)}B")
            ct = r.headers.get("content-type", "image/png")
            ext = ".jpg" if "jpeg" in ct else ".png"
            resp = await self.http.post(
                f"{TG_API}/bot{BOT_TOKEN}/sendPhoto",
                data={"chat_id": str(chat_id), "caption": caption[:1000]},
                files={"photo": (f"cam{ext}", r.content, ct)})
            if not resp.json().get("ok"):
                raise RuntimeError(str(resp.json()))
        except Exception as exc:
            logger.warning("chat %s photo %s failed: %s", chat_id, url, exc)
            await self.send_text(chat_id, f"(image failed: {caption or url})")
''',
    '''        return buf.getvalue()
''',
    1)
p.write_text(s)
print("repaired")
