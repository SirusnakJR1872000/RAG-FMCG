"""Synthetic training questions for fine-tuning the embedding model (PROJECT_SPEC §10.2).

Usage (from backend/):
  python -m src.finetuning.generate_queries --sample 8 --raw ../data/trial_raw.jsonl \
      --pairs ../data/trial_pairs.jsonl --report trial_stats.md
  python -m src.finetuning.generate_queries                 # all steps; resumable

Steps:
  1. LEAKAGE CONTROL — every chunk that answers a *test*-split golden question, and every chunk
     of the same section, is excluded. The fine-tuned model must never have studied the exam.
  2. GENERATE — llama3.2:3b writes 3 questions per remaining chunk (offline only, D-09).
     Results are appended to data/train_raw.jsonl after every chunk, so an interrupted run
     continues where it stopped.
  3. FILTER — drop questions under 6 or over 40 words, near-duplicates, and questions whose
     chunk is not in the BM25 or base-model dense top-10 (the "round trip": a question the
     chunk does not really answer is a bad training pair).
  4. WRITE data/train_pairs.jsonl and reports/train_data_stats.md.

Run it with the other applications closed: it takes hours on this CPU.
"""

import argparse
import asyncio
import datetime as dt
import json
import re
import sys
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
import structlog

from config import PROJECT_ROOT, Settings, get_settings
from src.evaluation.golden import GoldenItem, SectionTree, is_hit, load_golden, load_section_trees
from src.generation.ollama_client import OllamaClient, OllamaError
from src.ingestion.manifest import sha256_of
from src.retrieval.bm25_store import BM25Store
from src.retrieval.embeddings import Embedder
from src.retrieval.faiss_store import FaissStore
from src.retrieval.indexes import chunks_path, index_dir, load_build_info

log = structlog.get_logger(__name__)

QUESTIONS_PER_CHUNK = 3
MIN_WORDS, MAX_WORDS = 6, 40
ROUND_TRIP_K = 10
GENERATION_OPTIONS = {"temperature": 0.7, "top_p": 0.9}  # variety matters more than precision
MAX_TOKENS = 220
GOLDEN = PROJECT_ROOT / "backend/tests/golden/golden_set.jsonl"

SYSTEM_PROMPT = ("You write realistic search questions for a pharmaceutical quality (GMP) "
                 "knowledge tool used by QA and compliance engineers.")
USER_TEMPLATE = """Passage:
<<<
{passage}
>>>

Write exactly 3 different questions that a QA or compliance engineer might ask and that this \
passage answers.
- Every question must be fully answerable from the passage alone. Do not ask about anything the \
passage does not state, and do not add details, numbers or situations that are not in it.
- Each question must make sense on its own: never say "the passage", "this section" or "the \
document".
- Use between 6 and 40 words.
- Vary them: one direct question; one that asks for the same fact with different words than the \
passage uses; one about a requirement or time limit in the passage (if it has none, a third \
direct question about another fact in it).
Output only the 3 questions, one per line, with no numbering and no other text."""


# ── step 1: leakage control ──────────────────────────────────────────────────────────────

def leaked_chunk_ids(chunks: pd.DataFrame, test_items: list[GoldenItem],
                     trees: dict[str, SectionTree]) -> set[str]:
    """Chunks that answer a test question: same document, section equal to or inside an
    expected section (a merged chunk such as 11.14–11.16 counts as each member)."""
    expected = [e for item in test_items if item.answerable for e in item.expected]
    leaked = set()
    for row in chunks[["chunk_id", "doc_code", "section"]].itertuples(index=False):
        if is_hit(trees, row.doc_code, row.section, [e for e in expected
                                                     if e.doc_code == row.doc_code]):
            leaked.add(row.chunk_id)
    return leaked


# ── step 2: prompt and parsing ───────────────────────────────────────────────────────────

_BULLET = re.compile(r"^\s*(?:[-*•]+|\d+[.)])\s*")


