import re
from pathlib import Path

import pytest

from app.services.ai_generation_contracts import (
    STRATEGY_INSTRUMENT_IDENTITY_CONTRACT,
    SCRIPT_STRATEGY_QUICK_TOOL_SYSTEM_PROMPT,
    SCRIPT_STRATEGY_REPAIR_REQUIREMENTS,
)
from app.services.ai_skill_registry import get_skill
from app.services.strategy_ai_generation import build_strategy_system_prompt, validate_generated_strategy
from app.services.strategy_authoring import get_strategy_authoring_contract
from app.services.strategy_v2 import compile_strategy_v2, StrategyV2ContractError
from app.services.strategy_v2.instruments import parse_instrument


INSTRUMENT = "Crypto:00700/HKD@gate:spot"
APPLE = "Crypto:AAPL/USD@gate:spot"
BINANCE_HK_SWAP = "Crypto:HK0700/USDT@binance:swap"


@pytest.mark.parametrize("mode,asset", [("authoring", "script"), ("authoring", "portfolio_strategy"), ("indicator_conversion", "script")])
@pytest.mark.parametrize("canonical,symbol", [(INSTRUMENT, "00700/HKD"), (APPLE, "AAPL/USD")])
def test_all_strategy_generation_modes_preserve_gate_stock_identity(mode, asset, canonical, symbol):
    system, intent = build_strategy_system_prompt(
        prompt="Create a moving-average strategy", asset_type=asset, generation_mode=mode,
        context={"source": "indicator_ide_conversion", "conversionRequest": "", "instrument": canonical},
    )
    assert STRATEGY_INSTRUMENT_IDENTITY_CONTRACT in system
    assert "crypto_swap" not in intent.capabilities
    instrument = parse_instrument(canonical)
    assert (instrument.key, instrument.symbol, instrument.exchange_id, instrument.market_type) == (
        canonical, symbol, "gate", "spot",
    )


def test_quick_tool_repair_copilot_and_agent_share_instrument_rules():
    for prompt in (SCRIPT_STRATEGY_QUICK_TOOL_SYSTEM_PROMPT, SCRIPT_STRATEGY_REPAIR_REQUIREMENTS,
                   get_skill("script_strategy").system_instruction):
        assert STRATEGY_INSTRUMENT_IDENTITY_CONTRACT in prompt
    contract = get_strategy_authoring_contract()
    assert STRATEGY_INSTRUMENT_IDENTITY_CONTRACT in contract["system_contract"]
    example = contract["instrument_identity"]["examples"][0]
    assert example["instrument"] == INSTRUMENT
    assert (example["product_type"], example["api_family"], example["underlying_market"]) == (
        "direct_equity", "stock", "HKStock",
    )
    apple = contract["instrument_identity"]["examples"][1]
    assert (apple["instrument"], apple["symbol"], apple["underlying_market"], apple["underlying_symbol"]) == (
        APPLE, "AAPL/USD", "USStock", "AAPL",
    )
    binance_hk = contract["instrument_identity"]["examples"][2]
    assert (
        binance_hk["instrument"],
        binance_hk["product_type"],
        binance_hk["api_family"],
        binance_hk["underlying_market"],
        binance_hk["underlying_symbol"],
        binance_hk["direct_share_ownership"],
    ) == (BINANCE_HK_SWAP, "stock_perpetual", "swap", "HKStock", "00700", False)
    filters = contract["instrument_identity"]["discovery_filters"]
    assert filters["required"] == ["exchange_id", "market_type", "product_type"]
    assert filters["gate_direct_equity"] == {
        "exchange_id": "gate", "market_type": "spot", "product_type": "direct_equity",
        "search_examples": ["00700", "AAPL"],
    }
    assert filters["binance_hk_equity_perpetual"]["product_type"] == "stock_perpetual"
    assert filters["binance_bstock"] == {
        "exchange_id": "binance", "market_type": "spot", "product_type": "tokenized_equity",
        "search_examples": ["NVDAB", "AAPLB"],
    }
    matrix = contract["instrument_identity"]["venue_capabilities"]
    assert {item["product_type"] for item in matrix["binance"]} == {"tokenized_equity", "stock_perpetual"}
    assert {item["api_family"] for item in matrix["bitget"]} == {"reality", "swap"}
    assert matrix["htx"] == []


def test_all_strategy_prompts_share_exchange_equity_product_matrix():
    for prompt in (
        STRATEGY_INSTRUMENT_IDENTITY_CONTRACT,
        SCRIPT_STRATEGY_QUICK_TOOL_SYSTEM_PROMPT,
        SCRIPT_STRATEGY_REPAIR_REQUIREMENTS,
        get_skill("script_strategy").system_instruction,
        get_strategy_authoring_contract()["system_contract"],
    ):
        assert BINANCE_HK_SWAP in prompt
        assert "tokenized_equity/spot/reality" in prompt
        assert "HTX equity products remain disabled" in prompt
        assert "point-in-time fundamentals" in prompt
        assert "Do not combine HKD Gate direct equities" in prompt


