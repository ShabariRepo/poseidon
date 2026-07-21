"""Local lexical retrieval — BM25 over a set of documents.

Pure Python, zero dependencies, nothing leaves the machine. This is the same
primitive Poseidon's edge is built on: no embedding API calls (which would ship
your memories/context to a third party and cost per query), just fast local
bag-of-words ranking. Powers:
  - search_memory: find the relevant memory instead of dumping the whole index
  - context compression: detect near-duplicate blocks already in context so we
    don't re-send the same bytes to the model (measured token savings).

BM25 (Okapi) is the standard bag-of-words ranking function — term frequency
saturated by document length. We keep it tiny and dependency-free.
"""

import math
import re
from collections import Counter

_TOKEN_RE = re.compile(r"[a-z0-9]+")
# Common English + code-noise stopwords: cheap precision win, keeps the index
# focused on content terms.
_STOP = frozenset(
    "the a an and or of to in is are be it this that for on with as at by from "
    "you your we our i he she they them if then else return def class import "
    "true false null none self not no yes do does did has have had will would "
    "can could should may might into out up down over under can't won't".split()
)


def tokenize(text: str) -> list:
    return [t for t in _TOKEN_RE.findall((text or "").lower()) if t not in _STOP and len(t) > 1]


class BM25:
    """BM25 index over documents. docs: list of (id, text). Rebuild is cheap;
    for the scale Poseidon works at (dozens–hundreds of memories/blocks) we
    just build on demand."""

    __slots__ = ("k1", "b", "ids", "tf", "df", "idf", "dl", "avgdl", "n")

    def __init__(self, docs, k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.ids = []
        self.tf = []          # per-doc term frequencies
        self.df = Counter()   # document frequency per term
        self.dl = []          # doc lengths
        for doc_id, text in docs:
            toks = tokenize(text)
            counts = Counter(toks)
            self.ids.append(doc_id)
            self.tf.append(counts)
            self.dl.append(len(toks))
            for term in counts:
                self.df[term] += 1
        self.n = len(self.ids)
        self.avgdl = (sum(self.dl) / self.n) if self.n else 0.0
        # Precompute IDF (BM25 form, floored at 0 so common terms don't hurt).
        self.idf = {}
        for term, df in self.df.items():
            self.idf[term] = max(0.0, math.log((self.n - df + 0.5) / (df + 0.5) + 1.0))

    def score(self, query: str, doc_i: int) -> float:
        if self.avgdl == 0:
            return 0.0
        counts, dl = self.tf[doc_i], self.dl[doc_i]
        s = 0.0
        for term in set(tokenize(query)):
            f = counts.get(term, 0)
            if not f:
                continue
            idf = self.idf.get(term, 0.0)
            denom = f + self.k1 * (1 - self.b + self.b * dl / self.avgdl)
            s += idf * (f * (self.k1 + 1)) / denom
        return s

    def search(self, query: str, top_k: int = 5, min_score: float = 0.0):
        """Return [(doc_id, score)] best-first, above min_score."""
        scored = [(self.ids[i], self.score(query, i)) for i in range(self.n)]
        scored = [(d, s) for d, s in scored if s > min_score]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]


def jaccard(a: str, b: str) -> float:
    """Token-set Jaccard similarity — a cheap 'are these two blocks basically
    the same?' check for the compressor's near-duplicate detection."""
    sa, sb = set(tokenize(a)), set(tokenize(b))
    if not sa or not sb:
        return 0.0
    inter = len(sa & sb)
    return inter / (len(sa) + len(sb) - inter)
