"""Non-speakable content tag convention (grouped).

The robot speaks answers aloud, so some spans must not be recited: phone
numbers, e-mail addresses, web links, calendar dates, statute references and
opening-hours. Rather than one opaque ``<nospeak>`` block (which the consumer
can't filter), each non-speakable span is wrapped in a tag named for its GROUP:

* ``<phone>…</phone>``  — phone numbers (incl. a "доб. NNNNN" extension, and a
  bare extension when the number itself is given separately)
* ``<email>…</email>``  — e-mail addresses
* ``<link>…</link>``    — web URLs
* ``<date>…</date>``    — calendar dates ("18 мая 2020 г.", "до 25 июля")
* ``<law>…</law>``      — statute/decree refs ("Федеральный закон № 63-ФЗ")
* ``<hours>…</hours>``  — opening / reception hours ("Пн–Пт 09:00–18:00")

Two curation rules govern ``date``/``law``/``hours`` (and label-led phone/email/
link), and they need per-entry judgement — see mirea_data/TAGS.md:

1. The tag wraps the WHOLE phrase, not a dangling fragment, so stripping the
   group leaves no orphan label ("часы работы УО:" with nothing after it).
2. Skip the tag when the value IS the answer the question asks for — there the
   voice should speak it.

ФГОС programme codes ("09.03.01"), room/dorm numbers ("А-419", "корпус №4") and
money amounts are deliberately NOT tagged: they are speakable and a listener can
act on them.

Separate groups let the *consumer* (the script that feeds the LLM / drives TTS,
e.g. ``scripts/rag_chat.py``) decide per group: strip a group entirely, or
unwrap it (keep the value, drop the markup). That policy does NOT belong in the
shared RAG server — see mirea_data/TAGS.md for the full spec.

Marking is a curation step done by the LLM agent reading each entry
(see mirea_data/TAGS.md), not an automatic ingest stage.
"""
from __future__ import annotations

import re

# All tag groups, in canonical order. The consumer addresses these by name, and
# the recognition regexes below cover every group so consumer-side strip/unwrap
# and the idempotency guard work for date/law/hours too.
GROUPS = ("link", "email", "phone", "date", "law", "hours")

# Auto-detectable, self-contained spans (regex-safe): only these are wrapped by
# tag_nospeak(). date/law/hours are placed by the LLM curator — their span is a
# whole phrase (rule 1) and may be skipped when the value is the answer
# (rule 2), which no regex can decide. Room/dorm numbers, money and ФГОС codes
# are never matched.
_TARGET_RE = re.compile(
    r"(?P<link>https?://[^\s<>'\")\]}]*[^\s<>'\")\]}\.,;:!?«»\"'])"  # web URL
    r"|(?P<email>[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})"  # e-mail
    r"|(?P<phone>"                              # phone: full number OR bare ext
    r"(?<!\d)(?:\+7|8)[\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}"
    r"(?:\s*доб\.?\s*\d{1,5})?(?!\d)"
    r"|доб\.?\s*\d{2,6}(?!\d))"
)

# Matches any single group block (opening/closing tags must agree).
ANY_GROUP_RE = re.compile(
    "|".join(rf"<{g}>.*?</{g}>" for g in GROUPS), re.DOTALL
)
_ANY_GROUP_RE = ANY_GROUP_RE

# Tag markers only (open/close), for shielding the convention from the ingest
# pipeline: cleaner.strip_html and qa_ingest.strip_html both run "<[^>]+>" over
# the text, which would silently eat every curated <phone>/<hours>/… marker on a
# full rebuild. protect_nospeak/restore_nospeak wrap such strippers so the
# markup survives. Single source of truth for the tag vocabulary = GROUPS.
_TAG_MARK_RE = re.compile(r"</?(?:" + "|".join(GROUPS) + r")>")
_SENTINEL = "\x00NS{}\x00"


def protect_nospeak(text: str) -> tuple[str, list[str]]:
    """Swap nospeak tags for inert placeholders.

    Returns ``(text, stash)``; pass both to :func:`restore_nospeak` after the
    stripping is done. Placeholders contain no whitespace or punctuation the
    HTML/markdown strippers touch, so they survive unchanged.
    """
    if not text:
        return text, []
    stash: list[str] = []

    def _sub(m: re.Match) -> str:
        stash.append(m.group(0))
        return _SENTINEL.format(len(stash) - 1)

    return _TAG_MARK_RE.sub(_sub, text), stash


def restore_nospeak(text: str, stash: list[str]) -> str:
    """Inverse of :func:`protect_nospeak`."""
    if not text or not stash:
        return text
    for i, tag in enumerate(stash):
        text = text.replace(_SENTINEL.format(i), tag)
    return text


def _wrap(m: re.Match) -> str:
    return f"<{m.lastgroup}>{m.group(0)}</{m.lastgroup}>"


def tag_nospeak(text: str) -> str:
    """Wrap URLs, e-mails and phone numbers in their group tag.

    Idempotent: existing group blocks are protected and left untouched, so
    re-running never nests or double-wraps. Returns the text unchanged when
    nothing matches.
    """
    if not text:
        return text
    protected: list[str] = []

    def _stash(m: re.Match) -> str:
        protected.append(m.group(0))
        return f"\x00{len(protected) - 1}\x00"

    work = _ANY_GROUP_RE.sub(_stash, text)
    work = _TARGET_RE.sub(_wrap, work)
    work = re.sub(r"\x00(\d+)\x00", lambda m: protected[int(m.group(1))], work)
    return work


def _resolve(groups) -> tuple[str, ...]:
    return tuple(groups) if groups is not None else GROUPS


def strip_nospeak(text: str, groups=None) -> str:
    """Remove tagged blocks (tag + content) for the given groups.

    ``groups`` is an iterable of group names (``"link"``, ``"email"``,
    ``"phone"``); ``None`` means every group. The consumer uses this to drop
    non-speakable content before feeding the LLM or TTS — e.g. voice mode
    strips ``("phone", "email")`` and keeps or unwraps ``"link"``.

    Idempotent: text with no tags is returned unchanged. Removes each matched
    block and the whitespace around it, collapsing the gap so surrounding words
    neither fuse together nor leave doubled spaces. Newlines are kept.
    """
    if not text:
        return text
    sel = _resolve(groups)
    out = text
    for g in sel:
        out = re.sub(rf"<{g}>.*?</{g}>", " ", out, flags=re.DOTALL)
    out = re.sub(r"[ \t]{2,}", " ", out)
    out = re.sub(r"[ \t]+([,.;:!?)\]])", r"\1", out)   # collapse gap before punct
    out = re.sub(r"\n[ \t]+", "\n", out)
    return out.strip()


def unwrap_nospeak(text: str, groups=None) -> str:
    """Keep the tag content, drop the markup, for the given groups.

    ``groups`` as in :func:`strip_nospeak`; ``None`` means every group. The
    consumer uses this when it wants to SHOW a value (e.g. render the URL in a
    ``<link>`` block as a clickable link in a text UI) rather than hide it.
    """
    if not text:
        return text
    sel = _resolve(groups)
    out = text
    for g in sel:
        out = re.sub(rf"<{g}>(.*?)</{g}>", r"\1", out, flags=re.DOTALL)
    out = re.sub(r"[ \t]{2,}", " ", out)
    return out.strip()
