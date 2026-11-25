"""A fake Ollama server for tests (CLAUDE.md: tests never call the real Ollama).

Plugs into OllamaClient as an httpx transport, so the real client code — payloads, streaming,
error mapping — runs against deterministic replies. It records every request so tests can
assert what was sent (num_ctx, model, which prompt, how many calls).

Which reply is sent is decided by the system prompt: the follow-up rewrite prompt mentions
"standalone question"; anything else is an answer call.
"""

import json

import httpx


class FakeOllama:
    def __init__(self, answer: str = "An OOS result must be investigated [1].",
                 rewrite: str = "What must happen after an OOS result?"):
        self.answer = answer
        self.rewrite = rewrite
        self.requests: list[dict] = []  # parsed JSON bodies of /api/chat calls
        self.paths: list[str] = []
        self.generate_calls: list[dict] = []  # preload requests (/api/generate)
        self.fail: Exception | None = None  # raised for every call (e.g. httpx.ConnectError)
        self.fail_rewrite: Exception | None = None  # raised only for rewrite calls
        self.status: int = 200  # HTTP status for /api/chat (404 = model not pulled)
        self.fail_times: int = 0  # the next N chat calls fail with HTTP 500, then work again
        self.pieces: list[str] | None = None  # exact token pieces of the answer (default: words)
        self.done_reason = "stop"  # "length" = the answer was cut off at num_predict
        self.models_loaded = [{"name": "llama3.1:8b", "size": 6_000_000_000}]

    # ── helpers for assertions ──
    @property
    def answer_calls(self) -> list[dict]:
        return [r for r in self.requests if not self._is_rewrite(r)]

    @property
    def rewrite_calls(self) -> list[dict]:
        return [r for r in self.requests if self._is_rewrite(r)]

    @staticmethod
    def _is_rewrite(body: dict) -> bool:
        return "standalone question" in body["messages"][0]["content"].lower()

    # ── the transport ──
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.paths.append(request.url.path)
        if self.fail is not None:
            raise self.fail
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": []})
        if request.url.path == "/api/ps":
            return httpx.Response(200, json={"models": self.models_loaded})
        if request.url.path == "/api/generate":
            self.generate_calls.append(json.loads(request.content))
            return httpx.Response(200, json={"done": True})
        body = json.loads(request.content)
        self.requests.append(body)
        if self.fail_times > 0:
            self.fail_times -= 1
            return httpx.Response(500, json={"error": "runner crashed"})
        if self.status != 200:
            return httpx.Response(self.status, json={"error": "model not found"})
        rewrite = self._is_rewrite(body)
        if rewrite and self.fail_rewrite is not None:
            raise self.fail_rewrite
        text = self.rewrite if rewrite else self.answer
        if self.pieces is not None and not rewrite:
            pieces = list(self.pieces)
        else:
            pieces = [w + " " for w in text.split(" ")]
            pieces[-1] = pieces[-1].rstrip()
        if not body.get("stream", True):
            return httpx.Response(200, json=self._final(text))
        lines = [json.dumps({"message": {"role": "assistant", "content": p}, "done": False})
                 for p in pieces]
        lines.append(json.dumps(self._final("")))
        return httpx.Response(200, content="\n".join(lines).encode())

    def _final(self, text: str) -> dict:
        return {"message": {"role": "assistant", "content": text}, "done": True,
                "done_reason": self.done_reason, "prompt_eval_count": 1200, "eval_count": 40,
                "load_duration": 0, "prompt_eval_duration": 2_000_000_000,
                "eval_duration": 10_000_000_000}
