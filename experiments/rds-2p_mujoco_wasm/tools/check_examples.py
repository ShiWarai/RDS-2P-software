#!/usr/bin/env python3
"""Проверка «своих же примеров»: каждая фраза-пример из вариантов вопросов
(пресет + шаблоны) должна выбирать СВОЙ вариант. Сверка с ONNX-моделью Laya
тем же способом, каким её строит приложение (laya_encode.js).

  python3 tools/check_examples.py                 # пресет + шаблоны (нужен node)
  python3 tools/check_examples.py --max-per-option 3
  python3 tools/check_examples.py --trees /tmp/trees.json   # готовый дамп

Код возврата: 0 — все примеры классифицируются верно, 1 — есть промахи.
Модель: models/laya/model.onnx + tokenizer.json (по manifest.json).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
MAX_LEN = 512
HEAD_MAX_LEN = 256
KMAX = 64
QTYPES = {"choice": 0, "score": 1, "noul": 2}
CLS, SEP, PAD, MASK = 2, 1, 0, 4


def collect_choice_questions(node, out):
    """Рекурсивно собрать все choice-вопросы дерева v3."""
    if not isinstance(node, dict):
        return
    if node.get("kind") == "question" and node.get("qtype") == "choice":
        out.append(node)
    for child in node.get("then", []) or []:
        collect_choice_questions(child, out)
    for opt in node.get("options", []) or []:
        for child in opt.get("then", []) or []:
            collect_choice_questions(child, out)
    for outcome in node.get("outcomes", []) or []:
        for child in outcome.get("then", []) or []:
            collect_choice_questions(child, out)
    for child in (node.get("yes", []) or []) + (node.get("no", []) or []):
        collect_choice_questions(child, out)


def labels_for(options):
    """Как questionSpec в приложении: ключ — название варианта (с дедупликацией)."""
    labels = []
    used = set()
    for i, o in enumerate(options):
        base = str(o.get("name") or "").strip() or f"Вариант {i + 1}"
        label = base
        n = 2
        while label in used:
            label = f"{base} {n}"
            n += 1
        used.add(label)
        labels.append(label)
    return labels


class Encoder:
    def __init__(self, tok, session):
        self.tok = tok
        self.session = session

    def ids(self, text):
        return self.tok.encode(text, add_special_tokens=False).ids

    def ask(self, state, options, instructions):
        head = self.ids(f"choice question: {instructions}")
        opt_ids = [[MASK] + self.ids(" " + o)[:48] for o in options]
        budget = HEAD_MAX_LEN - sum(len(o) for o in opt_ids)
        if budget < 16:
            per = max(4, (HEAD_MAX_LEN - 16) // max(1, len(opt_ids)))
            opt_ids = [o[:per] for o in opt_ids]
            budget = HEAD_MAX_LEN - sum(len(o) for o in opt_ids)
        head = head[: max(8, budget)]
        ids = [CLS] + head + [SEP]
        markers = []
        for o in opt_ids:
            markers.append(len(ids))
            ids.extend(o)
        ids.append(SEP)
        room = max(0, MAX_LEN - len(ids) - 1)
        ids = ids + self.ids(str(state))[:room] + [SEP]
        n = len(ids[:MAX_LEN])
        feeds = {
            "input_ids": np.full((1, MAX_LEN), PAD, np.int64),
            "attention_mask": np.zeros((1, MAX_LEN), np.int64),
            "marker_pos": np.zeros((1, KMAX), np.int64),
            "marker_mask": np.zeros((1, KMAX), np.bool_),
            "qtype": np.array([QTYPES["choice"]], np.int64),
        }
        feeds["input_ids"][0, :n] = ids[:MAX_LEN]
        feeds["attention_mask"][0, :n] = 1
        feeds["marker_pos"][0, : len(markers)] = markers
        feeds["marker_mask"][0, : len(markers)] = True
        logits = self.session.run(None, feeds)[0][0][: len(options)]
        z = logits - logits.max()
        p = np.exp(z.astype(np.float64))
        p = p / p.sum()
        return int(np.argmax(p)), float(p.max()), p


def render_options(labels, options):
    rendered = []
    for label, o in zip(labels, options):
        examples = ", ".join(str(e) for e in (o.get("examples") or []))
        rendered.append(f"{label}: {examples}" if examples else label)
    return rendered


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--trees", type=Path, help="JSON от tools/dump_trees.mjs (иначе запустит node сам)")
    parser.add_argument("--rules", type=Path, default=ROOT / "assets/rules/panda_rules.json")
    parser.add_argument("--onnx", type=Path, default=ROOT / "models/laya/model.onnx")
    parser.add_argument("--tokenizer", type=Path, default=ROOT / "models/laya/tokenizer.json")
    parser.add_argument("--max-per-option", type=int, default=3)
    args = parser.parse_args()

    from tokenizers import Tokenizer
    import onnxruntime as ort

    tok = Tokenizer.from_file(str(args.tokenizer))
    session = ort.InferenceSession(str(args.onnx), providers=["CPUExecutionProvider"])
    enc = Encoder(tok, session)

    preset = json.load(open(args.rules, encoding="utf-8"))
    roots = []
    roots.extend(preset.get("rules") or [])
    if args.trees:
        trees = json.load(open(args.trees, encoding="utf-8"))
    else:
        out = subprocess.run(
            ["node", str(ROOT / "tools/dump_trees.mjs")],
            capture_output=True, text=True, check=True,
        )
        trees = json.loads(out.stdout)
    for tree in trees.values():
        roots.append(tree)

    questions = []
    for root in roots:
        collect_choice_questions(root, questions)

    failures = 0
    tested = 0
    for qi, q in enumerate(questions):
        options = q.get("options") or []
        if len(options) < 2:
            continue
        labels = labels_for(options)
        rendered = render_options(labels, options)
        instr = q.get("instructions") or "Какой вариант лучше подходит к фразе?"
        title = q.get("name") or f"вопрос {qi}"
        print(f"\n■ «{title}» ({len(options)} вар.) — {instr}")
        for label, o in zip(labels, options):
            examples = [str(e) for e in (o.get("examples") or [])][: args.max_per_option]
            for phrase in examples:
                tested += 1
                idx, prob, _ = enc.ask(phrase, rendered, instr)
                ok = labels[idx] == label
                if not ok:
                    failures += 1
                mark = "OK  " if ok else "ПРОМАХ"
                extra = "" if ok else f" (ждали «{label}»)"
                print(f"  {mark} «{phrase}» → «{labels[idx]}» {prob * 100:.0f}%{extra}")

    print(f"\nитог: {tested - failures}/{tested} примеров классифицируются верно")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())