def build_prompt(embed_text: str) -> tuple[str, str]:
    return SYSTEM_PROMPT, USER_TEMPLATE.format(passage=embed_text.strip())


def parse_questions(raw: str) -> list[str]:
    """Questions from the model's reply: one per line, numbering and quotes removed."""
    questions: list[str] = []
    for line in raw.splitlines():
        text = _BULLET.sub("", line).strip().strip("\"'“”").strip()
        if text.endswith("?") and text not in questions:
            questions.append(text)
    return questions[:QUESTIONS_PER_CHUNK]


# ── step 3: filters ──────────────────────────────────────────────────────────────────────

def normalise(question: str) -> str:
    """Lowercase, punctuation removed, one space: 'What  is X?' == 'what is x'."""
    return " ".join(re.sub(r"[^a-z0-9\s]", " ", question.lower()).split())


@dataclass
class FilterStats:
    raw: int = 0
    too_short: int = 0
    too_long: int = 0
    duplicate: int = 0
    round_trip_failed: int = 0
    kept: int = 0
    per_chunk_kept: Counter = field(default_factory=Counter)


def filter_questions(rows: list[dict], in_top_k: Callable[[str, str], bool],
                     ) -> tuple[list[tuple[str, str]], FilterStats]:
    """(question, chunk_id) pairs that pass every filter, in file order, plus the counts.

    A question that is the same as an earlier one (after normalisation) is dropped, so one
    question never points at two different chunks.
    """
    stats, seen, pairs = FilterStats(), set(), []
    for row in rows:
        for question in row["questions"]:
            stats.raw += 1
            words = len(question.split())
            if words < MIN_WORDS:
                stats.too_short += 1
            elif words > MAX_WORDS:
                stats.too_long += 1
            elif (key := normalise(question)) in seen:
                stats.duplicate += 1
            elif not (seen.add(key) or in_top_k(question, row["chunk_id"])):
                stats.round_trip_failed += 1
            else:
                stats.kept += 1
                stats.per_chunk_kept[row["chunk_id"]] += 1
                pairs.append((question, row["chunk_id"]))
    return pairs, stats


class RoundTrip:
    """Is the chunk among the top-10 of BM25 or of the BASE embedding model for the question?"""

    def __init__(self, settings: Settings, chunks: pd.DataFrame):
        load_build_info(settings, settings.embedding_model)  # the base index must be current
        self.embedder = Embedder(settings.embedding_model)
        self.dense = FaissStore.load(index_dir(settings, settings.embedding_model))
        self.bm25 = BM25Store(chunks["chunk_id"].tolist(), chunks["embed_text"].tolist())

    def __call__(self, question: str, chunk_id: str) -> bool:
        bm25 = {cid for cid, _ in self.bm25.search(question, ROUND_TRIP_K)}
        if chunk_id in bm25:
            return True
        dense = {cid for cid, _ in
                 self.dense.search(self.embedder.embed_query(question), ROUND_TRIP_K)}
        return chunk_id in dense


def pick_chunks(eligible: list[str], limit: int = 0, sample: int = 0) -> list[str]:
    """All eligible chunks, or a trial subset: the first `limit`, or a seeded random `sample`."""
    if sample:
        rng = np.random.default_rng(42)
        picked = set(rng.choice(len(eligible), size=min(sample, len(eligible)), replace=False))
        return [cid for i, cid in enumerate(eligible) if i in picked]
    return eligible[:limit] if limit else eligible


RETRIES = 4  # a 3-hour job must not die on one HTTP 500 (the runner restarts under memory pressure)
RETRY_WAIT_SECONDS = 20


