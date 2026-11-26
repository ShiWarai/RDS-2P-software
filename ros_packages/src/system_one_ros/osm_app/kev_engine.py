"""Kev-0.8B w8a8 on RKLLM runtime 1.3.1. The pointer head stays on CPU."""
import ctypes
import json
import math
import os
import time

import numpy as np
from tokenizers import Tokenizer

from .kev_encode import encode_question

RKLLM_INPUT_TOKEN = 1
RKLLM_INFER_GET_LAST_HIDDEN_LAYER = 1
RKLLM_RUN_ERROR = 3


class _Extend(ctypes.Structure):
    _fields_ = [
        ("base_domain_id", ctypes.c_int32),
        ("embed_flash", ctypes.c_int8),
        ("enabled_cpus_num", ctypes.c_int8),
        ("enabled_cpus_mask", ctypes.c_uint32),
        ("n_batch", ctypes.c_uint8),
        ("use_cross_attn", ctypes.c_int8),
        ("reserved", ctypes.c_uint8 * 104),
    ]


class _Param(ctypes.Structure):
    _fields_ = [
        ("model_path", ctypes.c_char_p),
        ("max_context_len", ctypes.c_int32),
        ("max_new_tokens", ctypes.c_int32),
        ("top_k", ctypes.c_float),
        ("n_keep", ctypes.c_int32),
        ("top_p", ctypes.c_float),
        ("temperature", ctypes.c_float),
        ("repeat_penalty", ctypes.c_float),
        ("frequency_penalty", ctypes.c_float),
        ("presence_penalty", ctypes.c_float),
        ("mirostat", ctypes.c_int32),
        ("mirostat_tau", ctypes.c_float),
        ("mirostat_eta", ctypes.c_float),
        ("skip_special_token", ctypes.c_bool),
        ("ignore_eos_token", ctypes.c_bool),
        ("is_async", ctypes.c_bool),
        ("extend_param", _Extend),
    ]


class _EmbedIn(ctypes.Structure):
    _fields_ = [("embed", ctypes.POINTER(ctypes.c_float)), ("n_tokens", ctypes.c_size_t)]


class _TokenIn(ctypes.Structure):
    _fields_ = [("input_ids", ctypes.POINTER(ctypes.c_int32)), ("n_tokens", ctypes.c_size_t)]


class _InputUnion(ctypes.Union):
    _fields_ = [
        ("prompt_input", ctypes.c_char_p),
        ("embed_input", _EmbedIn),
        ("token_input", _TokenIn),
    ]


class _Input(ctypes.Structure):
    _fields_ = [
        ("role", ctypes.c_char_p),
        ("enable_thinking", ctypes.c_bool),
        ("input_type", ctypes.c_int),
        ("input_data", _InputUnion),
    ]


class _Infer(ctypes.Structure):
    _fields_ = [
        ("mode", ctypes.c_int),
        ("lora_params", ctypes.c_void_p),
        ("prompt_cache_params", ctypes.c_void_p),
        ("sampling_params", ctypes.c_void_p),
        ("keep_history", ctypes.c_int),
        ("max_new_tokens", ctypes.c_int32),
    ]


class _Hidden(ctypes.Structure):
    _fields_ = [
        ("hidden_states", ctypes.POINTER(ctypes.c_float)),
        ("embd_size", ctypes.c_int),
        ("num_tokens", ctypes.c_int),
    ]


class _Logits(ctypes.Structure):
    _fields_ = [
        ("logits", ctypes.POINTER(ctypes.c_float)),
        ("vocab_size", ctypes.c_int),
        ("num_tokens", ctypes.c_int),
    ]


class _Perf(ctypes.Structure):
    _fields_ = [
        ("prefill_time_ms", ctypes.c_float),
        ("prefill_tokens", ctypes.c_int),
        ("generate_time_ms", ctypes.c_float),
        ("generate_tokens", ctypes.c_int),
        ("memory_usage_mb", ctypes.c_float),
    ]


class _Result(ctypes.Structure):
    _fields_ = [
        ("text", ctypes.c_char_p),
        ("token_id", ctypes.c_int),
        ("last_hidden_layer", _Hidden),
        ("logits", _Logits),
        ("perf", _Perf),
    ]


class _Callback(ctypes.Structure):
    _fields_ = [
        ("result_callback", ctypes.CFUNCTYPE(ctypes.c_int, ctypes.POINTER(_Result), ctypes.c_void_p, ctypes.c_int)),
        ("result_userdata", ctypes.c_void_p),
        ("tokenizer_callback", ctypes.c_void_p),
        ("tokenizer_userdata", ctypes.c_void_p),
        ("embed_callback", ctypes.c_void_p),
        ("embed_userdata", ctypes.c_void_p),
    ]


