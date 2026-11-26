"""Kev pointer head on NumPy: the decision token attends to option tokens.

Shared by the RKLLM and the torch CPU engines; only the hidden states differ.
"""
import math
import os

import numpy as np


class PointerHead:
    def __init__(self, root):
        self._wq = np.load(os.path.join(root, "q_weight.npy"))
        self._bq = np.load(os.path.join(root, "q_bias.npy"))
        self._wk = np.load(os.path.join(root, "k_weight.npy"))
        self._bk = np.load(os.path.join(root, "k_bias.npy"))
        self._scale = 1.0 / math.sqrt(self._wq.shape[0])

    def logits(self, hidden, decide, opts):
        query = hidden[decide] @ self._wq.T + self._bq
        key = hidden[opts] @ self._wk.T + self._bk
        return key @ query * self._scale