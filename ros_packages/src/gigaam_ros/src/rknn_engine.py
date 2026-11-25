#!/usr/bin/env python3
"""RKNN runtime helpers for gigaam_ros (RK3588 NPU, librknnrt 2.3.2).

Порт скриптов фронтенда/раннера модели ShiWarai/gigaam-ctc-rknn
(scripts/frontend.py, scripts/test_npu.py, scripts/decode_ctc.py) в переиспользуемый
модуль. Загружает ``librknnrt.so`` через ctypes (dlopen), инициализирует контекст и
прогоняет тензоры через NPU — ровно как эталонный ``test_npu.py``.

Модуль ставится рядом с нодами в ``lib/gigaam_ros``; ноды добавляют эту директорию
в ``sys.path`` и импортируют его (пакет ``gigaam_ros`` занят сгенерированными
интерфейсами, поэтому свой python-пакет того же имени introducing нельзя).
"""

from __future__ import annotations

import ctypes
import os

import numpy as np

# --- RKNN constants (RKNN-Toolkit2 2.3.2) ------------------------------------
RKNN_QUERY_IN_OUT_NUM = 0
RKNN_QUERY_INPUT_ATTR = 1
RKNN_QUERY_OUTPUT_ATTR = 2
RKNN_NPU_CORE_ALL = 0xFFFF
RKNN_MAX_DIMS = 16
RKNN_MAX_NAME_LEN = 256

RKNN_TENSOR_FLOAT16 = 1
RKNN_TENSOR_INT8 = 2
RKNN_TENSOR_FLOAT32 = 3


class _InputOutputNum(ctypes.Structure):
    _fields_ = [("n_input", ctypes.c_uint32), ("n_output", ctypes.c_uint32)]


class _TensorAttr(ctypes.Structure):
    _fields_ = [
        ("index", ctypes.c_uint32),
        ("n_dims", ctypes.c_uint32),
        ("dims", ctypes.c_uint32 * RKNN_MAX_DIMS),
        ("name", ctypes.c_char * RKNN_MAX_NAME_LEN),
        ("n_elems", ctypes.c_uint32),
        ("size", ctypes.c_uint32),
        ("fmt", ctypes.c_int),
        ("type", ctypes.c_int),
        ("qnt_type", ctypes.c_int),
        ("fl", ctypes.c_int8),
        ("zp", ctypes.c_int32),
        ("scale", ctypes.c_float),
        ("w_stride", ctypes.c_uint32),
        ("size_with_stride", ctypes.c_uint32),
        ("pass_through", ctypes.c_uint8),
        ("h_stride", ctypes.c_uint32),
    ]


class _RknnInput(ctypes.Structure):
    _fields_ = [
        ("index", ctypes.c_uint32),
        ("buf", ctypes.c_void_p),
        ("size", ctypes.c_uint32),
        ("pass_through", ctypes.c_uint8),
        ("type", ctypes.c_int),
        ("fmt", ctypes.c_int),
    ]


class _RknnOutput(ctypes.Structure):
    _fields_ = [
        ("want_float", ctypes.c_uint8),
        ("is_prealloc", ctypes.c_uint8),
        ("index", ctypes.c_uint32),
        ("buf", ctypes.c_void_p),
        ("size", ctypes.c_uint32),
    ]


def _attr_dims(attr: _TensorAttr) -> list:
    return list(attr.dims[: attr.n_dims])


def _attr_name(attr: _TensorAttr) -> str:
    try:
        return attr.name.decode().strip("\x00")
    except Exception:  # noqa: BLE001
        return ""


