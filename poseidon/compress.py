"""Context compression — cut tokens SENT to the model without changing the
answer. This is the "save X% out of the box, free" lever, grounded in the
token-cost study: remove provably-redundant content from the request while
preserving every operative fact.

Two safe, deterministic passes (no model call, nothing lost):

1. DEDUPE RE-SENT BLOCKS. In an agent loop the same large output — a file the
   agent read twice, a tool result repeated — sits in the history and is
   re-billed in full every turn. When an identical large block appears more
   than once, keep the LATEST copy verbatim and replace the earlier ones with
   a one-line pointer. The information is still there (in the latest copy), so
   the model loses nothing; we just stop paying for the same bytes N times.
   This is the dominant win for coding/agent workloads (repeated file reads).

2. WHITESPACE NORMALIZE. Collapse 3+ blank lines to one, strip trailing
   spaces. Tiny but free.

Everything is measured: compress() returns the token delta so the UI can show
a real, provable savings number instead of a marketing claim.
"""

import re

MIN_BLOCK = 240          # only dedupe blocks big enough to matter (chars)
_WS = re.compile(r"[ \t]+\n")
_BLANKS = re.compile(r"\n{3,}")


def _norm(text: str) -> str:
    return _BLANKS.sub("\n\n", _WS.sub("\n", text or "")).rstrip()


def _key(text: str) -> str:
    # dedupe key: whitespace-insensitive so re-reads with trivial spacing diffs
    # still collapse.
    return re.sub(r"\s+", " ", text or "").strip()


def _content_str(m: dict) -> str:
    c = m.get("content")
    return c if isinstance(c, str) else ""


def compress(messages: list, est_tokens) -> tuple:
    """Return (compressed_messages, tokens_saved). est_tokens(list)->int is the
    caller's tokenizer estimate so the saving is counted the same way cost is.
    Never touches the system message (index 0) or message structure/tool ids —
    only the text content of large, repeated blocks."""
    if len(messages) < 4:
        return messages, 0

    before = est_tokens(messages)

    # Map each large normalized block to the index of its LAST occurrence.
    last_seen = {}
    for i, m in enumerate(messages):
        s = _content_str(m)
        if len(s) >= MIN_BLOCK:
            last_seen[_key(s)] = i

    out = []
    for i, m in enumerate(messages):
        s = _content_str(m)
        if i == 0 or not isinstance(m.get("content"), str):
            out.append(m)
            continue
        k = _key(s)
        if len(s) >= MIN_BLOCK and last_seen.get(k, i) != i:
            # An identical block appears later — stub this earlier copy.
            nm = dict(m)
            nm["content"] = (
                "[identical earlier output elided to save tokens — the current "
                "copy appears later in this conversation]"
            )
            out.append(nm)
        else:
            nm = dict(m)
            nm["content"] = _norm(s)
            out.append(nm)

    after = est_tokens(out)
    saved = max(0, before - after)
    return out, saved