async def chat_with_retry(client: OllamaClient, system: str, user: str, *, retries: int = RETRIES,
                          wait: float = RETRY_WAIT_SECONDS, sleep=asyncio.sleep) -> str:
    """One generation call; a failed call is repeated after a pause, then the error is raised."""
    for attempt in range(retries + 1):
        try:
            reply, _ = await client.chat(system, user, MAX_TOKENS, GENERATION_OPTIONS)
            return reply
        except OllamaError as exc:
            if attempt == retries:
                raise
            print(f"    [{exc.code}] {exc} — retry {attempt + 1}/{retries} in {wait:.0f} s",
                  flush=True)
            await sleep(wait)
    raise AssertionError("unreachable")


# ── the long step: generation ────────────────────────────────────────────────────────────

def read_raw(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


async def generate(settings: Settings, chunks: pd.DataFrame, eligible: list[str], raw_path: Path,
                   ) -> int:
    """Ask llama3.2:3b for questions; append one JSON line per chunk. Returns chunks done."""
    done = {row["chunk_id"] for row in read_raw(raw_path)}
    todo = [cid for cid in eligible if cid not in done]
    print(f"{len(done)} chunks already done, {len(todo)} to go", flush=True)
    if not todo:
        return 0
    text = chunks.set_index("chunk_id")["embed_text"]
    big = OllamaClient(settings)  # free the RAM of the answer model before loading the small one
    small = OllamaClient(settings, model=settings.question_gen_model)
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    started, finished = time.perf_counter(), 0
    try:
        await big.unload()
        for i, chunk_id in enumerate(todo, start=1):
            system, user = build_prompt(text[chunk_id])
            reply = await chat_with_retry(small, system, user)
            row = {"chunk_id": chunk_id, "questions": parse_questions(reply),
                   "model": settings.question_gen_model,
                   "generated_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds")}
            with raw_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            finished += 1
            rate = (time.perf_counter() - started) / i
            print(f"  {i}/{len(todo)}  {len(row['questions'])} questions  {chunk_id[:46]:46}  "
                  f"ETA {rate * (len(todo) - i) / 60:.0f} min", flush=True)
        await small.unload()
    except OllamaError as exc:
        print(f"\n[{exc.code}] {exc}\nProgress is saved; run the same command again to continue.")
        raise SystemExit(1) from exc
    finally:
        await big.aclose()
        await small.aclose()
    return finished


# ── outputs ──────────────────────────────────────────────────────────────────────────────

