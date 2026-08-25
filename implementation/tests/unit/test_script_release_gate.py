import asyncio
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from omnicast.llm.deepseek import DeepSeekClient
from omnicast.llm.client import get_session_cost, record_cost, reset_session_cost
from omnicast.llm.json_utils import parse_json_payload
from omnicast.storage import products


def test_release_contract_blocks_needs_edit_and_allows_production_ready(tmp_path: Path):
    products.write_meta(
        tmp_path, release_gate_version=1, stage="needs_edit",
        script_approved=False, content_locked=False, production_ready=False,
    )
    assert set(products.release_issues(tmp_path)) == {
        "script_approved", "content_locked", "production_ready", "stage_needs_edit",
    }

    script = products.script_path(tmp_path)
    script.write_text("approved narration", encoding="utf-8")
    products.write_meta(
        tmp_path, stage="script", script_approved=True,
        content_locked=True, production_ready=True,
        script_sha256=hashlib.sha256(script.read_bytes()).hexdigest(),
    )
    assert products.release_issues(tmp_path) == []


def test_legacy_product_without_gate_version_remains_renderable(tmp_path: Path):
    products.write_meta(tmp_path, stage="script")
    assert products.release_issues(tmp_path) == []


def test_nested_variant_cannot_bypass_parent_product_release_contract(tmp_path: Path):
    product = tmp_path / "products" / "channel" / "run"
    variant = product / "variants" / "variant_writer_score90.txt"
    variant.parent.mkdir(parents=True)
    variant.write_text("unapproved narration", encoding="utf-8")
    canonical = products.script_path(product)
    canonical.write_text("approved narration", encoding="utf-8")
    products.write_meta(
        product, release_gate_version=1, stage="script", script_approved=True,
        content_locked=True, production_ready=True,
        script_sha256=hashlib.sha256(canonical.read_bytes()).hexdigest(),
    )

    assert products.product_dir_for_asset(variant) == product
    assert products.release_issues_for_script(variant) == ["noncanonical_script"]

    assert products.release_issues_for_script(canonical) == []


def test_editorial_override_is_bound_to_reviewed_script_and_storyboard_bytes(tmp_path: Path):
    script = products.script_path(tmp_path)
    storyboard = tmp_path / "script.json"
    script.write_text("reviewed narration", encoding="utf-8")
    storyboard.write_text('{"scenes": []}', encoding="utf-8")
    review = {
        "script_sha256": hashlib.sha256(script.read_bytes()).hexdigest(),
        "storyboard_sha256": hashlib.sha256(storyboard.read_bytes()).hexdigest(),
    }
    (tmp_path / "final_review.json").write_text(json.dumps(review), encoding="utf-8")
    products.write_meta(
        tmp_path, release_gate_version=1, stage="script", script_approved=True,
        content_locked=True, production_ready=True,
        release_basis="manual_editorial_override", final_review="final_review.json",
    )
    assert products.release_issues_for_script(script) == []

    script.write_text("changed after review", encoding="utf-8")
    assert products.release_issues_for_script(script) == ["script_review_hash_mismatch"]


def test_automated_release_is_bound_to_the_approved_script_bytes(tmp_path: Path):
    script = products.script_path(tmp_path)
    script.write_text("approved narration", encoding="utf-8")
    products.write_meta(
        tmp_path, release_gate_version=1, stage="script", script_approved=True,
        content_locked=True, production_ready=True,
        script_sha256=hashlib.sha256(script.read_bytes()).hexdigest(),
    )
    assert products.release_issues_for_script(script) == []

    script.write_text("mutated after approval", encoding="utf-8")
    assert products.release_issues_for_script(script) == ["script_release_hash_mismatch"]


def test_structured_json_parser_tolerates_short_preamble_and_trailer():
    assert parse_json_payload('Here is the result:\n{"score": 82}\nDone.') == {"score": 82}


@pytest.mark.asyncio
async def test_deepseek_disables_thinking_and_does_not_double_bill_cache_partition():
    usage = SimpleNamespace(
        prompt_tokens=1000,
        completion_tokens=100,
        prompt_cache_hit_tokens=200,
        prompt_cache_miss_tokens=800,
        completion_tokens_details=SimpleNamespace(reasoning_tokens=0),
    )
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="ok"), finish_reason="stop")],
        usage=usage,
    )
    api = SimpleNamespace(chat=SimpleNamespace(
        completions=SimpleNamespace(create=AsyncMock(return_value=response))
    ))
    client = DeepSeekClient("test", "deepseek-v4-pro")
    client._get_client = AsyncMock(return_value=api)

    result = await client.complete(system="judge", messages=[{"role": "user", "content": "x"}])

    kwargs = api.chat.completions.create.await_args.kwargs
    assert kwargs["extra_body"] == {"thinking": {"type": "disabled"}}
    assert result.cost_usd == pytest.approx(
        800 * 0.435 / 1_000_000
        + 200 * 0.003625 / 1_000_000
        + 100 * 0.87 / 1_000_000
    )


@pytest.mark.asyncio
async def test_deepseek_recovers_critic_dimensions_emitted_as_root_array():
    from omnicast.models.script import CriticFeedback
    from omnicast.llm import LLMResponse

    client = DeepSeekClient("test", "deepseek-v4-pro")
    client.complete = AsyncMock(return_value=LLMResponse(
        content=(
            '[{"name":"accuracy_trust","score":14,"max_score":16,'
            '"feedback":"grounded"},'
            '{"name":"visual_concreteness","score":18,"max_score":20,'
            '"feedback":"specific"}]'
        ),
        model="deepseek-v4-pro",
        input_tokens=10,
        output_tokens=10,
        cost_usd=0.0,
        stop_reason="stop",
    ))

    _, parsed = await client.complete_structured(
        system="judge",
        messages=[{"role": "user", "content": "review"}],
        output_schema=CriticFeedback,
    )

    assert parsed.total_score == 32
    assert [dimension.name for dimension in parsed.dimensions] == [
        "accuracy_trust", "visual_concreteness"]
    assert parsed.approved is False


@pytest.mark.asyncio
async def test_cost_accumulators_are_isolated_between_concurrent_jobs():
    async def job(model: str, amount: float) -> dict:
        reset_session_cost()
        await asyncio.sleep(0)
        record_cost(model, amount)
        await asyncio.sleep(0)
        return get_session_cost()

    first, second = await asyncio.gather(job("writer", 0.12), job("critic", 0.03))

    assert first == {"total": 0.12, "calls": 1, "by_model": {"writer": 0.12}}
    assert second == {"total": 0.03, "calls": 1, "by_model": {"critic": 0.03}}
