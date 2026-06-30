import re
from typing import Any, Dict, List


def analyze_strategy_code_quality(code: str) -> List[Dict[str, Any]]:
    hints: List[Dict[str, Any]] = []
    raw = (code or "").strip()
    if not raw:
        return [{"severity": "error", "code": "EMPTY_CODE", "params": {}}]

    has_on_init = bool(re.search(r"^\s*def\s+on_init\s*\(", raw, re.MULTILINE))
    has_on_bar = bool(re.search(r"^\s*def\s+on_bar\s*\(", raw, re.MULTILINE))
    has_ctx_param = bool(re.search(r"\bctx\.param\s*\(", raw))
    has_order_intent = bool(
        re.search(
            r"\bctx\.(buy|sell|close_position|open_long|add_long|close_long|open_short|add_short|close_short|basket)\s*\(",
            raw,
        )
    )

    if not has_on_init:
        hints.append({"severity": "warn", "code": "MISSING_ON_INIT", "params": {}})
    if not has_on_bar:
        hints.append({"severity": "error", "code": "MISSING_ON_BAR", "params": {}})
    if not has_ctx_param:
        hints.append({"severity": "info", "code": "NO_CTX_PARAM_DEFAULTS", "params": {}})
    if not has_order_intent:
        hints.append({"severity": "info", "code": "NO_ORDER_INTENT", "params": {}})
    return hints


def validate_strategy_code(code: str) -> Dict[str, Any]:
    from app.services.strategy_script_runtime import compile_strategy_script_handlers

    raw = (code or "").strip()
    hints = analyze_strategy_code_quality(raw)
    if not raw:
        return {
            "success": False,
            "message": "Code is empty",
            "error_type": "EmptyCode",
            "details": None,
            "hints": hints,
        }

    try:
        compile(raw, "<strategy>", "exec")
    except SyntaxError as se:
        return {
            "success": False,
            "message": f"Syntax error at line {se.lineno}: {se.msg}",
            "error_type": "SyntaxError",
            "details": str(se),
            "hints": hints,
        }

    required_funcs = ["on_bar", "on_init"]
    found = [func for func in required_funcs if f"def {func}" in raw]
    missing = [func for func in required_funcs if func not in found]
    if missing:
        return {
            "success": False,
            "message": f"Missing required functions: {', '.join(missing)}",
            "error_type": "MissingFunctions",
            "details": None,
            "hints": hints,
        }

    try:
        compile_strategy_script_handlers(raw)
    except Exception as exc:
        return {
            "success": False,
            "message": f"Runtime Error: {exc}",
            "error_type": "RuntimeError",
            "details": str(exc),
            "hints": hints,
        }

    return {
        "success": True,
        "message": "Code verification passed",
        "error_type": None,
        "details": None,
        "hints": hints,
    }


def strategy_debug_summary(validation: Dict[str, Any] | None = None) -> Dict[str, Any]:
    validation = validation or {}
    hints = validation.get("hints") or []
    return {
        "success": bool(validation.get("success")),
        "message": validation.get("message"),
        "error_type": validation.get("error_type"),
        "hint_codes": [hint.get("code") for hint in hints if hint.get("code")],
        "hint_count": len(hints),
    }


def strategy_ai_text(key: str, lang: str = "zh-CN") -> str:
    texts = {
        "prompt_empty": "Prompt cannot be empty",
        "no_llm_key": "No LLM API key configured",
        "insufficient_credits": "Insufficient credits. Please top up and try again.",
        "invalid_json_params": "AI did not return valid JSON parameters",
        "ai_empty_result": "AI generation returned empty result",
        "success": "success",
    }
    return texts.get(key, key)


def strategy_hint_to_text(hint_code: str, params: Dict[str, Any] | None = None, lang: str = "zh-CN") -> str:
    texts = {
        "MISSING_ON_INIT": "Missing on_init(ctx) function.",
        "MISSING_ON_BAR": "Missing on_bar(ctx, bar) function.",
        "NO_CTX_PARAM_DEFAULTS": "No parameter defaults were declared via ctx.param(...).",
        "NO_ORDER_INTENT": "No order intent like ctx.buy / ctx.sell / ctx.basket / ctx.close_position was detected.",
        "EMPTY_CODE": "Strategy code is empty.",
    }
    return texts.get(hint_code, f"Strategy hint detected: {hint_code}")


def strategy_human_summary(
    initial_validation: Dict[str, Any],
    final_validation: Dict[str, Any],
    auto_fix_applied: bool,
    auto_fix_succeeded: bool,
    returned_candidate: str,
    lang: str = "zh-CN",
) -> Dict[str, Any]:
    initial_hints = initial_validation.get("hints") or []
    final_hints = final_validation.get("hints") or []
    initial_codes = {hint.get("code") for hint in initial_hints if hint.get("code")}
    final_codes = {hint.get("code") for hint in final_hints if hint.get("code")}
    fixed_codes = sorted(initial_codes - final_codes)
    remaining_codes = sorted(final_codes)

    fixed_messages = [
        strategy_hint_to_text(hint.get("code"), hint.get("params"), lang=lang)
        for hint in initial_hints
        if hint.get("code") in fixed_codes
    ]
    remaining_messages = [
        strategy_hint_to_text(hint.get("code"), hint.get("params"), lang=lang)
        for hint in final_hints
        if hint.get("code") in remaining_codes
    ]

    if auto_fix_applied and auto_fix_succeeded:
        title = "AI auto-fixed the strategy code and returned a more stable version"
    elif auto_fix_applied:
        title = "AI attempted to auto-fix the strategy code, but some issues still remain"
    else:
        title = "AI generated strategy code and it passed the current QA flow"

    returned_text = (
        "The returned code is the auto-fixed version."
        if returned_candidate == "repaired"
        else "The returned code is the initially generated version."
    )

    return {
        "title": title,
        "returned_text": returned_text,
        "fixed_messages": fixed_messages,
        "remaining_messages": remaining_messages,
    }
