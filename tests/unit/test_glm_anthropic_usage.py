import pytest

from app.usage.normalization import normalize_usage


def test_glm_anthropic_cache_tokens_are_additive():
    observed = normalize_usage('glm', dict(wire_protocol='anthropic', input_tokens=10, output_tokens=5,
        cache_read_input_tokens=20, cache_creation_input_tokens=30))
    assert observed['total_tokens'] == 65
    assert observed['components']['cache_read_input_tokens'] == 20
    assert observed['components']['cache_creation_input_tokens'] == 30


def test_missing_anthropic_cache_counts_cannot_be_assumed_zero():
    observed = normalize_usage('glm', dict(wire_protocol='anthropic', input_tokens=10, output_tokens=5))
    assert observed['total_tokens'] is None and observed['source'] == 'unknown'


def test_anthropic_total_smaller_than_additive_components_is_rejected():
    with pytest.raises(ValueError):
        normalize_usage('glm', dict(wire_protocol='anthropic', input_tokens=10, output_tokens=5,
            cache_read_input_tokens=20, cache_creation_input_tokens=30, total_tokens=15))


def test_glm_openai_cache_details_remain_a_subset():
    observed = normalize_usage('glm', dict(input_tokens=30, output_tokens=5,
        input_tokens_details={'cached_tokens': 20}))
    assert observed['total_tokens'] == 35 and observed['components']['cached_tokens'] == 20
