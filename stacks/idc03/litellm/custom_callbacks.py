"""Pre-call hooks for LiteLLM proxy on idc03.

1. Groq rejects reasoning_content/reasoning echoed back in assistant messages
   (upstream bug BerriAI/litellm#47931 — strip on request side for groq-* groups).
2. Cloudflare Workers AI chat-completions only accepts `content` as a plain
   string (or legacy `prompt`), while OpenAI-compatible clients (opencode,
   @ai-sdk) send content as an array of parts. For `cf-*` model groups we
   flatten all-text part arrays into a single string and ensure every message
   carries a `content` field. Non-text parts are left untouched.
"""
from litellm.integrations.custom_logger import CustomLogger

_TEXT_PART_TYPES = {"text", "input_text", "output_text"}


def _flatten_content(content):
    """Return flattened string for all-text part lists, else original value."""
    if not isinstance(content, list):
        return content
    texts = []
    for part in content:
        if isinstance(part, dict):
            ptype = part.get("type")
            if ptype in _TEXT_PART_TYPES and isinstance(part.get("text"), str):
                texts.append(part["text"])
                continue
            if ptype is None and isinstance(part.get("text"), str):
                texts.append(part["text"])
                continue
        # non-text part (image, tool_use, ...) — cannot flatten safely
        return content
    return "\n".join(texts)


class _GroqReasoningStrip(CustomLogger):
    async def async_pre_call_hook(self, user_api_key_dict, cache, data, call_type):
        if "groq" not in str(data.get("model", "")):
            return data
        for m in data.get("messages") or []:
            if isinstance(m, dict):
                m.pop("reasoning_content", None)
                m.pop("reasoning", None)
        return data


class _CFContentFlatten(CustomLogger):
    async def async_pre_call_hook(self, user_api_key_dict, cache, data, call_type):
        if call_type != "acompletion":
            return data
        if not str(data.get("model", "")).startswith("cf-"):
            return data
        for m in data.get("messages") or []:
            if not isinstance(m, dict):
                continue
            m["content"] = _flatten_content(m.get("content"))
            if m.get("content") is None:
                m["content"] = ""
        return data


proxy_handler_instance = _GroqReasoningStrip()
cf_content_handler_instance = _CFContentFlatten()
