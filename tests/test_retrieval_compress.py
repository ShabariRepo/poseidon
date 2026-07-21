from poseidon.retrieval import BM25, jaccard, tokenize
from poseidon.compress import compress


def _est(msgs):
    import json
    return sum(len(json.dumps(m)) for m in msgs) // 4


def test_bm25_ranks_relevant_first():
    docs = [("a", "billing invoices and refunds policy"),
            ("b", "deploy the frontend to vercel"),
            ("c", "refund an invoice for a customer")]
    hits = BM25(docs).search("how do refunds on invoices work", top_k=2)
    assert hits and hits[0][0] in ("a", "c")
    assert hits[0][1] > 0


def test_bm25_empty_and_nomatch():
    assert BM25([]).search("x") == []
    docs = [("a", "totally unrelated content here")]
    assert BM25(docs).search("zzz qqq", min_score=0.01) == []


def test_jaccard():
    assert jaccard("read the config file", "read the config file") == 1.0
    assert jaccard("apple banana", "car train") == 0.0


def test_compress_dedupes_repeated_block():
    big = "def handler():\n" + "    x = compute_value()  # long line of code\n" * 40
    msgs = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "read the file"},
        {"role": "tool", "content": big},        # first read
        {"role": "assistant", "content": "ok"},
        {"role": "user", "content": "read it again"},
        {"role": "tool", "content": big},        # identical re-read
    ]
    out, saved = compress(msgs, _est)
    assert saved > 0                              # real tokens saved
    assert "elided" in out[2]["content"]          # earlier copy stubbed
    assert out[5]["content"].strip() == big.strip()  # latest copy kept intact
    assert out[0]["content"] == "sys"             # system untouched


def test_compress_noop_short():
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "hi"}]
    out, saved = compress(msgs, _est)
    assert saved == 0 and out == msgs
