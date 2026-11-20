"""Markdown loader for the internal SOPs (PROJECT_SPEC §7.1).

Same output shape as the PDF loader. Markdown has no pages, so the whole file is one
PageText with page=None; sections come from the headings (§7.2).
"""

from pathlib import Path

from src.ingestion.normalize import LoadedDocument, PageText, normalize_text


def load_markdown(path: Path) -> LoadedDocument:
    text = normalize_text(path.read_text(encoding="utf-8"))
    return LoadedDocument(path=path, pages=[PageText(page=None, text=text)])
