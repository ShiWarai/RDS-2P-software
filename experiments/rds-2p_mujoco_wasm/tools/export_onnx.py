#!/usr/bin/env python3
"""Laya → ONNX для браузера (PLAN.md 7).

Основа — scripts/export_onnx.py из HF ShiWarai/laya-multilingual-rknn
(laya==0.3.20, transformers==5.17.0, torch, opset 18, seq 512, KMAX 64).

Дополнительно:
  - cast int64 → int32 на пяти входах (WebGPU EP не любит int64);
  - --fp16  : приведение весов к fp16 (основной артефакт для WebGPU, ~560 МБ);
  - --int8  : динамическая квантизация MatMul (для WASM EP, ~280 МБ);
  - манифест models/laya/manifest.json + копирование tokenizer.json/temperature.json.

Окружение (x86, Python 3.10):
  python3.10 -m venv .venv && .venv/bin/pip install torch --index-url https://download.pytorch.org/whl/cpu
  .venv/bin/pip install 'laya==0.3.20' 'transformers==5.17.0' onnx numpy
  # для --fp16: .venv/bin/pip install onnxruntime onnxconverter-common
  # для --int8: .venv/bin/pip install onnxruntime
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import sys
from pathlib import Path

SEQ = 512
KMAX = 64

torch = None  # lazy import


def build_torch_modules():
    global torch
    import torch  # noqa: PLC0415

    torch.compile = lambda *args, **kwargs: (lambda fn: fn)

    class ScorerLogits(torch.nn.Module):
        def __init__(self, model):
            super().__init__()
            self.encoder = model.encoder
            self.head = model.head
            self.type_emb = model.type_emb
            self.scorer = model.scorer

        def forward(self, input_ids, attention_mask, marker_pos, marker_mask, qtype):
            h = self.encoder(input_ids=input_ids, attention_mask=attention_mask).last_hidden_state
            h = h + self.type_emb(qtype)[:, None, :]
            pad = attention_mask == 0
            for layer in self.head.layers:
                h = layer(h, src_key_padding_mask=pad)
            idx = marker_pos.clamp(min=0)[:, :, None].expand(-1, -1, h.size(-1))
            gathered = torch.gather(h, 1, idx)
            logits = self.scorer(gathered).squeeze(-1)
            logits = logits.masked_fill(marker_mask == 0, -1.0e4)
            return logits

    return torch, ScorerLogits


def pad_item(torch, ids, markers, qtype, pad_id):
    input_ids = torch.full((1, SEQ), pad_id, dtype=torch.long)
    attention_mask = torch.zeros((1, SEQ), dtype=torch.long)
    marker_pos = torch.zeros((1, KMAX), dtype=torch.long)
    marker_mask = torch.zeros((1, KMAX), dtype=torch.long)
    input_ids[0, : len(ids)] = torch.tensor(ids, dtype=torch.long)
    attention_mask[0, : len(ids)] = 1
    marker_pos[0, : len(markers)] = torch.tensor(markers, dtype=torch.long)
    marker_mask[0, : len(markers)] = 1
    q = torch.tensor([qtype], dtype=torch.long)
    return input_ids, attention_mask, marker_pos, marker_mask, q


def cast_inputs_to_int32(onnx_path: Path) -> None:
    """Graph inputs → INT32 с встроенным Cast в INT64 (без правки потребителей)."""
    import onnx  # noqa: PLC0415
    from onnx import TensorProto, helper, numpy_helper  # noqa: PLC0415

    model = onnx.load(str(onnx_path), load_external_data=False)
    graph = model.graph
    int64_inputs = [i for i in graph.input if i.type.tensor_type.elem_type == TensorProto.INT64]
    if not int64_inputs:
        print("входов int64 нет — cast не нужен")
        return

    for inp in int64_inputs:
        original = inp.name
        renamed = original + "_i32"
        inp.name = renamed
        inp.type.tensor_type.elem_type = TensorProto.INT32
        cast = helper.make_node("Cast", [renamed], [original], to=TensorProto.INT64,
                               name=f"cast_{original}")
        graph.node.insert(0, cast)
    onnx.checker.check_model(model)
    onnx.save(model, str(onnx_path))
    print(f"cast int64→int32 добавлен на входы: {[i.name for i in int64_inputs]}")


def to_fp16(onnx_path: Path) -> None:
    import onnx  # noqa: PLC0415

    try:
        from onnxruntime.transformers.float16 import convert_float_to_float16
    except ImportError as err:
        raise SystemExit("--fp16 требует: pip install onnxruntime onnxconverter-common") from err
    model = onnx.load(str(onnx_path), load_external_data=False)
    model_fp16 = convert_float_to_float16(model, keep_io_types=True,
                                          disable_shape_infer=True)
    onnx.save(model_fp16, str(onnx_path))
    print(f"fp16: {onnx_path} ({onnx_path.stat().st_size / 1e6:.0f} МБ)")


def to_int8(onnx_path: Path, out_path: Path) -> None:
    try:
        from onnxruntime.quantization import QuantType, quantize_dynamic
    except ImportError as err:
        raise SystemExit("--int8 требует: pip install onnxruntime") from err
    quantize_dynamic(str(onnx_path), str(out_path), weight_type=QuantType.QUInt8)
    print(f"int8: {out_path} ({out_path.stat().st_size / 1e6:.0f} МБ)")


def find_tokenizer_files() -> tuple[Path | None, Path | None]:
    """tokenizer.json/temperature.json: рядом со скриптом или из HF-кэша convaiinnovations/laya."""
    here = Path(__file__).resolve().parent
    tok = (here / "tokenizer.json") if (here / "tokenizer.json").exists() else None
    temp = (here / "temperature.json") if (here / "temperature.json").exists() else None
    if not tok:
        cache = os.path.expanduser("~/.cache/huggingface/hub")
        hits = glob.glob(f"{cache}/models--convaiinnovations--laya/snapshots/*/multilingual/tokenizer.json")
        tok = Path(hits[0]) if hits else None
    return tok, temp


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=root / "models/laya/laya_multilingual_seq512.onnx")
    parser.add_argument("--no-int32", action="store_true", help="не делать cast входов в int32")
    parser.add_argument("--fp16", action="store_true", help="конвертировать веса в fp16")
    parser.add_argument("--int8", action="store_true", help="дополнительно собрать int8-вариант")
    args = parser.parse_args()

    torch, ScorerLogits = build_torch_modules()

    try:
        from laya import load  # noqa: PLC0415
    except ImportError:
        raise SystemExit("pip install 'laya==0.3.20' (в venv python3.10) — см. docstring") from None

    print("loading convaiinnovations/laya (multilingual) …", flush=True)
    agent = load("convaiinnovations/laya", subfolder="multilingual", device="cpu")
    model = agent.model
    model.eval()
    enc = model.encoder
    if hasattr(enc, "set_attn_implementation"):
        enc.set_attn_implementation("eager")
    else:
        enc.config._attn_implementation = "eager"

    wrapper = ScorerLogits(model).eval()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    temperature_path = args.out.parent / "temperature.json"
    temp_values = model.temperature.detach().float().cpu().numpy().tolist()
    temperature_path.write_text(json.dumps({"temperature": temp_values}) + "\n", encoding="utf-8")
    print("temperature", temp_values, flush=True)

    example = pad_item(torch, [agent.tok.cls_token_id, agent.tok.sep_token_id], [1], 0, agent.tok.pad_token_id)
    print("exporting", args.out, flush=True)
    with torch.no_grad():
        torch.onnx.export(
            wrapper,
            example,
            str(args.out),
            input_names=["input_ids", "attention_mask", "marker_pos", "marker_mask", "qtype"],
            output_names=["logits"],
            opset_version=18,
            dynamo=False,
        )

    if not args.no_int32:
        cast_inputs_to_int32(args.out)

    if args.fp16:
        to_fp16(args.out)

    manifest = {
        "file": args.out.name,
        "inputs": "int64" if args.no_int32 else "int32",
        "tokenizer": "tokenizer.json",
        "temperature": "temperature.json",
        "seq": SEQ,
        "kmax": KMAX,
    }

    if args.int8:
        int8_path = args.out.with_name(args.out.stem + ".int8.onnx")
        to_int8(args.out, int8_path)
        # int8-версию тоже прогоняем через cast? ORT WASM принимает int64 — оставляем как есть
        manifest["int8"] = int8_path.name

    tok_src, _temp_src = find_tokenizer_files()
    tok_dst = args.out.parent / "tokenizer.json"
    if tok_src and tok_src.exists() and not tok_dst.exists():
        shutil.copyfile(tok_src, tok_dst)
        print("tokenizer.json скопирован в", tok_dst)
    elif not tok_dst.exists():
        print("ВНИМАНИЕ: tokenizer.json не найден — положите его рядом с --out (см. download_models.sh)")

    if not temperature_path.exists() and _temp_src:
        shutil.copyfile(_temp_src, temperature_path)

    (args.out.parent / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("готово:", args.out, args.out.stat().st_size, "байт; манифест записан")


if __name__ == "__main__":
    sys.exit(main())
