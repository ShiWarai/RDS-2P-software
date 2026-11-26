"""TypeSafe /v1/systemone request check and answer assembly."""
import json
import math


class ApiError(Exception):
    def __init__(self, status, detail):
        super().__init__(detail[0]["msg"] if detail else "invalid request")
        self.status = status
        self.detail = detail


class LimitError(Exception):
    """The encoded question does not fit the compiled model."""


CANONICAL = {
    "laya-multilingual": "laya-multilingual",
    "multilingual": "laya-multilingual",
    "kev-0.8b": "kev-0.8b",
    "kev-latest": "kev-0.8b",
}


def _err(loc, msg, kind):
    return {"loc": loc, "msg": msg, "type": kind}


def _fail(loc, msg, kind="value_error"):
    raise ApiError(422, [_err(loc, msg, kind)])


def softmax(logits, temperature):
    temp = temperature if temperature and temperature > 0 else 1.0
    scaled = [float(x) / temp for x in logits]
    peak = max(scaled)
    exps = [math.exp(x - peak) for x in scaled]
    total = sum(exps) or 1.0
    return [e / total for e in exps]


def choice_confidence(probs):
    count = len(probs)
    if count <= 1:
        return 1.0
    top = max(probs)
    return (top - 1.0 / count) / (1.0 - 1.0 / count)


def score_confidence(probs):
    count = len(probs)
    if count <= 1:
        return 1.0
    mode = max(range(count), key=lambda i: probs[i])
    middle = (count - 1) / 2.0
    uniform = sum(abs(i - middle) for i in range(count)) / count
    if uniform == 0:
        return 1.0
    spread = sum(abs(i - mode) * p for i, p in enumerate(probs))
    return max(0.0, 1.0 - spread / uniform)


def _text(value):
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _option_text(name, desc):
    if desc is None or desc == "":
        return name
    if isinstance(desc, str):
        return "%s: %s" % (name, desc)
    return "%s: %s" % (name, json.dumps(desc, ensure_ascii=False, separators=(", ", ": ")))


def normalize_question(name, raw):
    loc = ["body", "questions", name]
    if not isinstance(raw, dict):
        _fail(loc, "question must be an object")
    kind = raw.get("type")
    if kind not in ("choice", "noul", "score"):
        _fail(loc + ["type"], "type must be choice, noul, or score")
    instructions = _text(raw.get("instructions"))
    criteria = raw.get("criteria")
    if kind == "choice":
        if not isinstance(criteria, dict) or not criteria:
            _fail(loc + ["criteria"], "choice criteria must be a non-empty object")
        labels = list(criteria)
        options = [_option_text(key, criteria[key]) for key in labels]
    elif kind == "score":
        if not isinstance(criteria, list) or not criteria:
            _fail(loc + ["criteria"], "score criteria must be a non-empty array")
        labels = [str(i) for i in range(len(criteria))]
        options = [_text(item) for item in criteria]
    else:
        if criteria is None:
            criteria = {}
        if not isinstance(criteria, dict):
            _fail(loc + ["criteria"], "noul criteria must be an object")
        extra = set(criteria) - {"true", "false"}
        if extra:
            _fail(loc + ["criteria"], "noul criteria keys are only true and false")
        labels = ["false", "true"]
        options = [
            _option_text("no", criteria.get("false")),
            _option_text("yes", criteria.get("true")),
        ]
    return {
        "id": name,
        "kind": kind,
        "instructions": instructions,
        "labels": labels,
        "options": options,
        "criteria": criteria,
    }


def parse_request(payload, known_models):
    if not isinstance(payload, dict):
        _fail(["body"], "body must be an object")
    if "state" not in payload:
        _fail(["body", "state"], "Field required", "missing")
    state = payload["state"]
    if not isinstance(state, (str, dict, list)):
        _fail(["body", "state"], "state must be a string, object, or array")
    if "model" not in payload:
        _fail(["body", "model"], "Field required", "missing")
    model = payload["model"]
    if not isinstance(model, str) or model not in CANONICAL:
        _fail(["body", "model"], "unknown model")
    canonical = CANONICAL[model]
    if canonical not in known_models:
        _fail(["body", "model"], "model is not loaded")
    questions = payload.get("questions")
    if not isinstance(questions, dict) or not questions:
        _fail(["body", "questions"], "questions must contain at least one question")
    items = [normalize_question(name, raw) for name, raw in questions.items()]
    return canonical, state, items


def assemble(item, probs):
    kind = item["kind"]
    labels = item["labels"]
    rounded = {label: round(float(p), 4) for label, p in zip(labels, probs)}
    if kind == "noul":
        return {"type": "noul", "noul": round(float(probs[1]), 4)}
    if kind == "choice":
        picked = max(range(len(probs)), key=lambda i: probs[i])
        return {
            "type": "choice",
            "choice": labels[picked],
            "confidence": round(choice_confidence(probs), 4),
            "probabilities": rounded,
        }
    picked = max(range(len(probs)), key=lambda i: probs[i])
    expected = sum(i * float(p) for i, p in enumerate(probs))
    legend_src = item["criteria"]
    legend = {str(i): legend_src[i] if isinstance(legend_src[i], str) else _text(legend_src[i]) for i in range(len(legend_src))}
    return {
        "type": "score",
        "score": round(expected, 4),
        "confidence": round(score_confidence(probs), 4),
        "legend": legend,
        "probabilities": rounded,
    }


def response(model, answers, input_tokens, output_tokens):
    return {
        "model": model,
        "answers": answers,
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
    }
