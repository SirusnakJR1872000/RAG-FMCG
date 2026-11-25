"""The Ollama client used by the health endpoints (the pipeline has its own for answers)."""

from fastapi import Request

from src.generation.ollama_client import OllamaClient


def health_client(request: Request) -> OllamaClient:
    """The pipeline's client when there is one, else a standalone one (index not ready)."""
    pipeline = request.app.state.index.pipeline
    if pipeline is not None:
        return pipeline.client
    if request.app.state.health_client is None:
        request.app.state.health_client = OllamaClient(request.app.state.settings)
    return request.app.state.health_client
