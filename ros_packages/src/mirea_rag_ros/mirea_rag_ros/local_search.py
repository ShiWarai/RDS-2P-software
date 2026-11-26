"""Полностью локальный retrieval по запечённому bundle — 1:1 с сервером.

Путь по умолчанию: ``BundleRetriever`` (dense + question nodes + sentence
nodes + BM25 + MaxSim + LTR) и локальная Qwen3-Embedding-0.6B для энкодинга
запроса. Если модель/зависимости ещё не установлены, есть явный fallback на
BM25-only (``mode="bm25"``), но он не считается полноценным режимом.
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Optional

import numpy as np

from . import config
from .bm25 import BM25Index
from .rag_client import fix_asr_aliases

log = logging.getLogger(__name__)

DEFAULT_TOP_K = 3


class BundleSearcher:
    """Dense/hybrid BundleRetriever с ленивой загрузкой эмбеддера."""

    def __init__(self, bundle_dir: str, top_k: int = DEFAULT_TOP_K,
                 mode: str = "full") -> None:
        self.bundle_dir = os.path.abspath(bundle_dir)
        self.top_k = int(top_k)
        self.mode = (mode or "full").strip().lower()
        self._retriever = None
        self._model = None
        self._bm25 = None
        self._payloads = None
        self._load_lock = threading.Lock()
        if not os.path.isdir(self.bundle_dir):
            raise FileNotFoundError(f"bundle не найден: {self.bundle_dir}")
        if self.mode == "bm25":
            self._load_bm25()

    # ---- full retrieval -------------------------------------------------- #
    def _ensure_full(self) -> None:
        if self._retriever is not None and self._model is not None:
            return
        with self._load_lock:
            if self._retriever is not None and self._model is not None:
                return
            from .bundle_retriever import BundleRetriever
            from sentence_transformers import SentenceTransformer

            log.info("local RAG: loading embedder %s", config.EMBEDDING_MODEL)
            self._model = SentenceTransformer(config.EMBEDDING_MODEL, device="cpu")
            log.info("local RAG: loading bundle %s", self.bundle_dir)
            self._retriever = BundleRetriever(
                self.bundle_dir,
                weights=config.BUNDLE_WEIGHTS,
                rrf_k=config.BUNDLE_RRF_K,
                pool_factor=config.BUNDLE_POOL_FACTOR,
                correct=config.BUNDLE_CORRECT,
                q_alpha=config.BUNDLE_Q_ALPHA,
                s_alpha=config.BUNDLE_S_ALPHA,
            )

    def _encode(self, query: str):
        prefixed = f"{config.EMBED_QUERY_PREFIX}{query}"
        if config.BUNDLE_MAXSIM_ENABLED:
            try:
                tok = self._model.encode(
                    prefixed, convert_to_numpy=True,
                    normalize_embeddings=False,
                    output_value="token_embeddings")
                if hasattr(tok, "detach"):
                    import torch
                    tok = tok.detach().to(torch.float32).cpu().numpy()
                tokens = np.asarray(tok, dtype=np.float32)
                return tokens[-1].copy(), tokens
            except Exception as e:  # noqa: BLE001
                log.warning("token encode failed (%s); pooled only", e)
        vec = self._model.encode(
            prefixed, convert_to_numpy=True, normalize_embeddings=False)
        return np.asarray(vec, dtype=np.float32), None

    def _search_full(self, clean: str) -> dict:
        from .query_expansion import expand_query

        self._ensure_full()
        prepared = self._retriever.prepare(expand_query(clean))
        vec, tokens = self._encode(prepared)
        results = self._retriever.search(
            vec, prepared, top_k=self.top_k, query_tokens=tokens)
        chunks = []
        for rank, r in enumerate(results, 1):
            payload = r.get("payload") or {}
            chunks.append({
                "id": int(r["id"]),
                "title": payload.get("source_title") or "",
                "section": payload.get("section") or "",
                "url": payload.get("source_url") or "",
                "text": payload.get("text") or "",
                "score": float(r.get("score") or 0.0),
                "fused_score": float(r.get("fused_score") or 0.0),
                "rank": rank,
                "arms": r.get("arms") or {},
            })
        best = max((c["score"] for c in chunks), default=0.0)
        result = {
            "clean_query": clean,
            "query": clean,
            "chunks": chunks,
            "conf_score": best,
            "fusion": "bundle",
        }
        # Guard не блокирует генерацию: при пустом/слабом ретривале всё равно
        # отвечает LLM (RKLLM) — честность держит system-промт.
        return result

    # ---- BM25 fallback --------------------------------------------------- #
    def _load_bm25(self) -> None:
        import sqlite3

        bm25_path = os.path.join(self.bundle_dir, "bm25_raw.pkl")
        db_path = os.path.join(self.bundle_dir, "rag.db")
        if not os.path.isfile(bm25_path) or not os.path.isfile(db_path):
            raise FileNotFoundError(
                f"bundle не найден: {self.bundle_dir} "
                f"(нужны bm25_raw.pkl и rag.db)")
        self._bm25 = BM25Index.load(bm25_path)
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        self._payloads = {
            int(row["id"]): dict(row)
            for row in con.execute(
                "SELECT id, text, source_title, source_url, section, kind "
                "FROM chunks ORDER BY id")
        }
        con.close()

    def _search_bm25(self, clean: str) -> dict:
        if self._bm25 is None:
            self._load_bm25()
        hits = self._bm25.search(clean, top_k=self.top_k)
        if not hits:
            return {
                "clean_query": clean,
                "query": clean,
                "chunks": [],
                "conf_score": 0.0,
                "fusion": "bm25-local",
            }
        best = hits[0][1] or 1.0
        chunks = []
        for rank, (doc_id, score) in enumerate(hits, 1):
            payload = self._payloads.get(int(doc_id)) or {}
            chunks.append({
                "id": int(doc_id),
                "title": payload.get("source_title") or "",
                "section": payload.get("section") or "",
                "url": payload.get("source_url") or "",
                "text": payload.get("text") or "",
                "score": float(score) / best,
                "rank": rank,
                "arms": {"bm25_local": float(score)},
            })
        return {
            "clean_query": clean,
            "query": clean,
            "chunks": chunks,
            "conf_score": max(0.0, min(1.0, float(best) / 5.0)),
            "fusion": "bm25-local",
        }

    def search(self, question: str, history: Optional[list] = None,
               top_k: Optional[int] = None) -> dict:
        clean = fix_asr_aliases(question)
        if top_k:
            self.top_k = int(top_k)
        if self.mode == "bm25":
            return self._search_bm25(clean)
        return self._search_full(clean)
