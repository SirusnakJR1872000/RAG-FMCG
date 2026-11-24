"""Standalone rewrite of follow-up questions (PROJECT_SPEC §8.2 step 1, §9.5).

"What about retesting?" cannot be searched without its conversation, so the last two
exchanges are used to rewrite it as a question that stands alone. Runs on llama3.1:8b, the
only model loaded while serving (D-08). No history → no call. If the call fails, the
original question is used and the failure is logged (§9.5).
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass

import structlog

from src.generation.ollama_client import OllamaClient, OllamaError
from src.generation.prompts import Exchange, build_rewrite_prompt

log = structlog.get_logger(__name__)

MAX_REWRITE_CHARS = 300  # a longer "question" is the model rambling, not a rewrite
_LEAD_IN = re.compile(r"^\s*(standalone question|rewritten question|question)\s*:\s*", re.I)


# Words that point back at the conversation. Deliberately inclusive: a needless rewrite only
# costs time (the prompt returns a standalone question unchanged); a missed one costs the answer.
_REFERENCE_WORDS = frozenset({
    "it", "its", "they", "them", "their", "this", "that", "these", "those", "same", "above",
    "previous", "earlier", "former", "latter", "such", "one", "ones", "he", "she"})
_FOLLOW_UP_OPENERS = ("and ", "but ", "also ", "so ", "then ", "what about", "how about", "why")
SHORT_QUESTION_WORDS = 4  # "and retesting?" cannot be searched without its conversation


def needs_context(question: str) -> bool:
    """True if the question probably depends on earlier turns (pronoun, opener, or very short)."""
    text = question.lower().strip()
    words = re.findall(r"[a-z']+", text)
    return (len(words) <= SHORT_QUESTION_WORDS or text.startswith(_FOLLOW_UP_OPENERS)
            or any(w in _REFERENCE_WORDS for w in words))


def should_rewrite(question: str, history: Sequence[Exchange], turns: int) -> bool:
    """Rewrite only with history (§8.2 step 1) and only if the question needs it.

    Found with the real model: asked to rewrite "What does Annex 11 say about audit trails?"
    after a conversation about OOS, llama3.1:8b turned it into a question about OOS
    documentation. A self-contained question is searched as it was typed.
    """
    return bool(history) and turns > 0 and needs_context(question)


@dataclass(frozen=True)
class Rewrite:
    question: str  # what to search with
    rewritten: bool  # True if the model produced a usable rewrite
    failed: bool = False  # True if the call failed (original question used)


_SECTION_SIGN = re.compile(r"§")
_MARKER = re.compile(r"\[\d+")
_VERSION = re.compile(r"\(v?\d+(?:\.\d+)*\)")
_DOC_CODE = re.compile(r"\b[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+\b")  # ICH-Q7, ACME-SOP-QC-007, EU-ANNEX11


def introduces_source_labels(rewrite: str, question: str) -> bool:
    """True if the rewrite contains source-label debris the user never typed.

    Small models sometimes copy "ACME-SOP-QC-007 §1 Purpose (v3.0)" from the previous answer
    into the new question, which then searches for the label instead of the topic.
    A document code the user themselves wrote in the new question is fine.
    """
    if _SECTION_SIGN.search(rewrite) or _MARKER.search(rewrite) or _VERSION.search(rewrite):
        return True
    asked = question.upper()
    return any(code.upper() not in asked for code in _DOC_CODE.findall(rewrite))


def clean_rewrite(raw: str) -> str:
    """One line, no quotes or lead-in such as 'Standalone question:'."""
    lines = [ln.strip() for ln in raw.strip().splitlines() if ln.strip()]
    if not lines:
        return ""
    return _LEAD_IN.sub("", lines[0]).strip().strip("\"'“”").strip()


async def rewrite_question(client: OllamaClient, question: str, history: Sequence[Exchange],
                           turns: int, max_tokens: int) -> Rewrite:
    if not should_rewrite(question, history, turns):
        return Rewrite(question, rewritten=False)
    system, user = build_rewrite_prompt(question, list(history)[-turns:])
    try:
        raw, _ = await client.chat(system, user, max_tokens)
    except OllamaError as exc:
        log.warning("rewrite_failed", error=str(exc), code=exc.code)
        return Rewrite(question, rewritten=False, failed=True)
    standalone = clean_rewrite(raw)
    if not standalone or len(standalone) > MAX_REWRITE_CHARS:
        log.warning("rewrite_unusable", raw=raw[:200])
        return Rewrite(question, rewritten=False, failed=True)
    if introduces_source_labels(standalone, question):
        log.warning("rewrite_copied_source_labels", raw=raw[:200])
        return Rewrite(question, rewritten=False, failed=True)
    return Rewrite(standalone, rewritten=True)
