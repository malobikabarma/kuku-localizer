"""One function talks to the model: call_llm(). Any OpenAI-compatible endpoint works
(OpenAI, Gemini's OpenAI endpoint, Groq, OpenRouter, a local vLLM / Ollama server...).

Set API_BASE=mock to run the whole app offline with a fake model (used by the tests)."""
import json
import re
import time

import requests

from config import settings


class LLMError(Exception):
    """A readable error the UI can show as-is."""


class Usage:
    def __init__(self):
        self.reset()

    def reset(self):
        self.calls, self.tokens_in, self.tokens_out = 0, 0, 0

    def add(self, tin: int, tout: int):
        self.calls += 1
        self.tokens_in += int(tin or 0)
        self.tokens_out += int(tout or 0)

    @property
    def cost_usd(self) -> float:
        return (self.tokens_in * settings.price_in_per_m + self.tokens_out * settings.price_out_per_m) / 1e6

    def snapshot(self) -> dict:
        return {"model_calls": self.calls, "tokens_in": self.tokens_in, "tokens_out": self.tokens_out,
                "estimated_cost_usd": round(self.cost_usd, 6)}


usage = Usage()


def is_mock() -> bool:
    return (settings.api_base or "").strip().lower() == "mock"


def is_configured() -> bool:
    return is_mock() or bool(settings.api_key)


# ------------------------------------------------------------------ core call
def call_llm(system: str, user: str, json_mode: bool = False, temperature: float | None = None, task: str = "") -> str:
    if is_mock():
        out = _mock_reply(task, user)
        usage.add(len(system + user) // 4, len(out) // 4)
        return out
    if not settings.api_key:
        raise LLMError("No API key found. Add API_KEY to .env (local) or to the app's Secrets (Streamlit Cloud).")

    url = settings.api_base.rstrip("/") + "/chat/completions"
    body = {"model": settings.model_name,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": settings.temperature if temperature is None else temperature}
    if json_mode and settings.use_json_mode:
        body["response_format"] = {"type": "json_object"}
    headers = {"Authorization": f"Bearer {settings.api_key}", "Content-Type": "application/json"}

    last = ""
    for attempt in range(settings.max_retries + 1):
        try:
            r = requests.post(url, json=body, headers=headers, timeout=settings.request_timeout)
        except requests.RequestException as e:
            last = f"Network error: {e}"
            time.sleep(2 ** attempt)
            continue
        if r.status_code == 400 and "response_format" in body:
            body.pop("response_format")       # some providers don't support JSON mode: retry without it
            continue
        if r.status_code in (429, 500, 502, 503, 504):
            last = f"Provider returned {r.status_code} (rate limit or server busy)."
            time.sleep(min(2 ** attempt * 2, 20))
            continue
        if r.status_code in (401, 403):
            raise LLMError("The API key was rejected (HTTP %d). Check API_KEY and API_BASE." % r.status_code)
        if r.status_code >= 400:
            raise LLMError(f"Model call failed (HTTP {r.status_code}): {r.text[:300]}")
        data = r.json()
        try:
            text = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError):
            raise LLMError(f"Unexpected reply from the provider: {str(data)[:300]}")
        u = data.get("usage") or {}
        usage.add(u.get("prompt_tokens", len(system + user) // 4), u.get("completion_tokens", len(text) // 4))
        return text
    raise LLMError(last or "Model call failed after retries.")


def parse_json(text: str):
    """Tolerant JSON parsing: strips code fences and finds the first JSON object/array."""
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for open_c, close_c in (("{", "}"), ("[", "]")):
        start, end = text.find(open_c), text.rfind(close_c)
        if start != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                continue
    raise LLMError("The model did not return valid JSON. Try again or switch to a stronger model.")


def call_json(system: str, user: str, task: str = "", temperature: float | None = None):
    """call_llm + JSON parsing, with one automatic retry when the JSON is broken."""
    try:
        return parse_json(call_llm(system, user, json_mode=True, temperature=temperature, task=task))
    except LLMError as e:
        if "valid JSON" not in str(e):
            raise
        return parse_json(call_llm(system + "\nReturn ONLY valid JSON. No prose, no code fences.", user,
                                   json_mode=True, temperature=0.0, task=task))


# ------------------------------------------------------------------ offline fake model (tests + demos)
_MOCK_HI = {"Juliana": "जूलियाना", "Gerald": "जेराल्ड", "Clarissa": "क्लैरिसा", "Alexander": "अलेक्ज़ेंडर",
            "Father": "पिताजी", "Ashcroft": "ऐशक्रॉफ्ट"}


def _payload(user: str):
    m = re.search(r"INPUT_JSON:\s*(.*)$", user, flags=re.S)
    return json.loads(m.group(1)) if m else {}


def _mock_translate(text: str) -> str:
    words = [_MOCK_HI.get(w.strip(".,!?\"'"), "शब्द") for w in text.split()]
    return " ".join(words[: max(1, len(words))]) + "।"


def _mock_reply(task: str, user: str) -> str:
    p = _payload(user)
    if task == "glossary":
        names = p.get("speakers", [])
        entries = [{"kind": "character", "english": "Juliana", "target": "जूलियाना",
                    "aliases": ["LADY JULIANA", "JULIANA"], "note": "heroine"}]
        entries += [{"kind": "character", "english": n.title(), "target": n.title(), "aliases": [n], "note": ""}
                    for n in names if "JULIANA" not in n][:5]
        return json.dumps({"entries": entries})
    if task in ("adapt", "rewrite"):
        lines = p.get("lines", [])
        out = [{"id": l["id"], "target": _mock_translate(l.get("current") or l["english"])[: 40 if task == "rewrite" else 999]}
               for l in lines]
        return json.dumps({"lines": out, "summary": "Mock scene summary."})
    if task == "judge":
        return json.dumps({"hook_preserved": True, "hook_reason": "mock", "cliffhanger_preserved": True,
                           "cliffhanger_reason": "mock", "unnatural_lines": [], "suggestions": []})
    if task == "continuity":
        return json.dumps({"issues": []})
    if task == "reformat":
        return p.get("text", "")
    return "{}"
