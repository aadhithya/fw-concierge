"""Demo mode: deterministic, rule-based stand-ins for the model, so the whole flow runs offline and repeats exactly.

Each fake receives what a real model would (the agent's input as JSON, tool results) and answers the same way: with a tool
call named after the output class, or a call to the agent's own tool first. Nothing here is a real model.
"""

import json
import re
from datetime import date, datetime, timedelta

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult

from concierge.domain import NEIGHBOURHOODS, REGION, Provider, match_preferences

PREFERENCE_WORDS = {  # words in a request -> a preference phrase the providers can match
    "back": "back pain",
    "neck": "neck pain",
    "knee": "knee",
    "shoulder": "shoulder",
    "sciatica": "sciatica",
    "sport": "sports injury",
    "running": "running",
    "post-surgery": "post-surgery",
    "surgery": "post-surgery",
    "child": "paediatric",
    "kid": "paediatric",
    "pregnan": "pregnancy",
    "posture": "posture",
    "ankle": "ankle",
    "evening": "evening",
    "after work": "evening",
    "weekend": "weekend",
    "home visit": "home visit",
    "at home": "home visit",
    "wheelchair": "accessible",
    "accessible": "accessible",
}


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


def intake(text: str, today: date) -> tuple[dict, list[str]]:
    """Rules standing in for the model's understanding of a request: what we got, and what is still missing."""
    text = text.lower()
    args: dict = {"preferences": []}
    questions = []
    place = next(
        (n for n in NEIGHBOURHOODS if n.lower() in text),
        REGION if REGION.lower() in text or "münchen" in text or "anywhere" in text else None,
    )
    if place:
        args["location"] = place
    else:
        questions.append(f"Which area would suit you? ({', '.join(NEIGHBOURHOODS)}, or anywhere in {REGION})")
    window = _window(text, today)
    if window:
        args["date_from"], args["date_to"] = window[0].isoformat(), window[1].isoformat()
    else:
        questions.append("When would you like to be seen? For example 'next week' or 'tomorrow'.")
    for word, phrase in PREFERENCE_WORDS.items():
        if word in text and phrase not in args["preferences"]:
            args["preferences"].append(phrase)
    return args, questions


def _is_wake(message) -> bool:
    """The application's message that tells the chat how its research ended (not typed by the user)."""
    return message.type == "human" and str(message.content).startswith("<background_result")


def wake_reply(text: str) -> str:
    """The demo concierge's answer to the outcome of its research."""
    status = (re.search(r'status="(\w+)"', text) or [None, "FAILED"])[1]
    if status == "SUCCESS":
        result = json.loads(text[text.index("{") : text.rindex("}") + 1])
        # the framework wraps the job's output; accept it either wrapped or bare
        shortlist = (result.get("output") or result).get("shortlist", [])
        if not shortlist:
            return "The research finished, but nothing suitable came up. Try a wider area or different dates."
        names = ", ".join(f"{i['provider']['name']} ({i['provider']['neighbourhood']})" for i in shortlist[:3])
        return f"The research finished. Top options: {names}. Pick a slot in the booking pane and I'll help you prepare it."
    notes = [line[2:] for line in text.splitlines() if line.startswith("- ")]
    detail = f" The job reported: {'; '.join(notes[-2:])}." if notes else ""
    return f"The research failed.{detail} Press Retry on the research card to run it again."


def chat(messages) -> AIMessage:
    """The demo concierge: asks one question, or starts the research with `start_background`, then confirms. Only the
    conversation after the last started research or research outcome counts, as a real model would treat it."""
    if _is_wake(messages[-1]):
        return AIMessage(content=wake_reply(str(messages[-1].content)))
    last_tool = max((i for i, m in enumerate(messages) if m.type == "tool"), default=-1)
    last_wake = max((i for i, m in enumerate(messages) if _is_wake(m)), default=-1)
    if messages[-1].type == "tool":
        try:
            json.loads(str(messages[-1].content))["job_id"]
        except (ValueError, KeyError, TypeError):  # the framework refused the input: say so, and ask again
            return AIMessage(content="Sorry, I couldn't use that. Could you tell me the area and the dates again?")
        call = next(m for m in reversed(messages) if m.type == "ai" and m.tool_calls).tool_calls[0]["args"]
        done = json.loads(call["input_json"])
        prefs = f" Preferences: {', '.join(done['preferences'])}." if done["preferences"] else ""
        when = done["date_from"] if done["date_from"] == done["date_to"] else f"{done['date_from']} to {done['date_to']}"
        return AIMessage(
            content=f"Here is what I understood: physiotherapy in {done['location']}, {when}.{prefs} I've started the research."
        )
    text = " ".join(str(m.content) for m in messages[max(last_tool, last_wake) + 1 :] if m.type == "human" and not _is_wake(m))
    args, questions = intake(text, date.today())
    if questions:
        return AIMessage(content=questions[0])  # one focused question at a time
    call = {"agent_name": "researcher", "input_json": json.dumps(args)}
    return AIMessage(content="", tool_calls=[{"name": "start_background", "args": call, "id": "demo-start"}])