class KevEngine:
    name = "kev-0.8b"
    description = "Kev-0.8B merged into Qwen3.5-0.8B-Base, RKLLM w8a8, context 320"
    release_date = "2026-09-30"

    def __init__(self, root, lib_path):
        with open(os.path.join(root, "pointer.json"), encoding="utf-8") as handle:
            self._temperature_value = float(json.load(handle)["temperature"])
        self._wq = np.load(os.path.join(root, "q_weight.npy"))
        self._bq = np.load(os.path.join(root, "q_bias.npy"))
        self._wk = np.load(os.path.join(root, "k_weight.npy"))
        self._bk = np.load(os.path.join(root, "k_bias.npy"))
        self._scale = 1.0 / math.sqrt(self._wq.shape[0])
        self._tok = Tokenizer.from_file(os.path.join(root, "tokenizer.json"))
        self._captured = {}
        self._lib = ctypes.CDLL(lib_path)
        self._bind()
        callback_type = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.POINTER(_Result), ctypes.c_void_p, ctypes.c_int)

        @callback_type
        def on_result(result, userdata, state):
            del userdata
            if state == RKLLM_RUN_ERROR:
                return 0
            layer = result.contents.last_hidden_layer
            if layer.hidden_states and layer.num_tokens > 0 and layer.embd_size > 0:
                count = layer.num_tokens * layer.embd_size
                self._captured["h"] = np.ctypeslib.as_array(layer.hidden_states, shape=(count,)).copy()
                self._captured["ntok"] = layer.num_tokens
                self._captured["embd"] = layer.embd_size
            return 0

        self._on_result = on_result
        self._lib.rkllm_createDefaultParam.restype = _Param
        param = self._lib.rkllm_createDefaultParam()
        param.model_path = os.path.join(root, "kev-0.8b-w8a8-opt0-ctx320.rkllm").encode()
        param.max_context_len = 320
        param.max_new_tokens = 0
        param.n_keep = 0
        param.is_async = False
        param.skip_special_token = True
        param.ignore_eos_token = False
        param.extend_param.base_domain_id = 1
        param.extend_param.embed_flash = 0
        param.extend_param.n_batch = 1
        param.extend_param.use_cross_attn = 0
        param.extend_param.enabled_cpus_num = 4
        param.extend_param.enabled_cpus_mask = (1 << 4) | (1 << 5) | (1 << 6) | (1 << 7)
        self._handle = ctypes.c_void_p()
        cb = _Callback()
        cb.result_callback = on_result
        self._cb = cb
        ret = self._lib.rkllm_init(ctypes.byref(self._handle), ctypes.byref(param), ctypes.byref(cb))
        if ret != 0:
            raise SystemExit("rkllm_init %s" % ret)
        self._lib.rkllm_set_chat_template(self._handle, b"", b"", b"")

    def _bind(self):
        lib = self._lib
        lib.rkllm_init.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(_Param), ctypes.POINTER(_Callback)]
        lib.rkllm_init.restype = ctypes.c_int
        lib.rkllm_run.argtypes = [ctypes.c_void_p, ctypes.POINTER(_Input), ctypes.POINTER(_Infer), ctypes.c_void_p]
        lib.rkllm_run.restype = ctypes.c_int
        lib.rkllm_set_chat_template.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p]
        lib.rkllm_set_chat_template.restype = ctypes.c_int

    def temperature(self, kind):
        del kind
        return self._temperature_value

    def forward(self, state, item):
        ids, decide, opt_idx = encode_question(self._tok, state, item)
        hidden, shift, elapsed = self._hidden(ids)
        logits = self._pointer(hidden, decide + shift, [index + shift for index in opt_idx])
        return logits.tolist(), len(ids), elapsed

    def _hidden(self, ids):
        self._captured = {}
        tokens = (ctypes.c_int32 * len(ids))(*ids)
        rk_input = _Input()
        rk_input.role = b""
        rk_input.enable_thinking = False
        rk_input.input_type = RKLLM_INPUT_TOKEN
        rk_input.input_data.token_input.input_ids = ctypes.cast(tokens, ctypes.POINTER(ctypes.c_int32))
        rk_input.input_data.token_input.n_tokens = len(ids)
        infer = _Infer()
        infer.mode = RKLLM_INFER_GET_LAST_HIDDEN_LAYER
        infer.keep_history = 0
        infer.max_new_tokens = 0
        started = time.perf_counter()
        ret = self._lib.rkllm_run(self._handle, ctypes.byref(rk_input), ctypes.byref(infer), None)
        elapsed = (time.perf_counter() - started) * 1000
        if ret != 0 or "h" not in self._captured:
            raise RuntimeError("rkllm_run %s" % ret)
        hidden = self._captured["h"].reshape(self._captured["ntok"], self._captured["embd"])
        if self._captured["ntok"] < len(ids):
            raise RuntimeError("hidden tokens %s < %s" % (self._captured["ntok"], len(ids)))
        return hidden, self._captured["ntok"] - len(ids), elapsed

    def _pointer(self, hidden, decide, opts):
        query = hidden[decide] @ self._wq.T + self._bq
        key = hidden[opts] @ self._wk.T + self._bk
        return key @ query * self._scale
