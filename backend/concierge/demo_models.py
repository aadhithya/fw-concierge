"""Demo mode: deterministic, rule-based stand-ins for the model, so the whole flow runs offline and repeats exactly.

Each fake receives what a real model would (the agent's input as JSON, tool results) and answers the same way: with a tool
call named after the output class, or a call to the agent's own tool first. Nothing here is a real model.
"""

import json
import re
from datetime import date, timedelta

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from concierge.domain import NEIGHBOURHOODS, REGION

PREFERENCE_WORDS = {  # words in a request -> a preference phrase the providers can match
    "back": "back pain", "neck": "neck pain", "knee": "knee", "shoulder": "shoulder", "sciatica": "sciatica",
    "sport": "sports injury", "running": "running", "post-surgery": "post-surgery", "surgery": "post-surgery",
    "child": "paediatric", "kid": "paediatric", "pregnan": "pregnancy", "posture": "posture", "ankle": "ankle",
    "evening": "evening", "after work": "evening", "weekend": "weekend", "home visit": "home visit", "at home": "home visit",
    "wheelchair": "accessible", "accessible": "accessible",
}
ATTRIBUTE_PREFS = {"evening": "evenings", "weekend": "weekends", "home visit": "home_visits", "accessible": "accessible"}


def _window(text: str, today: date) -> tuple[date, date] | None:
    if m := re.search(r"\b(\d{4}-\d{2}-\d{2})\b", text):
        d = date.fromisoformat(m.group(1))
        return d, d
    if "tomorrow" in text:
        return today + timedelta(1), today + timedelta(1)
    if re.search(r"next (two|2) weeks|fortnight", text):
        return today + timedelta(1), today + timedelta(14)
    if "next week" in text:
        monday = today + timedelta(7 - today.weekday())
        return monday, monday + timedelta(6)
    if "this week" in text:
        return today + timedelta(1), today + timedelta(6 - today.weekday() or 1)
    if "weekend" in text:
        saturday = today + timedelta((5 - today.weekday()) % 7 or 7)
        return saturday, saturday + timedelta(1)
    if m := re.search(r"next (\d+) days", text):
        return today + timedelta(1), today + timedelta(int(m.group(1)))
    return None


def intake(inp: dict) -> dict:
    text, today = inp["conversation"].lower(), date.fromisoformat(inp["today"])
    out: dict = {"preferences": []}
    questions = []
    if re.search(r"physio|back|neck|knee|shoulder|hip|ankle|sciatica|injur|sport|rehab|pain", text):
        out["service_category"] = "physiotherapy"
    else:
        questions.append("I can only book physiotherapy at the moment. What do you need help with?")
    place = next((n for n in NEIGHBOURHOODS if n.lower() in text), REGION if REGION.lower() in text or "anywhere" in text else None)
    if place:
        out["location"] = place
    else:
        questions.append(f"Which area would suit you? ({', '.join(NEIGHBOURHOODS)}, or anywhere in {REGION})")
    window = _window(text, today)
    if window:
        out["date_from"], out["date_to"] = window[0].isoformat(), window[1].isoformat()
    else:
        questions.append("When would you like to be seen? For example 'next week' or 'tomorrow'.")
    for word, phrase in PREFERENCE_WORDS.items():
        if word in text and phrase not in out["preferences"]:
            out["preferences"].append(phrase)
    out["open_questions"] = questions[:1]  # one focused question at a time
    return out


def research(inp: dict, tool_text: str | None, tool_failed: bool) -> dict | tuple[str, dict]:
    req, prov = inp["request"], inp["provider"]
    if tool_text is None:
        return "check_availability", {"provider_id": prov["id"], "date_from": req["date_from"], "date_to": req["date_to"]}
    if tool_failed:
        return {"availability_checked": False, "concerns": ["availability lookup failed"]}
    slot_ids = [line.split("|")[0].strip() for line in tool_text.splitlines() if "|" in line]
    matched, concerns = [], []
    for pref in req["preferences"]:
        attr = ATTRIBUTE_PREFS.get(pref)
        ok = bool(prov[attr]) if attr else any(pref in t or t in pref for t in prov["tags"])
        (matched if ok else concerns).append(
            {"evening": "evening appointments", "weekend": "weekend appointments", "home visit": "home visits",
             "accessible": "step-free access"}.get(pref, f"treats {pref}") if ok else pref
        )
    fit = "weak" if not slot_ids or (req["preferences"] and not matched) else ("strong" if not concerns else "partial")
    return {"fit": fit, "matched": matched, "concerns": concerns, "slot_ids": slot_ids[:6], "availability_checked": True}


def evaluate(inp: dict) -> dict:
    rank = {"strong": 2, "partial": 1, "weak": 0}
    usable = [c for c in inp["candidates"] if c["fit"] != "weak" and c["slot_ids"]]
    usable.sort(key=lambda c: (-rank[c["fit"]], -len(c["matched"]), c["price_band"], c["provider_id"]))
    top = usable[:3]
    if not top:
        return {"summary": "No provider matches this request with open slots. Try a wider area or a different week."}
    reasons, slots = [], []
    for c in top:
        bits = c["matched"] or ["has open slots in your window"]
        reasons.append(f"{c['provider_id']}: {'; '.join(bits)}; price band {c['price_band']} of 3")
        slots += c["slot_ids"][:3]
    return {
        "ranked_provider_ids": [c["provider_id"] for c in top],
        "reasons": reasons,
        "slot_ids": slots,
        "summary": f"Shortlisted {len(top)} of {len(inp['candidates'])} providers researched.",
    }


class RuleModel(BaseChatModel):
    role: str
    counter: int = 0

    @property
    def _llm_type(self) -> str:
        return "demo-rules"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        human = next(m for m in messages if m.type == "human")
        inp = json.loads(str(human.content))
        self.counter += 1
        call_id = f"demo-{self.counter}"
        if self.role == "intake":
            call = ("IntakeOutput", intake(inp))
        elif self.role == "evaluator":
            call = ("Evaluation", evaluate(inp))
        else:
            tool_msg = next((m for m in reversed(messages) if m.type == "tool"), None)
            result = research(inp, str(tool_msg.content) if tool_msg else None, bool(tool_msg and tool_msg.status == "error"))
            call = result if isinstance(result, tuple) else ("Findings", result)
        name, args = call
        message = AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}])
        return ChatResult(generations=[ChatGeneration(message=message)])
