"""Embedding provider；默认哈希向量离线可复现，可选 OpenAI `/embeddings`。"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import urllib.request
from collections.abc import Mapping
from typing import Protocol
from app.runtime.executor import managed_call, runtime_managed
from app.runtime.contracts import ProviderEnvelope, RuntimeFailure

ASCII_RE = re.compile(r"[a-zA-Z0-9_]+")
CHINESE_RE = re.compile(r"[\u4e00-\u9fff]+")


def text_features(text: str) -> list[str]:
    lowered = (text or "").lower()
    out = ASCII_RE.findall(lowered)
    for seq in CHINESE_RE.findall(lowered):
        out.extend(seq[i:i + 2] for i in range(max(0, len(seq) - 1)))
        if len(seq) <= 6:
            out.append(seq)
    return [x for x in out if x]


class EmbeddingProvider(Protocol):
    kind: str
    model: str
    dimensions: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class HashEmbeddingProvider:
    kind = "hash"
    model = "dora-hash-bigram-v1"
    external = False

    def __init__(self, dimensions: int = 256):
        if dimensions < 32:
            raise ValueError("embedding dimensions 至少为 32")
        self.dimensions = dimensions

    @runtime_managed
    def embed(self, texts: list[str], *, run_context=None) -> list[list[float]]:
        return managed_call('rag-search', run_context, 'index_embedding' if run_context and run_context.profile.route == 'rag-index' else 'query_embedding',
                            self, {'input': texts}, lambda a: ProviderEnvelope([self._one(text) for text in texts]), output_tokens=0)

    def _one(self, text: str) -> list[float]:
        vec = [0.0] * self.dimensions
        for feature in text_features(text):
            digest = hashlib.sha256(feature.encode("utf-8")).digest()
            idx = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vec[idx] += sign
        norm = math.sqrt(sum(v * v for v in vec))
        return [v / norm for v in vec] if norm else vec


class OpenAIEmbeddingProvider:
    kind = "openai"
    external = True
    supports_timeout = True

    def __init__(self, api_key: str, model: str = "text-embedding-3-small", dimensions: int = 512,
                 base_url: str = "https://api.openai.com/v1", timeout: float = 20.0):
        if not api_key:
            raise ValueError("OpenAI embedding provider 需要 API key")
        self.api_key, self.model, self.dimensions = api_key, model, dimensions
        self.base_url, self.timeout = base_url.rstrip("/"), timeout

    @runtime_managed
    def embed(self, texts: list[str], *, run_context=None) -> list[list[float]]:
        payload = {"model": self.model, "input": texts, "dimensions": self.dimensions}
        def perform(attempt):
            if self.timeout <= 0: raise RuntimeFailure('configuration_error')
            attempt.timeout = min(attempt.timeout, self.timeout)
            raw = attempt.post_json(f"{self.base_url}/embeddings", self.api_key, payload, 'embeddings')
            vectors = self._parse(raw, len(texts))
            return ProviderEnvelope(vectors, attempt.usage, self.model, attempt.response_model, attempt.response_id)
        stage = 'index_embedding' if run_context and run_context.profile.route == 'rag-index' else 'query_embedding'
        return managed_call('rag-search', run_context, stage, self, payload, perform, output_tokens=0)

    def _parse(self, raw, expected_count):
        if not isinstance(raw, Mapping) or not isinstance(raw.get('data'), list) or len(raw['data']) != expected_count:
            raise RuntimeFailure('invalid_vector')
        vectors = [None] * expected_count
        for row in raw['data']:
            if not isinstance(row, Mapping):
                raise RuntimeFailure('invalid_vector')
            index, vector = row.get('index'), row.get('embedding')
            if type(index) is not int or not 0 <= index < expected_count or vectors[index] is not None:
                raise RuntimeFailure('invalid_vector')
            try:
                valid = isinstance(vector, list) and len(vector) == self.dimensions and all(
                    type(x) in (float, int) and math.isfinite(x) for x in vector)
            except (OverflowError, TypeError, ValueError):
                valid = False
            if not valid:
                raise RuntimeFailure('invalid_vector')
            vectors[index] = vector
        return vectors


def resolve_embedding_provider() -> EmbeddingProvider:
    kind = os.environ.get("DORA_RAG_EMBEDDING_PROVIDER", "hash").strip().lower()
    if kind == "hash":
        return HashEmbeddingProvider(int(os.environ.get("DORA_RAG_HASH_DIMENSIONS", "256")))
    if kind == "openai":
        return OpenAIEmbeddingProvider(
            api_key=os.environ.get("DORA_RAG_OPENAI_API_KEY") or os.environ.get("OPENAI_API_KEY", ""),
            model=os.environ.get("DORA_RAG_EMBEDDING_MODEL", "text-embedding-3-small"),
            dimensions=int(os.environ.get("DORA_RAG_EMBEDDING_DIMENSIONS", "512")),
            base_url=os.environ.get("DORA_RAG_OPENAI_BASE_URL", "https://api.openai.com/v1"),
        )
    raise ValueError(f"未知 embedding provider: {kind}")


def cosine(a: list[float], b: list[float]) -> float:
    if not a or len(a) != len(b):
        return 0.0
    return sum(x * y for x, y in zip(a, b))
