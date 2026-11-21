"""BundleRetriever — fast multi-entry search over the baked bundle.

Runtime path on the Orange Pi: the query is encoded once (NPU/CPU), then
candidate lists are produced by pure numpy + dict lookups — no server, no
ANN index, no Qdrant. The corpus is ~1.3k chunks; brute-force cosine over a
float16 matrix is sub-millisecond.

Entry points (signals):
  1. dense — cosine(query, chunk embeddings).
  2. questions — α · cosine(query, real past user question embeddings),
     max-pooled per chunk. The ASR-robust lever: a garbled microphone query
     sits closer to a real past question than to formal document prose.
  3. sentences — α · cosine(query, QA-answer sentence embeddings), max-pooled
     per parent chunk. Finer granularity than the whole-chunk vector: the
     cosine measures one sentence's meaning, not an average over the answer.
  4. bm25 — lexical scores over chunk text (spell-corrected query tokens).
  5. maxsim — ColBERT-style late interaction: mean over query tokens of the
     max cosine against the chunk's precomputed token vectors (PCA-projected
     to 256-d at bake time). Token-level semantics without a second model.

Fusion:
  * LTR (default when ``ltr_model.txt`` is baked): a LightGBM LambdaMART
    ranker scores every candidate from the signals above (see
    src/retrieval/ltr.py). Replaces hand-tuned RRF weights and the
    champion/anchor promotions — those become features, not rules.
  * RRF fallback (no model / no lightgbm): weighted RRF over the dense merge
    (max of chunk/question/sentence cosines) and BM25, with the BM25 champion
    promotion kept.

The returned ``score`` is the calibrated bi-encoder signal (max cosine across
chunk/question/sentence entries), NOT the fused rank score — the confidence
guard needs an honest cosine (fusion min-max gave fake ~100%). Ordering
follows the fused ranking; ``fused_score`` is kept for inspection.

The entity graph (rule-based NER surfaces + 2-hop expansion) was removed
2026-11-11 by decision: hardcoded word lists are overfitting, and the measured
2-hop expansion was net-negative.
"""
from __future__ import annotations

import logging
import os
import re
import sqlite3
import sys
from typing import Optional

import numpy as np

from . import config
from .bm25 import BM25Index, tokenize_ru
from .ltr import LTRRanker, feature_row

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# SymSpell-lite: corpus-vocabulary spell correction (edit distance ≤ 1)
# --------------------------------------------------------------------------- #

class VocabCorrector:
    """Delete-1 neighbourhood index over the corpus vocabulary.

    Only OUT-OF-VOCAB query tokens are candidates for correction (in-vocab
    tokens are never touched — valid Russian surface forms must survive).
    A replacement is accepted iff the highest-frequency vocab candidate is
    within edit distance `max_edit` of the token and appears at least
    `min_freq` times in the corpus. max_edit=1 matches our ASR noise model
    (one corrupted character per word); distance-2 was measured to "repair"
    grammatical but OOV proper nouns into wrong words, hurting clean queries.
    """

    def __init__(self, vocab: dict[str, int], min_freq: int = 3,
                 max_edit: int = 1) -> None:
        self.freq = vocab
        self.min_freq = min_freq
        self.max_edit = max_edit
        self._index: dict[str, list[str]] = {}
        for tok in vocab:
            self._insert(tok)

    def _insert(self, tok: str) -> None:
        self._index.setdefault(tok, [])
        for i in range(len(tok)):
            d = tok[:i] + tok[i + 1:]
            self._index.setdefault(d, []).append(tok)

    def _candidates(self, tok: str) -> list[str]:
        cands = {tok}
        cands.update(self._index.get(tok, []))
        for i in range(len(tok)):
            d = tok[:i] + tok[i + 1:]
            cands.update(self._index.get(d, []))
            if d in self.freq:
                cands.add(d)
        return [c for c in cands if c in self.freq]

    def correct_token(self, tok: str) -> str:
        if tok in self.freq:
            return tok
        cands = [c for c in self._candidates(tok)
                 if self.freq[c] >= self.min_freq
                 and _edit_distance_le(tok, c, self.max_edit)]
        if not cands:
            return tok
        return max(cands, key=lambda c: self.freq[c])

    def correct_text(self, text: str) -> tuple[str, list[tuple[str, str]]]:
        """Repair only OOV word tokens, preserving the original casing.

        The embedder is case-aware (proper nouns like МИРЭА carry signal), so
        we must NOT lowercase the whole query — only words that fail the
        vocabulary lookup get replaced by their corrected (lowercase) form.
        """
        fixes: list[tuple[str, str]] = []
        word_re = re.compile(r"[а-яёA-ЯЁa-zA-Z0-9]+")

        def repl(m: re.Match) -> str:
            w = m.group(0)
            lw = w.lower()
            if len(lw) >= 4:
                c = self.correct_token(lw)
                if c != lw:
                    fixes.append((lw, c))
                    return c
            return w

        return word_re.sub(repl, text), fixes


