#!/usr/bin/env python3
"""Сверка ONNX-графа с эталонным сервисом (PLAN.md 11).

python3 tools/verify_onnx_vs_service.py \
    [--onnx models/laya/laya_multilingual_seq512.onnx] \
    [--service http://192.168.1.40:8000/v1/systemone] \
    [--rules assets/rules/panda_rules.json] [--threshold 0.99]

ONNX гоняется через onnxruntime (CPU), сервис — HTTP POST в формате /v1/systemone.
Считается совпадение выбранной метки (argmax) на наборе фраз; цель ≥ 99 %.
Токенизация повторяет app/laya_encode.py (laya==0.3.20, multilingual).
"""
from __future__ import annotations

import argparse
import json
import math
import urllib.request
from pathlib import Path

import numpy as np

MAX_LEN = 512
HEAD_MAX_LEN = 256
KMAX = 64
QTYPES = {"choice": 0, "score": 1, "noul": 2}
CLS, SEP, PAD, MASK = 2, 1, 0, 4

ROOT = Path(__file__).resolve().parents[1]


class HubTok:
    def __init__(self, tokenizer):
        self.tokenizer = tokenizer
        self.mask_token = "<mask>"
        self.mask_token_id = MASK
        self.cls_token_id = CLS
        self.sep_token_id = SEP

    def encode(self, text, truncation=False, max_length=None):
        ids = self.tokenizer.encode(text, add_special_tokens=False).ids
        if truncation and max_length is not None:
            ids = ids[:max_length]
        return {"input_ids": ids}


