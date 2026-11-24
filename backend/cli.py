"""Interactive chat in the terminal (PROJECT_SPEC §8.2, §9; START_HERE M5).

  python cli.py                       # chat; /new starts a new conversation, /exit quits
  python cli.py --ask "question"      # one question, then exit

Answers stream as they are written. After each answer the numbered sources are listed, and a
warning is shown if the citation check failed. The conversation history is kept here and
given to the pipeline, which uses the last two exchanges to rewrite follow-up questions.
"""

import argparse
import asyncio
import logging
import sys

import structlog

from config import get_settings
from src.generation.ollama_client import OllamaError
from src.generation.pipeline import (
    Done,
    QuestionError,
    RagPipeline,
    Result,
    SourceInfo,
    SourcesReady,
    Status,
    Token,
)
from src.generation.prompts import Exchange
from src.retrieval.indexes import IndexNotReady

STAGE_TEXT = {"rewriting": "Understanding your question…", "retrieving": "Searching documents…",
              "reranking": "Ranking passages…", "generating": "Writing answer…"}
HELP = "Commands: /new (new conversation), /exit (quit). Anything else is a question."


def format_source(s: SourceInfo, cited: bool = False) -> str:
    where = f"p. {s.page}" if s.page is not None else "SOP"
    fictional = "  [Fictional]" if s.is_fictional else ""
    used = "  ← cited" if cited else ""
    return (f"  [{s.n}] {s.doc_code} §{s.section} {s.section_title} · {s.version} · "
            f"{where}{fictional}  (score {s.score:.1f}){used}")


def format_footer(result: Result) -> list[str]:
    lines = []
    if result.answer_type == "answered":
        check = result.citation_check
        lines += ["", "Sources:"] + [format_source(s, s.n in check.cited) for s in result.sources]
        if check.status == "invalid_citation":
            lines.append(f"⚠ Some citations couldn't be verified: {check.invalid} are not "
                         f"among the {len(result.sources)} sources.")
        elif check.status == "uncited_answer":
            lines.append("⚠ This answer has no citations. Verify it against the sources.")
        if result.truncated:
            lines.append("⚠ The answer was cut off at the length limit.")
        lines.append("Verify against the cited source before acting.")
    elif result.answer_type == "retrieval_refusal":
        lines.append(f"(top relevance score {result.top_score:.1f} is below the threshold; "
                     "the model was not called. Try rephrasing.)")
    t = result.latency_ms
    lines.append(f"[{result.answer_type} · rewrite {t['rewrite']} ms · retrieval "
                 f"{t['retrieval']} ms · rerank {t['rerank']} ms · first token {t['ttft']} ms · "
                 f"total {t['total']} ms]")
    return lines


async def ask(pipeline: RagPipeline, question: str, history: list[Exchange]) -> Result | None:
    """Stream one answer to the terminal. Returns the Result, or None if it failed."""
    answered_text = False
    try:
        async for event in pipeline.stream(question, history):
            if isinstance(event, Status):
                print(f"\r{STAGE_TEXT[event.stage]:<40}", end="", flush=True, file=sys.stderr)
            elif isinstance(event, Token):
                if not answered_text:
                    print("\r" + " " * 40 + "\r", end="", file=sys.stderr)
                    answered_text = True
                print(event.text, end="", flush=True)
            elif isinstance(event, Done):
                print("\r" + " " * 40 + "\r", end="", file=sys.stderr)
                if not answered_text:
                    print(event.result.answer, end="")
                print()
                if event.result.standalone_question != question:
                    print(f"(understood as: {event.result.standalone_question})")
                for line in format_footer(event.result):
                    print(line)
                return event.result
            elif isinstance(event, SourcesReady):
                pass
    except QuestionError as exc:
        print(f"\n{exc}")
    except OllamaError as exc:
        print(f"\n[{exc.code}] {exc}")
    return None


async def chat(pipeline: RagPipeline) -> None:
    history: list[Exchange] = []
    print(HELP)
    loop = asyncio.get_running_loop()
    while True:
        try:
            line = (await loop.run_in_executor(None, input, "\nYou> ")).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not sys.stdin.isatty():
            print(line)  # piped input is not echoed by a terminal: keep transcripts readable
        if line in ("/exit", "/quit"):
            return
        if line == "/new":
            history.clear()
            print("New conversation.")
            continue
        if not line:
            continue
        print()
        result = await ask(pipeline, line, history)
        if result is not None:  # a failed question is not part of the conversation
            history.append(Exchange(line, result.answer))


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ask", help="answer one question and exit")
    parser.add_argument("--verbose", action="store_true", help="show the pipeline's log lines")
    args = parser.parse_args()
    if not args.verbose:  # log lines would be printed in the middle of the answer
        structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.WARNING))
    print("Loading models and index…", file=sys.stderr)
    try:
        pipeline = RagPipeline(get_settings())
        await pipeline.warm_up()
    except IndexNotReady as exc:
        print(f"[{exc.code}] {exc}")
        return 1
    except OllamaError as exc:
        print(f"[{exc.code}] {exc}")
        return 1
    try:
        if args.ask:
            return 0 if await ask(pipeline, args.ask, []) else 1
        await chat(pipeline)
        return 0
    finally:
        await pipeline.aclose()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