def _edit_distance_le(a: str, b: str, max_d: int) -> bool:
    """Bounded Levenshtein — bails out early, tiny words only."""
    la, lb = len(a), len(b)
    if abs(la - lb) > max_d:
        return False
    prev = list(range(lb + 1))
    for i in range(1, la + 1):
        cur = [i] + [0] * lb
        best = i
        for j in range(1, lb + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            best = min(best, cur[j])
        if best > max_d:
            return False
        prev = cur
    return prev[lb] <= max_d


# --------------------------------------------------------------------------- #
# BundleRetriever
# --------------------------------------------------------------------------- #

def _normed(a: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(a, axis=-1, keepdims=True)
    return (a / np.maximum(n, 1e-10)).astype(np.float32)


class BundleRetriever:
    def __init__(
        self,
        bundle_dir: str,
        weights: Optional[dict] = None,
        rrf_k: int = 60,
        pool_factor: int = 3,
        correct: bool = True,
        q_alpha: float = 1.0,
        s_alpha: float = 0.95,
    ) -> None:
        self.rrf_k = rrf_k
        self.pool_factor = pool_factor
        self.q_alpha = q_alpha
        self.s_alpha = s_alpha
        self.weights = weights or {"dense": 0.95, "bm25": 0.05}

        chunk_vecs = np.load(os.path.join(bundle_dir, "vectors_chunks.f16.npy"))
        self.chunk_vecs = _normed(chunk_vecs.astype(np.float32))
        self.n_chunks = self.chunk_vecs.shape[0]

        qpath = os.path.join(bundle_dir, "vectors_questions.f16.npy")
        if os.path.exists(qpath):
            qvecs = np.load(qpath).astype(np.float32)
            self.question_vecs = _normed(qvecs)
            self.q_chunk_ids = np.load(os.path.join(bundle_dir, "question_chunk_ids.npy"))
        else:
            self.question_vecs = None
            self.q_chunk_ids = None

        spath = os.path.join(bundle_dir, "vectors_sentences.f16.npy")
        if os.path.exists(spath):
            svecs = np.load(spath).astype(np.float32)
            self.sentence_vecs = _normed(svecs)
            self.s_chunk_ids = np.load(os.path.join(bundle_dir, "sentence_chunk_ids.npy"))
        else:
            self.sentence_vecs = None
            self.s_chunk_ids = None

        # MaxSim late-interaction assets (optional): padded token vectors,
        # per-chunk token counts, and the bake-time PCA projection.
        self.token_vecs = None
        self.token_lens = None
        self.maxsim_mean = None
        self.maxsim_components = None
        tpath = os.path.join(bundle_dir, "tokens_chunks.f16.npy")
        ppath = os.path.join(bundle_dir, "maxsim_pca.npz")
        if (getattr(config, "BUNDLE_MAXSIM_ENABLED", True)
                and os.path.exists(tpath) and os.path.exists(ppath)):
            self.token_vecs = np.load(tpath)            # (n, T, D) float16
            self.token_lens = np.load(os.path.join(bundle_dir, "token_lens.npy"))
            pca = np.load(ppath)
            self.maxsim_mean = pca["mean"].astype(np.float32)
            self.maxsim_components = pca["components"].astype(np.float32)

        # HNSW indices (usearch) — logarithmic NN search instead of brute-force.
        self._hnsw_chunks = None
        self._hnsw_questions = None
        if getattr(config, "HNSW_ENABLED", False):
            self._try_load_hnsw(bundle_dir)

        bm25_name = getattr(config, "BUNDLE_BM25_FILE",
                            os.environ.get("BUNDLE_BM25_NAME", "bm25_raw.pkl"))
        self.bm25 = BM25Index.load(os.path.join(bundle_dir, bm25_name))

        con = sqlite3.connect(f"file:{os.path.join(bundle_dir, 'rag.db')}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        self.payloads = [dict(r) for r in con.execute(
            "SELECT id, text, source_title, source_url, section, kind FROM chunks ORDER BY id")]
        try:
            vocab = {r[0]: r[1] for r in con.execute("SELECT token, freq FROM vocab_all")}
        except sqlite3.OperationalError:
            vocab = {r[0]: r[1] for r in con.execute("SELECT token, freq FROM vocab")}
        con.close()
        self.corrector = (
            VocabCorrector(vocab, max_edit=getattr(config, "BUNDLE_CORRECT_MAX_EDIT", 1))
            if correct else None
        )

        ltr_wanted = getattr(config, "BUNDLE_LTR_ENABLED", True)
        self.ltr = LTRRanker.load(bundle_dir) if ltr_wanted else None
        self.fusion_mode = "ltr" if self.ltr is not None else "rrf"
        if ltr_wanted and self.ltr is None:
            log.warning("FUSION FALLBACK: LTR enabled but unavailable — using "
                        "weighted RRF (dense+question+sentence max-merge + BM25). "
                        "Train scripts/train_ltr.py and install lightgbm to enable LTR.")
        elif not ltr_wanted:
            log.info("FUSION: LTR disabled by config — weighted RRF")

        log.info("BundleRetriever ready: %d chunks, %s questions, %s sentences, "
                 "maxsim=%s, fusion=%s, vocab %d",
                 self.n_chunks,
                 len(self.question_vecs) if self.question_vecs is not None else 0,
                 len(self.sentence_vecs) if self.sentence_vecs is not None else 0,
                 self.token_vecs is not None, self.fusion_mode, len(vocab))

    @classmethod
    def from_config(cls) -> "BundleRetriever":
        return cls(
            bundle_dir=getattr(config, "BUNDLE_PATH", "mirea_data/bundle"),
            weights=getattr(config, "BUNDLE_WEIGHTS", None),
            rrf_k=getattr(config, "BUNDLE_RRF_K", 60),
            pool_factor=getattr(config, "BUNDLE_POOL_FACTOR", 3),
            correct=getattr(
                config, "BUNDLE_CORRECT",
                os.environ.get("BUNDLE_CORRECT", "1") == "1",
            ),
            q_alpha=getattr(config, "BUNDLE_Q_ALPHA", 1.0),
            s_alpha=getattr(config, "BUNDLE_S_ALPHA", 0.95),
        )

    # ---- HNSW loading ---- #

    def _try_load_hnsw(self, bundle_dir: str) -> None:
        """Load .usearch HNSW indices if present; silently skip otherwise."""
        try:
            from usearch.index import Index as UIndex
        except ImportError:
            log.info("HNSW_ENABLED but usearch not installed — using brute-force")
            return
        chunks_path = os.path.join(bundle_dir, "hnsw_chunks.usearch")
        q_path = os.path.join(bundle_dir, "hnsw_questions.usearch")
        if not os.path.exists(chunks_path):
            log.info("hnsw_chunks.usearch not found — using brute-force")
            return
        try:
            idx = UIndex(ndim=self.chunk_vecs.shape[1], metric="cos", dtype="f16")
            idx.load(chunks_path)
            self._hnsw_chunks = idx
        except Exception as e:
            log.warning("Failed to load HNSW chunks index: %s — brute-force", e)
            return
        if os.path.exists(q_path) and self.q_chunk_ids is not None:
            try:
                idx_q = UIndex(
                    ndim=self.question_vecs.shape[1], metric="cos", dtype="f16")
                idx_q.load(q_path)
                self._hnsw_questions = idx_q
            except Exception as e:
                log.warning("Failed to load HNSW questions index: %s", e)
        log.info("HNSW loaded: chunks=%d, questions=%s",
                 idx.size,
                 self._hnsw_questions.size if self._hnsw_questions else "none")

    # ---- entry lists ---- #

    def prepare(self, query_text: str) -> str:
        """Spell-corrected text for embedding AND lexical scoring.

        Correction is applied only to all-lowercase text — the shape of ASR
        (microphone) output. Typed queries carrying capitals/punctuation are
        left alone: measured, repairing lowercase-shaped OOV *word forms*
        warped clean queries' inflected words and lost hit@3 0.88→0.84.
        """
        if self.corrector is None:
            return query_text
        if query_text != query_text.lower():
            return query_text
        fixed, _fixes = self.corrector.correct_text(query_text)
        return fixed

    def _dense_lists(self, q: np.ndarray, pool: int):
        """(chunk-cos list, per-chunk question-cos array)."""
        if self._hnsw_chunks is not None:
            return self._dense_lists_hnsw(q, pool)
        sims_c = self.chunk_vecs @ q
        kth = min(pool, self.n_chunks - 1)
        idx = np.argpartition(-sims_c, kth)[:pool]
        idx = idx[np.argsort(-sims_c[idx])]
        dc = [(int(i), float(sims_c[i])) for i in idx]
        if self.question_vecs is None:
            return dc, None
        sims_q = self.question_vecs @ q
        agg_q = np.full(self.n_chunks, -1.0, dtype=np.float32)
        np.maximum.at(agg_q, self.q_chunk_ids, sims_q)
        return dc, agg_q

    def _dense_lists_hnsw(self, q: np.ndarray, pool: int):
        """HNSW-graph dense search: O(log n) traversal instead of O(n)."""
        result_c = self._hnsw_chunks.search(q, count=pool)
        dc = [(int(kk), float(1.0 - d)) for kk, d in
              zip(result_c.keys, result_c.distances)]
        if self.question_vecs is None or self._hnsw_questions is None:
            return dc, None
        result_q = self._hnsw_questions.search(q, count=pool)
        q_keys = result_q.keys
        q_sims = (1.0 - result_q.distances).astype(np.float32)
        agg_q = np.full(self.n_chunks, -1.0, dtype=np.float32)
        chunk_ids = self.q_chunk_ids[q_keys]
        np.maximum.at(agg_q, chunk_ids, q_sims)
        return dc, agg_q

    def _sentence_sims(self, q: np.ndarray) -> Optional[np.ndarray]:
        """Per-chunk max sentence cosine (brute force — a few k vectors)."""
        if self.sentence_vecs is None:
            return None
        sims = self.sentence_vecs @ q
        agg = np.full(self.n_chunks, -1.0, dtype=np.float32)
        np.maximum.at(agg, self.s_chunk_ids, sims)
        return agg

    def project_tokens(self, tokens: np.ndarray) -> np.ndarray:
        """Apply the bake-time PCA to raw query token embeddings + L2-normalise."""
        t = tokens.astype(np.float32)
        t = (t - self.maxsim_mean) @ self.maxsim_components.T
        return _normed(t)

    def _maxsim_scores(self, q_proj: np.ndarray, cand_ids: list[int]) -> dict[int, float]:
        """ColBERT MaxSim: mean over query tokens of max cosine vs chunk tokens.

        Vectorised over the whole candidate union: one einsum produces the
        (candidates × query-tokens × chunk-tokens) similarity tensor, padding
        is masked to -inf, then max over chunk tokens and mean over query
        tokens. q_proj is (n_q, D) normalised; chunk tokens are stored
        pre-projected and normalised (float16, padded to T).
        """
        if not cand_ids or q_proj.shape[0] == 0:
            return {}
        ids = np.asarray(cand_ids, dtype=np.int64)
        lens = self.token_lens[ids]                       # (C,)
        toks = self.token_vecs[ids].astype(np.float32)    # (C, T, D)
        sims = np.einsum("qd,ctd->cqt", q_proj, toks, optimize=True)
        t = toks.shape[1]
        mask = np.arange(t)[None, :] < lens[:, None]      # (C, T)
        sims = np.where(mask[:, None, :], sims, -1e4)
        scores = sims.max(axis=2).mean(axis=1)            # (C,)
        return {int(d): float(s) for d, s in zip(ids, scores)}

    # ---- RRF fallback fusion ---- #

    def fuse(
        self,
        dc: list[tuple[int, float]],
        agg_q: Optional[np.ndarray],
        bm25_hits: list[tuple[int, float]],
        top_k: int,
        q: Optional[np.ndarray] = None,
        bm25_anchors: Optional[list[int]] = None,
        agg_s: Optional[np.ndarray] = None,
    ) -> list[tuple[int, float, float]]:
        """Weighted RRF over the dense merge and BM25 (no LTR model present).

        Dense merge = element-wise max of chunk-cos, α·question-cos and
        α·sentence-cos. The BM25 champion (sole hit or >2× runner-up) is
        anchored to the head so a distinctive lexical match surfaces even
        when its dense cosine falls outside the pool. Anchored chunks get an
        honest cosine for the relevance threshold / confidence guard.

        Returns ``[(doc_id, fused_score, bi_score)]`` ordered by fused rank.
        """
        dense_scores: dict[int, float] = {d: s for d, s in dc}
        if agg_q is not None:
            scaled = np.where(agg_q >= 0, self.q_alpha * agg_q, -1.0)
            k = min(20, self.n_chunks - 1)
            for i in np.argpartition(-scaled, k)[:k]:
                i = int(i)
                if float(scaled[i]) > dense_scores.get(i, -1.0):
                    dense_scores[i] = float(scaled[i])
        if agg_s is not None:
            scaled_s = np.where(agg_s >= 0, self.s_alpha * agg_s, -1.0)
            k = min(20, self.n_chunks - 1)
            for i in np.argpartition(-scaled_s, k)[:k]:
                i = int(i)
                if float(scaled_s[i]) > dense_scores.get(i, -1.0):
                    dense_scores[i] = float(scaled_s[i])
        dense_rank = sorted(dense_scores.items(), key=lambda kv: -kv[1])[:max(top_k * 4, 20)]
        anchors = list(bm25_anchors or [])
        anchor_set = set(anchors)
        for d in anchor_set:
            if dense_scores.get(d, -1.0) < 0:
                cand = []
                if q is not None:
                    cand.append(float(self.chunk_vecs[d] @ q))
                if agg_q is not None and float(agg_q[d]) >= 0:
                    cand.append(self.q_alpha * float(agg_q[d]))
                if agg_s is not None and float(agg_s[d]) >= 0:
                    cand.append(self.s_alpha * float(agg_s[d]))
                dense_scores[d] = max(cand) if cand else 0.0
        merged_dense = anchors + [d for d, _ in dense_rank if d not in anchor_set]

        lists = [merged_dense, [d for d, _ in bm25_hits]]
        w = self.weights
        weights = [w.get("dense", 0.95), w.get("bm25", 0.05)]
        total = sum(weights) or 1.0
        weights = [x / total for x in weights]
        raw: dict[int, float] = {}
        for ranking, wt in zip(lists, weights):
            for rank, doc_id in enumerate(ranking, start=1):
                raw[doc_id] = raw.get(doc_id, 0.0) + wt / (self.rrf_k + rank)
        fused = sorted(raw.items(), key=lambda kv: -kv[1])[:top_k]
        return [(d, s, dense_scores.get(d, -1.0)) for d, s in fused]

    # ---- search ---- #

    def _collect_signals(
        self,
        q: np.ndarray,
        query_text: str,
        pool: int,
        query_tokens: Optional[np.ndarray] = None,
    ) -> dict:
        """Compute every retrieval arm and the candidate union.

        Shared by search() (runtime) and scripts/train_ltr.py (labels are
        joined onto these exact features, so training and serving never drift).
        """
        dc, agg_q = self._dense_lists(q, pool)
        agg_s = self._sentence_sims(q)

        prepared = self.prepare(query_text)
        bm25_tokens = tokenize_ru(query_text) + tokenize_ru(prepared)
        bm25_hits = self.bm25.search(bm25_tokens, top_k=pool)

        bm25_anchors: list[int] = []
        if bm25_hits and (len(bm25_hits) == 1 or bm25_hits[0][1] > 2.0 * bm25_hits[1][1]):
            bm25_anchors = [bm25_hits[0][0]]
        champ = set(bm25_anchors)

        d_rank = {int(d): i + 1 for i, (d, _) in enumerate(dc)}
        b_rank = {int(d): i + 1 for i, (d, _) in enumerate(bm25_hits)}
        b_score = {int(d): float(s) for d, s in bm25_hits}

        q_rank: dict[int, int] = {}
        q_cos: dict[int, float] = {}
        if agg_q is not None:
            scaled = np.where(agg_q >= 0, self.q_alpha * agg_q, -1.0)
            for i in np.argsort(-scaled)[:20]:
                i = int(i)
                if float(scaled[i]) >= 0:
                    q_rank[i] = len(q_rank) + 1
                    q_cos[i] = float(scaled[i])

        s_rank: dict[int, int] = {}
        s_cos: dict[int, float] = {}
        if agg_s is not None:
            scaled_s = np.where(agg_s >= 0, self.s_alpha * agg_s, -1.0)
            for i in np.argsort(-scaled_s)[:20]:
                i = int(i)
                if float(scaled_s[i]) >= 0:
                    s_rank[i] = len(s_rank) + 1
                    s_cos[i] = float(scaled_s[i])

        cand_ids: list[int] = []
        seen: set[int] = set()
        for lst in ([d for d, _ in dc], list(q_rank), list(s_rank),
                    [d for d, _ in bm25_hits], bm25_anchors):
            for d in lst:
                if d not in seen:
                    seen.add(d)
                    cand_ids.append(d)

        maxsim: dict[int, float] = {}
        if self.token_vecs is not None and query_tokens is not None:
            q_proj = self.project_tokens(np.asarray(query_tokens)[:32])
            maxsim = self._maxsim_scores(q_proj, cand_ids)
        m_rank = {d: i + 1 for i, (d, _) in enumerate(
            sorted(maxsim.items(), key=lambda kv: -kv[1]))}

        bi: dict[int, float] = {}
        for d in cand_ids:
            cos = float(self.chunk_vecs[d] @ q)
            if d in q_cos:
                cos = max(cos, q_cos[d])
            if d in s_cos:
                cos = max(cos, s_cos[d])
            bi[d] = cos

        return {
            "dc": dc, "agg_q": agg_q, "agg_s": agg_s,
            "bm25_hits": bm25_hits, "bm25_anchors": bm25_anchors, "champ": champ,
            "d_rank": d_rank, "q_rank": q_rank, "s_rank": s_rank,
            "b_rank": b_rank, "b_score": b_score, "q_cos": q_cos, "s_cos": s_cos,
            "m_rank": m_rank, "maxsim": maxsim, "cand_ids": cand_ids, "bi": bi,
        }

    def _feature_rows(self, cand_ids: list[int], sig: dict, q: np.ndarray) -> np.ndarray:
        """LTR feature matrix for the candidate union (FEATURES order)."""
        dc, q_rank, s_rank = sig["dc"], sig["q_rank"], sig["s_rank"]
        bm25_hits = sig["bm25_hits"]
        n_d, n_q, n_s, n_b = len(dc), len(q_rank), len(s_rank), len(bm25_hits)
        d_rank, b_rank, b_score = sig["d_rank"], sig["b_rank"], sig["b_score"]
        q_cos, s_cos, maxsim, champ = sig["q_cos"], sig["s_cos"], sig["maxsim"], sig["champ"]
        rows = []
        for d in cand_ids:
            p = self.payloads[d]
            rows.append(feature_row(
                dense_cos=float(self.chunk_vecs[d] @ q),
                q_cos=q_cos.get(d),
                sent_cos=s_cos.get(d),
                bm25_score=b_score.get(d, 0.0),
                dense_rank_pct=(d_rank[d] / n_d) if d in d_rank else None,
                q_rank_pct=(q_rank[d] / n_q) if d in q_rank else None,
                sent_rank_pct=(s_rank[d] / n_s) if d in s_rank else None,
                bm25_rank_pct=(b_rank[d] / n_b) if d in b_rank else None,
                champion=d in champ,
                maxsim=maxsim.get(d),
                is_qa=(p.get("kind") == "qa"),
                doc_len=len(p["text"]),
            ))
        return np.asarray(rows, dtype=np.float64)

    def search(
        self,
        query_vec: np.ndarray,
        query_text: str,
        top_k: int = 3,
        query_tokens: Optional[np.ndarray] = None,
    ) -> list[dict]:
        q = query_vec.astype(np.float32)
        q = q / max(float(np.linalg.norm(q)), 1e-10)

        pool = max(top_k * self.pool_factor, 12)
        sig = self._collect_signals(q, query_text, pool, query_tokens)
        cand_ids = sig["cand_ids"]
        bi = sig["bi"]

        if self.ltr is not None:
            X = self._feature_rows(cand_ids, sig, q)
            scores = self.ltr.predict(X)
            order = np.argsort(-scores)
            fused = [(cand_ids[i], float(scores[i]), bi[cand_ids[i]])
                     for i in order[:top_k]]
        else:
            fused = self.fuse(sig["dc"], sig["agg_q"], sig["bm25_hits"], top_k,
                              q=q, bm25_anchors=sig["bm25_anchors"], agg_s=sig["agg_s"])

        d_rank, q_rank, s_rank = sig["d_rank"], sig["q_rank"], sig["s_rank"]
        b_rank, m_rank, champ = sig["b_rank"], sig["m_rank"], sig["champ"]
        results = []
        for doc_id, fused_score, bi_score in fused:
            p = self.payloads[doc_id]
            results.append({
                "id": doc_id,
                "score": bi_score,
                "fused_score": fused_score,
                "arms": {
                    "D": d_rank.get(doc_id),
                    "Q": q_rank.get(doc_id),
                    "S": s_rank.get(doc_id),
                    "B": b_rank.get(doc_id),
                    "M": m_rank.get(doc_id),
                    "C": doc_id in champ,
                },
                "payload": {
                    "text": p["text"],
                    "source_title": p["source_title"] or "",
                    "source_url": p["source_url"] or "",
                    "section": p["section"] or "",
                },
            })
        return results


__all__ = ["BundleRetriever", "VocabCorrector"]