def test_indicator_conversion_preserves_binance_hk_equity_perpetual_contract():
    system, intent = build_strategy_system_prompt(
        prompt="Convert the golden cross indicator to a long-only strategy",
        asset_type="script",
        generation_mode="indicator_conversion",
        context={
            "source": "indicator_ide_conversion",
            "instrument": BINANCE_HK_SWAP,
            "timeframe": "1d",
        },
    )
    assert BINANCE_HK_SWAP in system
    assert "crypto_swap" in intent.capabilities
    code = f'''"""Binance Hong Kong Equity Perpetual Cross
Preserves the selected catalog contract and trades its long hedge leg.
"""

def initialize(context):
    g.symbol = "{BINANCE_HK_SWAP}"
    context.set_universe([g.symbol])
    context.subscribe(frequency="1d")
    context.set_warmup(22)
    context.set_metadata(direction_mode="long_only")

def handle_data(context, data):
    bars = get_history(21, "1d", "close", g.symbol)
    if len(bars) < 20:
        return
    bullish = float(bars["close"].iloc[-1]) > float(bars["close"].tail(20).mean())
    position = get_position(g.symbol, position_side="long")
    order_target_percent(
        g.symbol,
        0.2 if bullish else 0.0,
        position_side="long",
        reason="binance_hk_equity_perpetual_cross",
    )
'''
    program = validate_generated_strategy(
        code,
        asset_type="script",
        generation_mode="indicator_conversion",
        context={"instrument": BINANCE_HK_SWAP, "timeframe": "1d"},
        prompt="Convert the golden cross indicator to a long-only strategy",
        intent=intent,
    )
    instrument = program.manifest.universe.instruments[0]
    assert (instrument.key, instrument.exchange_id, instrument.market_type) == (
        BINANCE_HK_SWAP,
        "binance",
        "swap",
    )


@pytest.mark.parametrize("filename", ["STRATEGY_DEV_GUIDE.md", "STRATEGY_DEV_GUIDE_CN.md"])
@pytest.mark.parametrize("canonical,invalid", [
    (INSTRUMENT, ("HKStock:00700.HK", "Crypto:00700/USDT@gate:spot", "Crypto:700/HKD@gate:spot")),
    (APPLE, ("USStock:AAPL", "Crypto:AAPL/USDT@gate:spot", "Crypto:AAPL/USD@binance:spot")),
])
def test_gate_equity_documentation_example_compiles_and_rejects_identity_changes(filename, canonical, invalid):
    guide = Path(__file__).parents[2] / "docs/trading" / filename
    documentation = guide.read_text(encoding="utf-8")
    assert canonical in documentation
    assert "Direct Equity" in documentation
    snippets = re.findall(r"~~~python\n(.*?)\n~~~", documentation, re.S)
    code = next(block for block in snippets if INSTRUMENT in block and "def initialize" in block)
    code = code.replace(INSTRUMENT, canonical)
    context = {"instrument": canonical, "timeframe": "1d"}
    program = validate_generated_strategy(code, asset_type="script", generation_mode="indicator_conversion", context=context)
    assert program.manifest.universe.instruments[0].key == canonical
    assert program.manifest.direction_mode == "long_only"
    assert not program.manifest.leverage_allowed
    for changed in invalid:
        with pytest.raises(StrategyV2ContractError, match="aiInstrumentMismatch"):
            validate_generated_strategy(code.replace(canonical, changed), asset_type="script", context=context)
    with pytest.raises(StrategyV2ContractError, match="leverageCryptoSwapOnly"):
        compile_strategy_v2(code.replace('context.set_warmup(30)', 'context.set_warmup(30)\n    context.allow_leverage(max_leverage=2)'))


@pytest.mark.parametrize("filename", [
    "STRATEGY_DEV_GUIDE.md",
    "STRATEGY_DEV_GUIDE_CN.md",
    "INDICATOR_DEV_GUIDE.md",
    "INDICATOR_DEV_GUIDE_CN.md",
])
def test_strategy_and_indicator_guides_cover_exchange_equity_identity(filename):
    guide = Path(__file__).parents[2] / "docs/trading" / filename
    documentation = guide.read_text(encoding="utf-8")
    assert INSTRUMENT in documentation
    assert BINANCE_HK_SWAP in documentation
    assert any(term in documentation for term in ("product_type", "product type", "产品类型"))
    assert "API family" in documentation
