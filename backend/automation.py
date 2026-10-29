"""AutomationIR: Spark intent -> deterministic HA automation (Day 4).

Pipeline: gesture (bound source/target regions) + typed text -> Muse Spark
structured output (AutomationIR) -> deterministic validator -> deterministic
compiler (allowlisted HA automation forms only). No LLM-generated YAML is
ever executed; the compiler emits only the three P0 templates.
"""

from __future__ import annotations

IR_SCHEMA = {
    "type": "object",
    "properties": {
        "trigger": {
            "type": "object",
            "properties": {
                "entity_id": {"type": "string"},
                "to": {"type": "string", "enum": ["on"]},
            },
            "required": ["entity_id", "to"],
            "additionalProperties": False,
        },
        "condition": {
            "type": ["object", "null"],
            "properties": {
                "sun": {"type": "string", "enum": ["after_sunset", "before_sunrise"]},
            },
            "required": ["sun"],
            "additionalProperties": False,
        },
        "action": {
            "type": "object",
            "properties": {
                "entity_id": {"type": "string"},
                "service": {"type": "string",
                            "enum": ["light.turn_on", "light.turn_off"]},
            },
            "required": ["entity_id", "service"],
            "additionalProperties": False,
        },
        "delay_s": {"type": "integer", "minimum": 0, "maximum": 3600},
        "description": {"type": "string"},
    },
    "required": ["trigger", "action", "delay_s", "description"],
    "additionalProperties": False,
}

IR_SYSTEM = (
    "You translate a smart-home gesture plus typed instruction into an "
    "AutomationIR JSON object. Reply with JSON only, following the schema. "
    "Rules: the trigger is ALWAYS the given source entity with to='on'; "
    "the action targets ALWAYS the given target entity with service "
    "light.turn_on (use light.turn_off only if the text asks to turn off); "
    "condition.sun is 'after_sunset' only if the text mentions sunset, "
    "evening, night, or dark, 'before_sunrise' only if it mentions sunrise "
    "or morning, else null; delay_s is seconds (1 minute = 60) only if the "
    "text asks for a delay or auto-off, else 0; never invent entity IDs, "
    "services, or conditions outside the schema."
)

# P0 safety allowlist (single source of truth for validator + compiler).
ALLOWED_TRIGGER = "binary_sensor.patio_door"
ALLOWED_ACTION_SERVICES = ("light.turn_on", "light.turn_off")


def validate_ir(ir: dict, registry: set[str]) -> list[str]:
    """Deterministic validation. Returns plain-language rejection reasons
    (empty = valid)."""
    reasons: list[str] = []
    trigger = ir.get("trigger") or {}
    action = ir.get("action") or {}
    condition = norm_condition(ir)
    delay = ir.get("delay_s", 0)

    tent = trigger.get("entity_id", "")
    if tent not in registry:
        reasons.append(f"Unknown trigger entity '{tent}' (not in this home).")
    elif tent != ALLOWED_TRIGGER:
        reasons.append(
            f"Trigger '{tent}' is outside the demo allowlist: only the patio "
            f"door may trigger automations.")
    if trigger.get("to") != "on":
        reasons.append("Trigger must be a door-open event (to='on').")

    aent = action.get("entity_id", "")
    if aent not in registry:
        reasons.append(f"Unknown action entity '{aent}' (not in this home).")
    elif not aent.startswith("light."):
        reasons.append(f"Action target '{aent}' is not a light.")
    if action.get("service") not in ALLOWED_ACTION_SERVICES:
        reasons.append(
            f"Service '{action.get('service')}' is not allowed: only "
            f"{' and '.join(ALLOWED_ACTION_SERVICES)}.")

    if condition is not None:
        if not isinstance(condition, dict) or condition.get("sun") not in (
                "after_sunset", "before_sunrise"):
            reasons.append(
                "Condition must be null or sun after sunset / before sunrise.")

    if not isinstance(delay, int) or not 0 <= delay <= 3600:
        reasons.append("Delay must be 0–3600 seconds.")
    return reasons


def apply_delay_override(ir: dict, delay_s: int | None) -> dict:
    """Deterministic delay override for the Automate dropdown.

    None means "use the model's text-derived delay". An explicit value
    replaces it before validation, so the delay beat does not depend on
    Spark parsing "off after a minute" correctly. The compiled form is
    unchanged: turn_on, delay, turn_off (pattern 3).
    """
    if delay_s is None:
        return ir
    if isinstance(delay_s, bool) or not isinstance(delay_s, int) \
            or not 0 <= delay_s <= 3600:
        raise ValueError("Delay must be 0–3600 seconds.")
    out = dict(ir)
    out["delay_s"] = delay_s
    return out


def norm_condition(ir: dict) -> dict | None:
    """Explicit null sun counts as absent (models often emit it)."""
    condition = ir.get("condition")
    if isinstance(condition, dict) and condition.get("sun") is None:
        return None
    return condition


def compile_ir(ir: dict, alias: str) -> dict:
    """Deterministic compile to an HA automation config. Only the three P0
    templates; assumes validate_ir passed."""
    automation: dict = {
        "alias": alias,
        "trigger": [{"platform": "state",
                     "entity_id": ir["trigger"]["entity_id"],
                     "to": ir["trigger"]["to"]}],
        "action": [{"service": ir["action"]["service"],
                    "target": {"entity_id": ir["action"]["entity_id"]}}],
    }
    condition = norm_condition(ir)
    if condition:
        sun = condition["sun"]
        automation["condition"] = (
            [{"condition": "sun", "after": "sunset"}]
            if sun == "after_sunset"
            else [{"condition": "sun", "before": "sunrise"}]
        )
    delay = ir.get("delay_s", 0)
    if delay:
        h, rem = divmod(delay, 3600)
        m, s = divmod(rem, 60)
        automation["action"].append({"delay": f"{h:02d}:{m:02d}:{s:02d}"})
        if ir["action"]["service"] == "light.turn_on":
            automation["action"].append(
                {"service": "light.turn_off",
                 "target": {"entity_id": ir["action"]["entity_id"]}})
    return automation


def build_ir_prompt(source_entity: str, target_entity: str, text: str) -> str:
    return (f"Source (trigger): {source_entity}\n"
            f"Target (action): {target_entity}\n"
            f"Instruction: {text.strip() or '(no text — use the gesture alone)'}\n"
            f"Describe the automation in AutomationIR.")
