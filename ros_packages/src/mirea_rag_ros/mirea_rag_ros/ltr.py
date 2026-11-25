"""Learning-to-rank fusion over the bundle's retrieval arms (LightGBM LambdaMART).

Replaces the hand-tuned weighted RRF (dense/question/BM25 weights, champion
promotion, entity anchors) with a tiny gradient-boosted ranker trained on the
golden+ASR eval queries. Every signal the old fusion used by hand becomes a
feature; the model learns their combination from labelled queries instead of
manual weights.

Runtime cost: one Booster.predict over the candidate pool (~40-80 rows × 12
features) — sub-millisecond on CPU, model file a few hundred KB. No neural
model is added; LightGBM is the only new dependency (aarch64 wheels exist for
the Orange Pi).

Feature schema is FIXED (FEATURES below) and shared by scripts/train_ltr.py
and BundleRetriever. Missing signals are NaN — LightGBM handles them natively,
so a bundle baked without sentence nodes or MaxSim tokens still ranks (those
features simply never split). Rank features are normalised by their arm's
hit-list length so they stay comparable across pool sizes.

The bi-encoder cosine used by the confidence guard is NOT produced here: the
retriever keeps max(chunk-cos, α·question-cos, α·sentence-cos) as the honest
``score`` regardless of the LTR ordering.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Optional

import numpy as np

log = logging.getLogger(__name__)

FEATURES = [
    "dense_cos",       # cosine(query, chunk vector)
    "q_cos",           # q_alpha · max cosine(query, question nodes of chunk)
    "sent_cos",        # s_alpha · max cosine(query, sentence nodes of chunk)
    "bm25_score",      # raw BM25 score (0 when no lexical hit)
    "dense_rank_pct",  # rank / len(dense hit list), NaN when absent
    "q_rank_pct",      # rank / len(question hit list), NaN when absent
    "sent_rank_pct",   # rank / len(sentence hit list), NaN when absent
    "bm25_rank_pct",   # rank / len(bm25 hit list), NaN when absent
    "champion",        # 1 iff dominant BM25 hit (sole hit or >2× runner-up)
    "maxsim",          # ColBERT-style mean-max token similarity, NaN if absent
    "is_qa",           # 1 iff chunk kind == "qa"
    "doc_len",         # chunk text length / 1000
]

MODEL_FILE = "ltr_model.txt"
SCHEMA_FILE = "ltr_features.json"


def feature_row(
    dense_cos: float,
    q_cos: Optional[float],
    sent_cos: Optional[float],
    bm25_score: float,
    dense_rank_pct: Optional[float],
    q_rank_pct: Optional[float],
    sent_rank_pct: Optional[float],
    bm25_rank_pct: Optional[float],
    champion: bool,
    maxsim: Optional[float],
    is_qa: bool,
    doc_len: int,
) -> list[float]:
    """One candidate's feature vector in FEATURES order (None → NaN)."""
    def f(v: Optional[float]) -> float:
        return float("nan") if v is None else float(v)
    return [
        f(dense_cos), f(q_cos), f(sent_cos), f(bm25_score),
        f(dense_rank_pct), f(q_rank_pct), f(sent_rank_pct), f(bm25_rank_pct),
        1.0 if champion else 0.0, f(maxsim),
        1.0 if is_qa else 0.0, doc_len / 1000.0,
    ]


class LTRRanker:
    """Thin wrapper over a LightGBM Booster saved as text (portable, tiny)."""

    def __init__(self, booster, features: list[str]) -> None:
        self.booster = booster
        self.features = features

    @classmethod
    def load(cls, bundle_dir: str) -> Optional["LTRRanker"]:
        """Load the ranker if present; None on any failure (RRF fallback)."""
        model_path = os.path.join(bundle_dir, MODEL_FILE)
        schema_path = os.path.join(bundle_dir, SCHEMA_FILE)
        if not os.path.exists(model_path):
            log.info("LTR: %s not found in bundle — weighted RRF fallback", MODEL_FILE)
            return None
        try:
            import lightgbm as lgb
        except ImportError:
            log.warning("LTR: lightgbm not installed — weighted RRF fallback")
            return None
        try:
            booster = lgb.Booster(model_file=model_path)
            features = FEATURES
            if os.path.exists(schema_path):
                with open(schema_path, encoding="utf-8") as fh:
                    saved = json.load(fh).get("features")
                if saved and saved != FEATURES:
                    log.warning("LTR schema mismatch (bundle=%s code=%s) — disabled",
                                saved, FEATURES)
                    return None
            log.info("LTR ranker loaded: %s (%d trees, %d features)",
                     MODEL_FILE, booster.num_trees(), len(features))
            return cls(booster, features)
        except Exception as e:
            log.warning("LTR load failed (%s) — RRF fallback", e)
            return None

    def predict(self, X: np.ndarray) -> np.ndarray:
        return self.booster.predict(X, num_iteration=self.booster.best_iteration)


__all__ = ["FEATURES", "MODEL_FILE", "SCHEMA_FILE", "LTRRanker", "feature_row"]
