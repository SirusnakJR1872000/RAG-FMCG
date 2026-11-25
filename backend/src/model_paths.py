"""Hugging Face model names or folders of our own (the fine-tuned model, PROJECT_SPEC §10.3).

EMBEDDING_MODEL can be `intfloat/e5-small-v2` (downloaded and cached by Hugging Face) or
`models/pharma-e5-small-v2-v1` (a folder inside the project, written by the training script).
The name is kept as typed for prefixes and index folders; only loading needs the real path.
"""

from pathlib import Path

from config import PROJECT_ROOT


def resolve_model(name: str, root: Path = PROJECT_ROOT) -> str:
    """The folder if `name` is (relative to the project root, or absolutely) an existing
    directory; otherwise the name unchanged, for Hugging Face to resolve."""
    path = Path(name) if Path(name).is_absolute() else root / name
    return str(path) if path.is_dir() else name