def write_pairs(path: Path, pairs: list[tuple[str, str]], chunks: pd.DataFrame) -> None:
    """{question, chunk_id, positive_text}. positive_text is the text the model embeds at
    search time (document header + body); the training script adds the model's passage prefix."""
    text = chunks.set_index("chunk_id")["embed_text"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for question, chunk_id in pairs:
            row = {"question": question, "chunk_id": chunk_id, "positive_text": text[chunk_id]}
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def stats_report(settings: Settings, chunks: pd.DataFrame, leaked: set[str], eligible: list[str],
                 raw_rows: list[dict], stats: FilterStats, pairs: list[tuple[str, str]]) -> str:
    by_doc = chunks.set_index("chunk_id")["doc_code"]
    leaked_docs = Counter(by_doc[c] for c in leaked)
    pairs_docs = Counter(by_doc[c] for _, c in pairs)
    chunk_docs = Counter(chunks["doc_code"])
    covered = len({c for _, c in pairs})
    words = [len(q.split()) for q, _ in pairs] or [0]
    sample = np.random.default_rng(42).permutation(len(pairs))[:12]
    text = chunks.set_index("chunk_id")
    lines = [
        "# Training data statistics (spec §10.2)", "",
        f"Generated by `python -m src.finetuning.generate_queries` on "
        f"{dt.date.today().isoformat()}. Question model `{settings.question_gen_model}`; "
        f"round-trip check against BM25 and the base embedding model `{settings.embedding_model}`.",
        "", "## From chunks to pairs", "",
        "| Step | Count |", "|---|---|",
        f"| Chunks in `chunks.parquet` | {len(chunks)} |",
        f"| Excluded: they answer a **test**-split golden question (or share its section) | "
        f"{len(leaked)} |",
        f"| Chunks eligible for training | {len(eligible)} |",
        f"| Chunks with generated questions | {len(raw_rows)} |",
        f"| Questions generated | {stats.raw} |",
        f"| Dropped: under {MIN_WORDS} words | {stats.too_short} |",
        f"| Dropped: over {MAX_WORDS} words | {stats.too_long} |",
        f"| Dropped: duplicate | {stats.duplicate} |",
        f"| Dropped: chunk not in BM25 / dense top-{ROUND_TRIP_K} (round trip) | "
        f"{stats.round_trip_failed} |",
        f"| **Training pairs kept** | **{stats.kept}** |",
        f"| Chunks that have at least one pair | {covered} of {len(eligible)} eligible |",
        "", f"Question length: median {int(np.median(words))} words "
        f"(min {min(words)}, max {max(words)}).", "",
        "## Per document", "",
        "| Document | Chunks | Excluded (test leakage) | Training pairs |", "|---|---|---|---|"]
    for doc in sorted(chunk_docs):
        lines.append(f"| {doc} | {chunk_docs[doc]} | {leaked_docs.get(doc, 0)} | "
                     f"{pairs_docs.get(doc, 0)} |")
    lines += ["", "## Twelve random pairs (read them: are these questions the chunk answers?)", ""]
    for i in sample:
        question, chunk_id = pairs[i]
        row = text.loc[chunk_id]
        lines += [f"- **{question}**  \n  → {row['doc_code']} §{row['section']} "
                  f"{row['section_title']}: “{row['text'][:140].strip()}…”"]
    lines += [
        "", "## Notes", "",
        "- Dev-split answer chunks are **not** excluded (spec §10.2 excludes test only), so the "
        "dev comparison in D-12 can be somewhat optimistic; the test split is the clean number.",
        "- The chunk text is the text the model embeds at search time (document header + body).",
        ""]
    return "\n".join(lines)


async def run(args: argparse.Namespace) -> int:
    settings = get_settings()
    chunks = pd.read_parquet(chunks_path(settings))
    golden = load_golden(GOLDEN)
    leaked = leaked_chunk_ids(chunks, [g for g in golden if g.split == "test"],
                              load_section_trees(settings))
    eligible = [cid for cid in chunks["chunk_id"] if cid not in leaked]
    print(f"{len(chunks)} chunks; {len(leaked)} excluded for test-split leakage; "
          f"{len(eligible)} eligible", flush=True)
    selected = pick_chunks(eligible, args.limit, args.sample)
    raw_path = Path(args.raw)

    if args.stage in ("generate", "all"):
        await generate(settings, chunks, selected, raw_path)
    if args.stage in ("filter", "all"):
        wanted = set(selected)
        rows = [r for r in read_raw(raw_path) if r["chunk_id"] in wanted]
        pairs, stats = filter_questions(rows, RoundTrip(settings, chunks))
        out = Path(args.pairs)
        write_pairs(out, pairs, chunks)
        report = stats_report(settings, chunks, leaked, selected, rows, stats, pairs)
        report_path = settings.reports_dir / args.report
        report_path.write_text(report, encoding="utf-8")
        print(f"\n{stats.kept} training pairs from {stats.raw} questions → {out}\n"
              f"report: {report_path} (sha256 of chunks: {sha256_of(chunks_path(settings))[:12]})")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--stage", choices=["generate", "filter", "all"], default="all")
    parser.add_argument("--limit", type=int, default=0, help="trial: the first N eligible chunks")
    parser.add_argument("--sample", type=int, default=0, help="trial: N random eligible chunks")
    parser.add_argument("--raw", default=str(get_settings().data_dir / "train_raw.jsonl"))
    parser.add_argument("--pairs", default=str(get_settings().data_dir / "train_pairs.jsonl"))
    parser.add_argument("--report", default="train_data_stats.md")
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