class Engine:
    """Контекст одного RKNN-графа поверх ``librknnrt`` (dlopen, RK3588).

    ``model`` — путь к ``.rknn`` (librknnrt читает файл, если размер буфера 0,
    ровно как в эталонном test_npu.py). ``lib_path`` — путь к ``librknnrt.so``.
    """

    def __init__(self, model: str, lib_path: str = "librknnrt.so"):
        if not os.path.isfile(model):
            raise FileNotFoundError(f"RKNN-модель не найдена: {model}")
        self.model_path = model
        self.lib_path = lib_path
        lib = ctypes.CDLL(lib_path)
        self._lib = lib
        lib.rknn_init.argtypes = [
            ctypes.POINTER(ctypes.c_uint64), ctypes.c_char_p,
            ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
        lib.rknn_init.restype = ctypes.c_int
        lib.rknn_query.argtypes = [
            ctypes.c_uint64, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
        lib.rknn_query.restype = ctypes.c_int
        lib.rknn_inputs_set.argtypes = [
            ctypes.c_uint64, ctypes.c_uint32, ctypes.POINTER(_RknnInput)]
        lib.rknn_inputs_set.restype = ctypes.c_int
        lib.rknn_run.argtypes = [ctypes.c_uint64, ctypes.c_void_p]
        lib.rknn_run.restype = ctypes.c_int
        lib.rknn_outputs_get.argtypes = [
            ctypes.c_uint64, ctypes.c_uint32, ctypes.POINTER(_RknnOutput), ctypes.c_void_p]
        lib.rknn_outputs_get.restype = ctypes.c_int
        lib.rknn_outputs_release.argtypes = [
            ctypes.c_uint64, ctypes.c_uint32, ctypes.POINTER(_RknnOutput)]
        lib.rknn_outputs_release.restype = ctypes.c_int
        lib.rknn_set_core_mask.argtypes = [ctypes.c_uint64, ctypes.c_int]
        lib.rknn_set_core_mask.restype = ctypes.c_int
        lib.rknn_destroy.argtypes = [ctypes.c_uint64]
        lib.rknn_destroy.restype = ctypes.c_int

        self._ctx = ctypes.c_uint64(0)
        ret = lib.rknn_init(ctypes.byref(self._ctx), model.encode(), 0, 0, None)
        if ret != 0:
            raise RuntimeError(f"rknn_init не удался (код {ret}): {model}")
        try:
            lib.rknn_set_core_mask(self._ctx.value, RKNN_NPU_CORE_ALL)
        except Exception:  # noqa: BLE001
            pass  # не критично: старый раннер может не иметь set_core_mask

        io = _InputOutputNum()
        lib.rknn_query(self._ctx.value, RKNN_QUERY_IN_OUT_NUM,
                       ctypes.byref(io), ctypes.sizeof(io))
        self.n_input = int(io.n_input)
        self.n_output = int(io.n_output)

        self._in_attrs = []
        for index in range(io.n_input):
            attr = _TensorAttr()
            attr.index = index
            lib.rknn_query(self._ctx.value, RKNN_QUERY_INPUT_ATTR,
                           ctypes.byref(attr), ctypes.sizeof(attr))
            self._in_attrs.append(attr)

        self._out_attrs = []
        for index in range(io.n_output):
            attr = _TensorAttr()
            attr.index = index
            lib.rknn_query(self._ctx.value, RKNN_QUERY_OUTPUT_ATTR,
                           ctypes.byref(attr), ctypes.sizeof(attr))
            self._out_attrs.append(attr)

    def input_names(self):
        return [(_attr_name(a), _attr_dims(a), int(a.type)) for a in self._in_attrs]

    def output_names(self):
        return [(_attr_name(a), _attr_dims(a), int(a.type)) for a in self._out_attrs]

    def _encode_input(self, attr: _TensorAttr, arr: np.ndarray) -> np.ndarray:
        """Привести массив к типу, который объявляет вход модели."""
        if attr.type == RKNN_TENSOR_INT8:
            q = np.clip(np.round(arr.astype(np.float32) / float(attr.scale))
                        + int(attr.zp), -128, 127)
            return np.ascontiguousarray(q, dtype=np.int8)
        if attr.type == RKNN_TENSOR_FLOAT16:
            return np.ascontiguousarray(arr, dtype=np.float16)
        return np.ascontiguousarray(arr, dtype=np.float32)

    def run(self, feats: np.ndarray):
        """Прогнать один вход (graph с одним входом) и вернуть выход float + мс."""
        if self.n_input != 1:
            raise RuntimeError(
                f"run() ждёт 1 вход, у графа {self.n_input}; используйте run_multi()")
        out, ms = self.run_multi([feats])
        return out[0], ms

    def run_multi(self, inputs):
        """Прогнать граф с N входами; вернуть список выходов (float) и время мс."""
        if len(inputs) != self.n_input:
            raise RuntimeError(f"ожидалось {self.n_input} входов, передано {len(inputs)}")
        bufs = [self._encode_input(attr, a) for attr, a in zip(self._in_attrs, inputs)]
        in_arr = (_RknnInput * self.n_input)()
        holds = []
        for i, (attr, buf) in enumerate(zip(self._in_attrs, bufs)):
            holds.append(buf)
            in_arr[i].index = i
            in_arr[i].buf = buf.ctypes.data_as(ctypes.c_void_p)
            in_arr[i].size = buf.nbytes
            in_arr[i].pass_through = 1
            in_arr[i].type = attr.type
            in_arr[i].fmt = attr.fmt
        ret = self._lib.rknn_inputs_set(self._ctx.value, self.n_input, in_arr)
        if ret != 0:
            raise RuntimeError(f"rknn_inputs_set не удался (код {ret})")

        started = __import__("time").perf_counter()
        ret = self._lib.rknn_run(self._ctx.value, None)
        if ret != 0:
            raise RuntimeError(f"rknn_run не удался (код {ret})")

        outs = (_RknnOutput * self.n_output)()
        for i in range(self.n_output):
            outs[i].want_float = 1
            outs[i].index = i
        ret = self._lib.rknn_outputs_get(self._ctx.value, self.n_output, outs, None)
        if ret != 0:
            raise RuntimeError(f"rknn_outputs_get не удался (код {ret})")
        ms = (__import__("time").perf_counter() - started) * 1000.0

        results = []
        for i, attr in enumerate(self._out_attrs):
            count = outs[i].size // 4
            arr = np.ctypeslib.as_array(
                ctypes.cast(outs[i].buf, ctypes.POINTER(ctypes.c_float)),
                shape=(count,)).copy()
            dims = _attr_dims(attr)
            results.append(arr.reshape(dims) if dims else arr)
        self._lib.rknn_outputs_release(self._ctx.value, self.n_output, outs)
        return results, ms

    def close(self):
        try:
            self._lib.rknn_destroy(self._ctx.value)
        except Exception:  # noqa: BLE001
            pass


# --- CTC decode --------------------------------------------------------------

WORD_SEP_ID = 0


def collapse(am, blank: int = 70):
    """argmax → схлопнуть повторы → убрать CTC-blank (id 70)."""
    ids = [a for i, a in enumerate(am) if i == 0 or a != am[i - 1]]
    return [a for a in ids if a != blank]


def load_vocab(path: str) -> dict:
    """multilingual_vocab.txt (``token id``) → {id: token}. id 0 — разделитель слов,
    id 70 — CTC blank."""
    ch = {}
    with open(path) as f:
        for ln in f:
            parts = ln.rstrip("\n").split(" ", 1)
            if len(parts) == 2:
                ch[int(parts[1])] = parts[0]
    return ch


def decode_ids(ids, vocab: dict) -> str:
    return "".join(vocab.get(i, "?") for i in ids).replace("\u2581", " ").strip()


_RU_LETTERS = set("абвгдежзийклмнопрстуфхцчшщъыьэюяё")
_TURKIC_EXTRA = set("іғқңүұһәө")


def allowed_ids_for_lang(vocab: dict, lang: str):
    """Разрешённые id токенов для ``lang`` (ru / en / ru+en / all); None — без фильтра."""
    lang = (lang or "all").strip().lower()
    if lang in ("", "all", "multi", "multilingual"):
        return None
    langs = {x.strip() for x in lang.replace("+", ",").split(",") if x.strip()}
    want_ru = bool(langs & {"ru", "rus", "russian"})
    want_en = bool(langs & {"en", "eng", "english"})
    if not want_ru and not want_en:
        return None
    allowed = set()
    for tid, tok in vocab.items():
        low = tok.lower()
        if tok in ("<blk>", "\u2581", "'"):
            allowed.add(tid)
            continue
        if low in _TURKIC_EXTRA:
            continue
        if low in _RU_LETTERS:
            if want_ru:
                allowed.add(tid)
            continue
        if low.isascii() and low.isalpha():
            if want_en:
                allowed.add(tid)
            continue
        allowed.add(tid)
    return allowed


# --- GigaAM log-mel frontend (ровно как scripts/frontend.py) -----------------

SR = 16000
N_MELS = 64
WIN = 320
HOP = 160
N_FFT = 320
CENTER = False
FRAMES = 500  # статичное окно энкодера: 500 фреймов ≈ 5.02 с @16 кГц
WINDOW_SAMPLES = (FRAMES - 1) * HOP + WIN  # 80160 отсчётов ≈ 5.01 с


class GigaamFrontend:
    """WAV(int16/float mono 16k) → ``features [1, 64, 500]`` float32 log-mel.

    Точно апстримный фронтенд: ``torchaudio.MelSpectrogram(n_mels=64, win=320,
    hop=160, n_fft=320, center=False)`` → ``log(clamp(x, 1e-9, 1e9))``. Длиннее
    окна — обрезается, короче — дополняется повтором последнего кадра.
    torch подгружается лениво (CPU-у VAD он не нужен).
    """

    def __init__(self, num_threads: int = 4, allowed_ids=None):
        import torch
        from torch import nn
        import torchaudio
        self._torch = torch
        torch.set_num_threads(max(1, int(num_threads)))
        self._allowed_ids = set(allowed_ids) if allowed_ids is not None else None
        self._lang_mask = None

        class SpecScaler(nn.Module):
            def forward(self, x):
                return torch.log(x.clamp_(1e-9, 1e9))

        self._feat = nn.Sequential(
            torchaudio.transforms.MelSpectrogram(
                sample_rate=SR, n_mels=N_MELS, win_length=WIN, hop_length=HOP,
                n_fft=N_FFT, center=CENTER),
            SpecScaler(),
        ).eval()

    def features(self, samples_16k_mono: np.ndarray) -> np.ndarray:
        """float32 моно @16 кГц (диапазон [-1,1]) → [1, 64, 500] float32."""
        torch = self._torch
        sig = torch.from_numpy(np.ascontiguousarray(samples_16k_mono, dtype=np.float32))
        with torch.no_grad():
            f = self._feat(sig.unsqueeze(0))
        t = f.shape[-1]
        if t < FRAMES:
            pad = f[:, :, -1:].repeat(1, 1, FRAMES - t)
            f = torch.cat([f, pad], -1)
        else:
            f = f[:, :, :FRAMES]
        return f.numpy().astype("float32")

    def run_windows(self, engine: Engine, samples_16k_mono: np.ndarray):
        """Разбить фразу на окна ≤500 фреймов, прогнать каждое по NPU.

        Возвращает (collapsed_ids: list[int], latency_ms: list[float]).
        """
        collapsed = []
        lat = []
        n = int(samples_16k_mono.size)
        if n == 0:
            return collapsed, lat
        step = WINDOW_SAMPLES
        pos = 0
        while pos < n:
            chunk = samples_16k_mono[pos:pos + step]
            feats = self.features(chunk)
            out, ms = engine.run(feats)
            lat.append(ms)
            logits = out[0]
            if self._allowed_ids is not None:
                n_tok = logits.shape[-1]
                if self._lang_mask is None or self._lang_mask.size != n_tok:
                    self._lang_mask = np.full(n_tok, -1e9, dtype=np.float32)
                    for tid in self._allowed_ids:
                        if 0 <= tid < n_tok:
                            self._lang_mask[tid] = 0.0
                logits = logits + self._lang_mask
            am = logits.argmax(-1)
            win_ids = collapse(am)
            if (collapsed and win_ids
                    and collapsed[-1] != WORD_SEP_ID
                    and win_ids[0] != WORD_SEP_ID):
                collapsed.append(WORD_SEP_ID)
            collapsed.extend(win_ids)
            pos += step
            # хвост, короче шага, но не с нуля: обработаем следующим куском
        return collapsed, lat


def resolve_model_rknn(model_path: str, model_file: str = ""):
    """Разрешить путь к ``.rknn`` и директорию модели (по аналогии с vosk model_path).

    ``model_path`` — директория с ``.rknn``/vocab (как директория модели vosk) либо
    прямой путь к ``.rknn``. Возвращает ``(rknn_path, model_dir)``.
    """
    if os.path.isdir(model_path):
        model_dir = model_path
        if model_file:
            rknn = os.path.join(model_dir, model_file)
            if not os.path.isfile(rknn):
                raise FileNotFoundError(f"модель не найдена: {rknn}")
            return rknn, model_dir
        cands = sorted(
            os.path.join(model_dir, f) for f in os.listdir(model_dir)
            if f.endswith(".rknn"))
        if not cands:
            raise FileNotFoundError(
                f"в каталоге {model_dir} нет .rknn (задайте model_path на .rknn "
                f"или укажите model_file)")
        return cands[0], model_dir
    if os.path.isfile(model_path) and model_path.endswith(".rknn"):
        return model_path, os.path.dirname(os.path.abspath(model_path))
    raise FileNotFoundError(f"не удалось разрешить модель: {model_path}")


# --- Silero VAD по NPU (экспериментально) ------------------------------------

class SileroVadRknn:
    """Потоковый Silero VAD (v4) поверх RKNN-графа через :class:`Engine`.

    Контракт стримингового Silero: аудио-окно ``[1, 512]`` @16 кГц + скрытые
    состояния ``h``/``c`` (или единый ``state``) на входе, вероятность речи +
    обновлённые состояния на выходе. Порядок/имена тензоров зависят от экспорта
    .rknn — здесь авто-детект по количеству и форме входов/выходов; при запуске
    логируются имена и формы, чтобы подстроить под конкретный экспорт. Требуется
    статический экспорт silero_vad.onnx в .rknn (RKNN-Toolkit2 2.3.2).
    """

    WINDOW = 512  # silero v4 @16k

    def __init__(self, engine: Engine):
        self.engine = engine
        ins = engine.input_names()
        self._n_in = len(ins)
        self._state_h = None
        self._state_c = None
        self._state_combined = None
        # классификация входов: аудио (1D/2D по 512), sr (скаляр), h/c (3D/4D)
        self._audio_idx = 0
        self._sr_idx = None
        self._h_idx = None
        self._c_idx = None
        self._combined_idx = None
        for i, (_name, dims, _t) in enumerate(ins):
            flat = 1
            for d in dims:
                flat *= int(d)
            if flat == 1 or dims == []:
                self._sr_idx = i
            elif dims and dims[-1] == self.WINDOW:
                self._audio_idx = i
            elif len(dims) >= 3 and dims[0] == 2:
                # state [2, B, H] — единый state (hn,cn вместе)
                self._combined_idx = i
            elif len(dims) >= 3:
                if self._h_idx is None:
                    self._h_idx = i
                elif self._c_idx is None:
                    self._c_idx = i
        outs = engine.output_names()
        # выход вероятности: скалярный или [1,2]; состояние — остальные
        self._prob_idx = None
        self._out_state_idx = []
        for i, (_name, dims, _t) in enumerate(outs):
            flat = 1
            for d in dims:
                flat *= int(d)
            if self._prob_idx is None and flat <= 2:
                self._prob_idx = i
            else:
                self._out_state_idx.append(i)

    def describe(self):
        ins = self.engine.input_names()
        outs = self.engine.output_names()
        return {
            "inputs": ins, "outputs": outs,
            "audio_idx": self._audio_idx, "sr_idx": self._sr_idx,
            "h_idx": self._h_idx, "c_idx": self._c_idx,
            "combined_idx": self._combined_idx, "prob_idx": self._prob_idx,
            "out_state_idx": self._out_state_idx,
        }

    def reset(self):
        self._state_h = None
        self._state_c = None
        self._state_combined = None

    def _state_for(self, idx):
        if idx == self._combined_idx:
            return self._state_combined
        if idx == self._h_idx:
            return self._state_h
        if idx == self._c_idx:
            return self._state_c
        return None

    def process_window(self, window_16k: np.ndarray) -> float:
        """Принять окно (<=512 отсчётов float @16k), вернуть вероятность речи [0,1]."""
        w = np.asarray(window_16k, dtype=np.float32)
        if w.size < self.WINDOW:
            w = np.pad(w, (0, self.WINDOW - w.size))
        audio = w.reshape(1, self.WINDOW)

        inputs = []
        for i in range(self._n_in):
            if i == self._audio_idx:
                inputs.append(audio)
            elif i == self._sr_idx:
                inputs.append(np.array(SR, dtype=np.int64))
            elif i in (self._h_idx, self._c_idx, self._combined_idx):
                st = self._state_for(i)
                if st is None:
                    st = self._zero_state(self.engine._in_attrs[i])
                inputs.append(st)
            else:
                st = self._state_for(i)
                inputs.append(st if st is not None else audio)

        outs, _ = self.engine.run_multi(inputs)
        self._update_state(outs)

        prob = outs[self._prob_idx]
        p = np.asarray(prob).reshape(-1)
        if p.size >= 2:  # [no_speech, speech]
            return float(p[-1])
        return float(p[0]) if p.size else 0.0

    def _zero_state(self, attr: _TensorAttr) -> np.ndarray:
        dims = _attr_dims(attr) or [1]
        return np.zeros(dims, dtype=np.float32)

    def _update_state(self, outs):
        if not self._out_state_idx:
            return
        if self._combined_idx is not None and len(self._out_state_idx) >= 1:
            self._state_combined = np.asarray(outs[self._out_state_idx[0]], dtype=np.float32)
            return
        if self._h_idx is not None and len(self._out_state_idx) >= 1:
            self._state_h = np.asarray(outs[self._out_state_idx[0]], dtype=np.float32)
        if self._c_idx is not None and len(self._out_state_idx) >= 2:
            self._state_c = np.asarray(outs[self._out_state_idx[1]], dtype=np.float32)
