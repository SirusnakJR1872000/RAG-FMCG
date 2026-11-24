"""Async client for the local Ollama server (PROJECT_SPEC §9.1, §15.6).

- One shared `httpx.AsyncClient` per OllamaClient (connection reuse, one place for timeouts).
- `num_ctx` is sent on EVERY call: Ollama's default context can be smaller than our prompt,
  and it then truncates the prompt silently — the model would answer from half the sources.
- Failures become typed errors the API layer maps to HTTP codes in M7:
  LLMUnavailable → 503 LLM_UNAVAILABLE, LLMTimeout → 504 LLM_TIMEOUT.
"""

import json
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx

from config import Settings

NS_PER_MS = 1_000_000


class OllamaError(Exception):
    """Base class; `code` is the API error code (§15.6)."""

    code = "LLM_ERROR"


class LLMUnavailable(OllamaError):
    code = "LLM_UNAVAILABLE"


class LLMTimeout(OllamaError):
    code = "LLM_TIMEOUT"


@dataclass
class CallStats:
    """What Ollama reports about one generation (filled when the call finishes)."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    load_ms: float = 0.0  # model load time; ~0 when the model is already resident
    prompt_eval_ms: float = 0.0
    eval_ms: float = 0.0
    done_reason: str = ""  # "stop" = finished, "length" = hit num_predict (answer cut off)

    @property
    def tokens_per_second(self) -> float:
        return self.completion_tokens / (self.eval_ms / 1000) if self.eval_ms else 0.0


class OllamaClient:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self.settings = settings
        self.model = settings.llm_model
        self._timeout = settings.llm_timeout_seconds
        self._http = httpx.AsyncClient(
            base_url=settings.ollama_base_url,
            timeout=httpx.Timeout(connect=5.0, read=self._timeout, write=30.0, pool=5.0),
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    # ── request building ──
    def _payload(self, system: str, user: str, max_tokens: int, stream: bool) -> dict:
        s = self.settings
        return {
            "model": self.model,
            "stream": stream,
            "keep_alive": s.llm_keep_alive,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "options": {
                "num_ctx": s.llm_num_ctx,  # ALWAYS set explicitly (§9.1)
                "temperature": s.llm_temperature,
                "top_p": s.llm_top_p,
                "repeat_penalty": s.llm_repeat_penalty,
                "num_predict": max_tokens,
            },
        }

    def _unavailable(self, exc: Exception) -> LLMUnavailable:
        return LLMUnavailable(
            f"Ollama is not reachable at {self.settings.ollama_base_url}. "
            f"Is it running? ({type(exc).__name__})")

    def _raise_for_status(self, response: httpx.Response) -> None:
        if response.status_code == 404:
            raise LLMUnavailable(
                f"Ollama has no model '{self.model}'. Install it with: ollama pull {self.model}")
        if response.is_error:
            raise OllamaError(f"Ollama returned HTTP {response.status_code}")

    # ── generation ──
    async def chat(self, system: str, user: str, max_tokens: int) -> tuple[str, CallStats]:
        """Blocking call: the whole answer at once."""
        stats = CallStats()
        text = "".join([t async for t in self.chat_stream(system, user, max_tokens, stats)])
        return text, stats

    async def chat_stream(self, system: str, user: str, max_tokens: int,
                          stats: CallStats | None = None) -> AsyncIterator[str]:
        """Yield the answer piece by piece. Stops cleanly if the consumer stops iterating."""
        stats = stats if stats is not None else CallStats()
        deadline = time.monotonic() + self._timeout  # whole-call limit (httpx limits each wait)
        try:
            async with self._http.stream(
                    "POST", "/api/chat", json=self._payload(system, user, max_tokens, True),
            ) as response:
                if response.is_error:
                    await response.aread()
                    self._raise_for_status(response)
                async for line in response.aiter_lines():
                    if time.monotonic() > deadline:
                        raise LLMTimeout(f"The model took longer than {self._timeout} s.")
                    if not line.strip():
                        continue
                    chunk = json.loads(line)
                    if "error" in chunk:
                        raise OllamaError(str(chunk["error"]))
                    piece = chunk.get("message", {}).get("content", "")
                    if piece:
                        yield piece
                    if chunk.get("done"):
                        self._fill_stats(stats, chunk)
                        return
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            raise self._unavailable(exc) from exc
        except httpx.ReadTimeout as exc:
            raise LLMTimeout(f"The model took longer than {self._timeout} s.") from exc
        except httpx.TransportError as exc:  # connection dropped mid-answer, etc.
            raise self._unavailable(exc) from exc

    @staticmethod
    def _fill_stats(stats: CallStats, chunk: dict) -> None:
        stats.prompt_tokens = chunk.get("prompt_eval_count", 0)
        stats.completion_tokens = chunk.get("eval_count", 0)
        stats.load_ms = chunk.get("load_duration", 0) / NS_PER_MS
        stats.prompt_eval_ms = chunk.get("prompt_eval_duration", 0) / NS_PER_MS
        stats.eval_ms = chunk.get("eval_duration", 0) / NS_PER_MS
        stats.done_reason = chunk.get("done_reason", "")

    # ── housekeeping ──
    async def ping(self) -> bool:
        """True if the server answers (used by /health in M7 and the CLI start-up)."""
        try:
            return (await self._http.get("/api/tags", timeout=5.0)).is_success
        except httpx.HTTPError:
            return False

    async def preload(self) -> None:
        """Load the model into RAM now (an empty prompt), so the first question isn't slow."""
        try:
            response = await self._http.post("/api/generate", json={
                "model": self.model, "prompt": "", "keep_alive": self.settings.llm_keep_alive,
                "options": {"num_ctx": self.settings.llm_num_ctx}})
        except httpx.TransportError as exc:
            raise self._unavailable(exc) from exc
        self._raise_for_status(response)

    async def loaded_models(self) -> list[dict]:
        """Models currently resident in Ollama's memory (name, size in bytes)."""
        try:
            response = await self._http.get("/api/ps", timeout=5.0)
            return response.json().get("models", []) if response.is_success else []
        except httpx.HTTPError:
            return []
