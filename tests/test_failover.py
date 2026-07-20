"""Failover chain: fallback_providers fills keys from the per-provider vault."""
from poseidon.orchestrator import fallback_providers


def test_empty_config():
    assert fallback_providers({}) == []


def test_vault_fills_missing_keys():
    cfg = {
        "provider_keys": {"https://api.groq.com/openai/v1": "gsk_x"},
        "provider_fallbacks": [
            {"base_url": "https://api.groq.com/openai/v1", "model": "llama-3.3-70b-versatile"},
            {"base_url": "https://api.openai.com/v1", "model": "gpt-4o-mini"},
        ],
    }
    out = fallback_providers(cfg)
    assert len(out) == 2
    assert out[0]["api_key"] == "gsk_x"          # filled from vault
    assert out[1]["api_key"] == ""               # no vault entry -> empty


def test_inline_key_wins_and_invalid_entries_skipped():
    cfg = {
        "provider_keys": {"https://a/v1": "vault_key"},
        "provider_fallbacks": [
            {"base_url": "https://a/v1", "model": "m", "api_key": "inline_key"},
            {"base_url": "", "model": "m"},          # no base_url -> skipped
            {"base_url": "https://b/v1"},            # no model -> skipped
        ],
    }
    out = fallback_providers(cfg)
    assert len(out) == 1
    assert out[0]["api_key"] == "inline_key"


def test_original_config_not_mutated():
    fb = {"base_url": "https://a/v1", "model": "m"}
    cfg = {"provider_keys": {"https://a/v1": "k"}, "provider_fallbacks": [fb]}
    fallback_providers(cfg)
    assert "api_key" not in fb  # helper copies, never mutates config
