"""The cost meter. Rough per-1M-token prices by model-name substring.

Unknown models cost $0 and are flagged unpriced rather than guessed.
"""

# (substring, input $/1M, output $/1M) — first match wins, most specific first.
PRICES = [
    ("gpt-4o-mini", 0.15, 0.60),
    ("gpt-4o", 2.50, 10.00),
    ("gpt-4.1-mini", 0.40, 1.60),
    ("gpt-4.1", 2.00, 8.00),
    ("o3-mini", 1.10, 4.40),
    ("claude-haiku", 1.00, 5.00),
    ("claude-sonnet", 3.00, 15.00),
    ("claude-opus", 15.00, 75.00),
    ("haiku", 1.00, 5.00),
    ("sonnet", 3.00, 15.00),
    ("opus", 15.00, 75.00),
    ("llama-3.3-70b", 0.59, 0.79),
    ("llama", 0.20, 0.20),
    ("hermes", 0.0, 0.0),   # local
    ("qwen", 0.0, 0.0),     # usually local
    ("mistral", 0.25, 0.25),
]


def price_for(model: str):
    m = (model or "").lower()
    for sub, pin, pout in PRICES:
        if sub in m:
            return pin, pout
    return None


def compute_cost(model: str, usage: dict) -> tuple[float, bool]:
    """Returns (usd, priced). usage is the OpenAI-style usage block."""
    if not usage:
        return 0.0, False
    p = price_for(model)
    if p is None:
        return 0.0, False
    pin, pout = p
    cin = usage.get("prompt_tokens", 0) * pin / 1_000_000
    cout = usage.get("completion_tokens", 0) * pout / 1_000_000
    return cin + cout, True
