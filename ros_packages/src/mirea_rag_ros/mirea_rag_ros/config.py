"""Константы локального retrieval, совпадающие с серверным config.py."""
from __future__ import annotations

import os

EMBEDDING_MODEL = os.environ.get(
    "MIREA_RAG_EMBEDDING_MODEL", "Qwen/Qwen3-Embedding-0.6B")
EMBED_QUERY_PREFIX = (
    "Instruct: Given a Russian question about RTU MIREA "
    "university services, retrieve the passage that answers it. Query: ")
EMBED_PASSAGE_PREFIX = ""

BUNDLE_BM25_FILE = "bm25_raw.pkl"
BUNDLE_WEIGHTS = {"dense": 0.95, "bm25": 0.05}
BUNDLE_RRF_K = 60
BUNDLE_POOL_FACTOR = 3
BUNDLE_Q_ALPHA = 0.85
BUNDLE_S_ALPHA = 0.95
BUNDLE_CORRECT = True
BUNDLE_CORRECT_MAX_EDIT = 1

BUNDLE_LTR_ENABLED = os.environ.get(
    "BUNDLE_LTR_ENABLED", "1").strip().lower() in ("1", "true", "yes", "on")
BUNDLE_MAXSIM_ENABLED = os.environ.get(
    "BUNDLE_MAXSIM_ENABLED", "1").strip().lower() in ("1", "true", "yes", "on")
HNSW_ENABLED = os.environ.get(
    "HNSW_ENABLED", "1").strip().lower() in ("1", "true", "yes", "on")
RERANK_ENABLED = False

NORMALIZE_WHITESPACE = True
NORMALIZE_PUNCTUATION = True
NORMALIZE_KEYBOARD_LAYOUT = True
NORMALIZE_ASR_ALIASES = True
NORMALIZE_CASE = False