def brief(inp: dict) -> dict:
    """Demo briefer: compares the request's preferences with the provider's known attributes (the shared matching)."""
    matched, concerns = match_preferences(Provider(**inp["provider"]), inp["request"]["preferences"])
    return {
        "matches": matched or ["has an open slot in your window"],
        "concerns": [f"does not list '{c}'" for c in concerns],
        "before_you_go": ["Arrive ten minutes early", "Bring any earlier scans or referral letters"],
    }


def write_confirmation(inp: dict) -> dict:
    """Demo writer: a confirmation sentence from the verified provider and slot."""
    prov, slot, brief_ = inp["provider"], inp["slot"], inp["briefing"]
    when = datetime.fromisoformat(slot["starts_at"]).strftime("%a %d %b at %H:%M")
    note = brief_["matches"][0] if brief_["matches"] else "an open slot"
    return {
        "text": f"{prov['name']} in {prov['neighbourhood']}, {when} ({slot['duration_min']} minutes): {note}. This is a simulated booking; nothing real is reserved."
    }


def _text(content) -> str:
    """The text of a tool result. An MCP tool returns a list of content blocks, not a string."""
    if isinstance(content, list):
        return "\n".join(block.get("text", "") if isinstance(block, dict) else str(block) for block in content)
    return str(content)


class RuleModel(BaseChatModel):
    role: str
    counter: int = 0

    @property
    def _llm_type(self) -> str:
        return "demo-rules"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.counter += 1
        if self.role == "chat":
            return ChatResult(generations=[ChatGeneration(message=chat(messages))])
        inp = json.loads(str(next(m for m in messages if m.type == "human").content))  # the agent's input, as JSON
        if self.role == "researcher":
            tool_msg = next((m for m in reversed(messages) if m.type == "tool"), None)
            if tool_msg is None:  # call the one tool, as the prompt says
                name, args = (
                    "providers_search_providers",
                    {
                        "location": inp["location"],
                        "date_from": inp["date_from"],
                        "date_to": inp["date_to"],
                        "preferences": inp["preferences"],
                        "sleep_seconds": inp["provider_sleep_seconds"],
                    },
                )
            else:  # forward what it returned
                data = json.loads(_text(tool_msg.content))
                found = data["providers"]
                summary = (
                    f"Found {len(found)} of {data['considered']} providers with open slots."
                    if found
                    else "No provider matches this request."
                )
                name, args = "ResearchResult", {"shortlist": found, "considered": data["considered"], "summary": summary}
        elif self.role == "briefer":
            name, args = "Briefing", brief(inp)
        elif self.role == "writer":
            name, args = "Confirmation", write_confirmation(inp)
        else:
            raise ValueError(f"no demo model for role {self.role!r}")
        message = AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": f"demo-{self.counter}"}])
        return ChatResult(generations=[ChatGeneration(message=message)])

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        """Stream the same answer in pieces, as a real model does: the words of a reply, or a tool call's arguments whole."""
        answer = self._generate(messages).generations[0].message
        for i, call in enumerate(answer.tool_calls):
            chunk = {"name": call["name"], "args": json.dumps(call["args"]), "id": call["id"], "index": i}
            yield ChatGenerationChunk(message=AIMessageChunk(content="", tool_call_chunks=[chunk]))
        words = str(answer.content).split(" ") if answer.content else []
        for i, word in enumerate(words):
            yield ChatGenerationChunk(message=AIMessageChunk(content=word + (" " if i < len(words) - 1 else "")))
