from app.services.cursor_client import TokenTotals, _match_member_spend
from app.services.cursor_connection import _default_variant_params


def test_default_variant_params_prefers_is_default():
    model = {
        "variants": [
            {"params": [{"id": "fast", "value": "true"}], "isDefault": False},
            {"params": [{"id": "fast", "value": "false"}], "isDefault": True},
        ]
    }
    assert _default_variant_params(model) == [{"id": "fast", "value": "false"}]


def test_default_variant_params_single_variant():
    model = {
        "variants": [
            {"params": [{"id": "reasoning", "value": "high"}]},
        ]
    }
    assert _default_variant_params(model) == [{"id": "reasoning", "value": "high"}]



def test_token_totals_add():
    totals = TokenTotals()
    totals.add({"inputTokens": 1000, "outputTokens": 500, "totalTokens": 1500})
    totals.add({"inputTokens": 200, "outputTokens": 100, "cacheReadTokens": 50, "totalTokens": 350})
    assert totals.input_tokens == 1200
    assert totals.output_tokens == 600
    assert totals.cache_read_tokens == 50
    assert totals.total_tokens == 1850


def test_match_member_spend_by_email():
    members = [
        {"email": "alice@example.com", "spendCents": 100},
        {"email": "bob@example.com", "spendCents": 200},
    ]
    match = _match_member_spend(members, "bob@example.com")
    assert match["spendCents"] == 200


def test_match_member_spend_fallback():
    members = [{"email": "alice@example.com", "spendCents": 100}]
    match = _match_member_spend(members, None)
    assert match["spendCents"] == 100