def build_sequence(tok, state, options, instructions):
    opts = list(options)
    ins = str(instructions).replace(tok.mask_token, " ")
    head_ids = tok.encode(f"choice question: {ins}")["input_ids"]
    opt_ids = []
    for opt in opts:
        opt_tokens = tok.encode(" " + opt.replace(tok.mask_token, " "), True, 48)["input_ids"]
        opt_ids.append([tok.mask_token_id] + opt_tokens)
    opt_budget = HEAD_MAX_LEN - sum(len(o) for o in opt_ids)
    if opt_budget < 16:
        per = max(4, (HEAD_MAX_LEN - 16) // max(1, len(opt_ids)))
        opt_ids = [o[:per] for o in opt_ids]
        opt_budget = HEAD_MAX_LEN - sum(len(o) for o in opt_ids)
    head_ids = head_ids[: max(8, opt_budget)]
    ids = [tok.cls_token_id] + head_ids + [tok.sep_token_id]
    markers = []
    for opt in opt_ids:
        markers.append(len(ids))
        ids.extend(opt)
    ids.append(tok.sep_token_id)
    room = MAX_LEN - len(ids) - 1
    if room < 0:
        raise ValueError("вопрос не влезает")
    state_ids = tok.encode(str(state).replace(tok.mask_token, " "))["input_ids"]
    ids = ids + state_ids[:room] + [tok.sep_token_id]
    return ids, markers


def pad_arrays(ids, markers):
    input_ids = np.full((1, MAX_LEN), PAD, np.int64)
    attention = np.zeros((1, MAX_LEN), np.int64)
    marker_pos = np.zeros((1, KMAX), np.int64)
    marker_mask = np.zeros((1, KMAX), np.bool_)
    input_ids[0, : len(ids)] = ids
    attention[0, : len(ids)] = 1
    marker_pos[0, : len(markers)] = markers
    marker_mask[0, : len(markers)] = 1
    return [input_ids, attention, marker_pos, marker_mask, np.array([QTYPES["choice"]], np.int64)]


def softmax(logits, temperature=1.0):
    scaled = np.asarray(logits, np.float64) / (temperature or 1.0)
    e = np.exp(scaled - scaled.max())
    return e / e.sum()


def choose_options(rules_data):
    """{"rules":[...]} → список вариантов первого choice-вопроса {name, examples}.

    Поддерживает v3-дерево (kind/question/options) и плоский v1-список правил.
    """
    roots = rules_data.get("rules") or rules_data.get("roots") or []
    flat = [r for r in roots if "kind" not in r]
    if flat:
        return [{"name": r["name"], "examples": list(r.get("examples", []))} for r in flat]
    queue = list(roots)
    while queue:
        node = queue.pop(0)
        if node.get("kind") == "question" and node.get("qtype") == "choice":
            return [{"name": o.get("name", ""), "examples": list(o.get("examples", []))} for o in node.get("options", [])]
        queue.extend(node.get("then", []) or [])
        for opt in node.get("options", []) or []:
            queue.extend(opt.get("then", []) or [])
        for q in node.get("outcomes", []) or []:
            queue.extend(q.get("then", []) or [])
        queue.extend(node.get("yes", []) or [])
        queue.extend(node.get("no", []) or [])
    return []


def rules_payload(options):
    """Критерии как в приложении: ключ — название варианта, значение — примеры.

    Сырые id в тексте варианта («r_paw: Дай лапу: ...») ломают классификатор —
    см. probe-замер: «дай лапу» 99% → мусор.
    """
    criteria = {}
    for o in options:
        criteria[o["name"]] = ", ".join(o["examples"])
    return {
        "model": "laya-multilingual",
        "questions": {
            "command": {
                "type": "choice",
                "instructions": "Какая команда подходит к фразе?",
                "criteria": criteria,
            }
        },
    }


def test_phrases(options):
    phrases = []
    for o in options:
        for ex in o["examples"][:2]:
            phrases.append((ex, o["name"]))
    phrases.append(("спой гимн", None))
    phrases.append(("полная неизвестная чушь", None))
    return phrases


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--onnx", type=Path, default=ROOT / "models/laya/model.onnx")
    parser.add_argument("--tokenizer", type=Path, default=ROOT / "models/laya/tokenizer.json")
    parser.add_argument("--temperature", type=Path, default=ROOT / "models/laya/temperature.json")
    parser.add_argument("--rules", type=Path, default=ROOT / "assets/rules/panda_rules.json")
    parser.add_argument("--service", default=None, help="URL /v1/systemone для сравнения; без него — только self-check")
    parser.add_argument("--threshold", type=float, default=0.99)
    args = parser.parse_args()

    try:
        import onnxruntime as ort  # noqa: F401
    except ImportError:
        raise SystemExit("pip install onnxruntime") from None
    from tokenizers import Tokenizer  # type: ignore
    import onnx  # noqa: F401

    onnx_path = args.onnx if args.onnx.is_absolute() else ROOT / args.onnx
    tok = HubTok(Tokenizer.from_file(str(args.tokenizer)))
    temps = [1.0, 1.0, 1.0]
    temp_path = args.temperature if args.temperature.is_absolute() else ROOT / args.temperature
    if temp_path.exists():
        temps = json.load(open(temp_path))["temperature"]

    model = onnx.load(str(onnx_path), load_external_data=False)
    input_types = {i.name: i.type.tensor_type.elem_type for i in model.graph.input}
    int32_inputs = all(t in (1, 6) for t in input_types.values() if t != 1)  # INT32=1, INT64=7
    sess = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])

    rules_data = json.load(open(args.rules if args.rules.is_absolute() else ROOT / args.rules, encoding="utf-8"))
    options_meta = choose_options(rules_data)
    if not options_meta:
        raise SystemExit("в правилах не найден choice-вопрос с вариантами")
    payload = rules_payload(options_meta)
    criteria = payload["questions"]["command"]["criteria"]
    labels = list(criteria)
    options = [f"{k}: {v}" if v else k for k, v in criteria.items()]

    def run_onnx(state):
        ids, markers = build_sequence(tok, state, options, payload["questions"]["command"]["instructions"])
        arrays = pad_arrays(ids, markers)
        feeds = {}
        for meta, arr in zip(sess.get_inputs(), arrays):
            if meta.type == "tensor(int32)":
                arr = arr.astype(np.int32)
            feeds[meta.name] = arr
        logits = sess.run(None, feeds)[0][0][: len(labels)]
        probs = softmax(logits, temps[QTYPES["choice"]])
        return labels[int(np.argmax(probs))], probs

    phrases = test_phrases(options_meta)

    def call_service(state):
        body = dict(payload)
        body["state"] = state
        req = urllib.request.Request(args.service, data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=60) as resp:
            answer = json.loads(resp.read().decode("utf-8"))["answers"]["command"]
        return answer["choice"]

    matched = 0
    total = 0
    for text, expected in phrases:
        choice, probs = run_onnx(text)
        line = f"«{text}» → onnx={choice}"
        if args.service:
            svc = call_service(text)
            ok = svc == choice
            matched += 1 if ok else 0
            total += 1
            line += f" service={svc} {'OK' if ok else 'РАСХОЖДЕНИЕ'}"
        if expected:
            line += f" (ожидалось {expected}{'' if choice == expected else ' — ПРОМАХ'} )"
        print(line)

    if args.service and total:
        agreement = matched / total
        print(f"\nсогласие ONNX ↔ сервис: {matched}/{total} = {agreement:.1%} (цель ≥ {args.threshold:.0%})")
        raise SystemExit(0 if agreement >= args.threshold else 1)
    print("\nсервис не указан (--service) — выполнен только self-check")


if __name__ == "__main__":
    main()
