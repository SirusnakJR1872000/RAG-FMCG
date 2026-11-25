"""Hugging Face name or local folder (PROJECT_SPEC §10.3)."""

from scripts.build_index import model_hash
from src.model_paths import resolve_model
from src.retrieval.embeddings import prefixes_for


def test_a_huggingface_name_is_left_alone(tmp_path):
    assert resolve_model("intfloat/e5-small-v2", root=tmp_path) == "intfloat/e5-small-v2"


def test_a_project_folder_is_resolved_against_the_project_root(tmp_path):
    (tmp_path / "models" / "pharma-e5-small-v2-v1").mkdir(parents=True)
    assert resolve_model("models/pharma-e5-small-v2-v1", root=tmp_path) == str(
        tmp_path / "models" / "pharma-e5-small-v2-v1")


def test_an_absolute_folder_is_kept_and_a_missing_one_is_left_as_a_name(tmp_path):
    folder = tmp_path / "m"
    folder.mkdir()
    assert resolve_model(str(folder), root=tmp_path / "elsewhere") == str(folder)
    assert resolve_model("models/not-trained-yet", root=tmp_path) == "models/not-trained-yet"


def test_the_fine_tuned_model_keeps_its_base_models_prefixes():
    assert prefixes_for("models/pharma-e5-small-v2-v1") == ("query: ", "passage: ")
    assert prefixes_for("models/pharma-bge-small-en-v1.5-v1")[0].startswith("Represent this")


def test_a_local_model_folder_is_hashed_by_its_files(tmp_path, monkeypatch):
    import src.model_paths as mp

    folder = tmp_path / "models" / "pharma-x-v1"
    folder.mkdir(parents=True)
    (folder / "model.safetensors").write_bytes(b"weights-1")
    monkeypatch.setattr("scripts.build_index.resolve_model",
                        lambda name: mp.resolve_model(name, root=tmp_path))

    class Embedder:
        model_name = "models/pharma-x-v1"

    first = model_hash(Embedder())
    assert first.startswith("sha256:")
    (folder / "model.safetensors").write_bytes(b"weights-2")
    assert model_hash(Embedder()) != first  # retraining changes the hash
