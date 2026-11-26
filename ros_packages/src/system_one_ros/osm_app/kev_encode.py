"""One Kev question as a single causal row.

Questions are encoded separately. A packed row would let later questions leak
into the Gated DeltaNet state, and the published file holds 320 tokens.
"""
import json
import re

from .api import LimitError

MAX_CONTEXT = 320
SPECIAL = (
    "<|fim_prefix|>",
    "<|fim_middle|>",
    "<|box_start|>",
    "<|box_end|>",
    "<|fim_suffix|>",
)
_SPECIAL_RE = re.compile(r"<\|([A-Za-z0-9_]+)\|>")


def state_text(state):
    if isinstance(state, str):
        return state
    return json.dumps(state, ensure_ascii=False)


def user_ids(tok, text):
    text = _SPECIAL_RE.sub(lambda match: "<¦%s¦>" % match.group(1), text)
    return tok.encode(text, add_special_tokens=False).ids


def encode_question(tok, state, item):
    ids_of = [tok.token_to_id(token) for token in SPECIAL]
    if any(token_id is None for token_id in ids_of):
        raise LimitError("Kev tokenizer is missing the decision special tokens")
    prefix, question, open_opt, close_opt, decide = ids_of
    state_tokens = user_ids(tok, state_text(state))
    ids = [prefix] + state_tokens
    instr = [question] + user_ids(tok, item["instructions"])
    spans = [[open_opt] + user_ids(tok, option) + [close_opt] for option in item["options"]]
    branch = instr + [token for span in spans for token in span] + [decide]
    base = len(ids)
    ids = ids + branch
    if len(ids) > MAX_CONTEXT:
        raise LimitError("Kev row is %d tokens; this file holds %d" % (len(ids), MAX_CONTEXT))
    cursor = len(instr)
    opt_idx = []
    for span in spans:
        cursor += len(span)
        opt_idx.append(base + cursor - 1)
    return ids, len(ids) - 1, opt_idx
