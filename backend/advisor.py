"""Design Advisor: Spark-proposed lighting settings, validated before use.

Rules that keep an advisor suggestion honest in this demo:
- Settings are combinations of the home's real lights, on or off only.
  The template lights support no brightness or colour, so the model
  must not invent those, and relocation stays a suggestion in prose,
  never an HA action.
- Only light.* entities from the live HA registry, only
  light.turn_on / light.turn_off, approval in the UI before any write.
  Declining a suggestion changes nothing.
- Every image preview is labelled illustrative in the UI: it is a
  mood preview, never a photometrically accurate simulation and never
  a promise that the room will look exactly like the picture.
"""

from __future__ import annotations

ALLOWED_ACTION_SERVICES = ("light.turn_on", "light.turn_off")

ADVISOR_SCHEMA = {
    "type": "object",
    "properties": {
        "settings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "actions": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "entity_id": {"type": "string"},
                                "service": {"type": "string",
                                            "enum": list(ALLOWED_ACTION_SERVICES)},
                            },
                            "required": ["entity_id", "service"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["name", "description", "actions"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["settings"],
    "additionalProperties": False,
}

ADVISOR_SYSTEM = (
    "You propose lighting settings for a room. Reply with JSON only, "
    "following the schema. Rules: propose exactly 2 settings; each "
    "setting uses only the light entities given, each with service "
    "light.turn_on or light.turn_off; do not invent entity IDs, "
    "brightness, colour, or other devices; do not move furniture — "
    "relocation, if mentioned at all, stays in the description text "
    "only and is never an action."
)


def build_advisor_prompt(light_ids: list[str], request_text: str) -> str:
    return (
        f"Available lights (on/off only): {', '.join(light_ids)}\n"
        f"Request: {request_text.strip() or 'cozy evening'}\n"
        "Propose exactly 2 feasible lighting settings for this request."
    )


def validate_settings(settings, registry: set[str]) -> list[str]:
    """Validate one or more settings. Returns reasons (empty = valid)."""
    reasons: list[str] = []
    if not isinstance(settings, list) or not settings:
        return ["At least one setting is required."]
    for setting in settings:
        if not isinstance(setting, dict):
            reasons.append("Each setting must be an object.")
            continue
        if not (setting.get("name") or "").strip():
            reasons.append("Each setting needs a name.")
        actions = setting.get("actions")
        if not isinstance(actions, list) or not actions:
            reasons.append(f"Setting '{setting.get('name', '')}' has no actions.")
            continue
        seen: set[str] = set()
        for action in actions:
            if not isinstance(action, dict):
                reasons.append("Each action must be an object.")
                continue
            ent = action.get("entity_id", "")
            if ent not in registry:
                reasons.append(f"Unknown light entity '{ent}' (not in this home).")
            elif not ent.startswith("light."):
                reasons.append(f"Action target '{ent}' is not a light.")
            if action.get("service") not in ALLOWED_ACTION_SERVICES:
                reasons.append(
                    f"Service '{action.get('service')}' is not allowed: only "
                    f"{' and '.join(ALLOWED_ACTION_SERVICES)}.")
            if ent in seen:
                reasons.append(f"Setting '{setting.get('name', '')}' lists '{ent}' twice.")
            seen.add(ent)
    return reasons


def validate_advisor_response(settings, registry: set[str]) -> list[str]:
    """Advisor responses must carry exactly 2 settings, both valid."""
    if not isinstance(settings, list) or len(settings) != 2:
        return ["Advisor must propose exactly 2 settings."]
    return validate_settings(settings, registry)


# Deterministic time-of-day presets. These are not model output: each
# variant maps to supported on/off actions only, validated the same way
# as advisor settings before any HA write.
TIME_OF_DAY_PRESETS = {
    "morning": {
        "label": "Morning",
        "description": "Daylight in the room; all lights off.",
        "image_prompt": (
            "The same room in bright morning daylight, sunlight through "
            "the window, all lamps off."),
        "actions": [
            {"entity_id": "light.floor_lamp", "service": "light.turn_off"},
            {"entity_id": "light.string_lights", "service": "light.turn_off"},
            {"entity_id": "light.reading_light", "service": "light.turn_off"},
        ],
    },
    "sunset": {
        "label": "Sunset",
        "description": "Warm evening glow: string lights and reading light on.",
        "image_prompt": (
            "The same room at sunset, warm string lights and a reading "
            "lamp glowing, soft evening light through the window."),
        "actions": [
            {"entity_id": "light.string_lights", "service": "light.turn_on"},
            {"entity_id": "light.reading_light", "service": "light.turn_on"},
            {"entity_id": "light.floor_lamp", "service": "light.turn_off"},
        ],
    },
    "night": {
        "label": "Night",
        "description": "Night reading: reading light on, everything else off.",
        "image_prompt": (
            "The same room at night, only a reading lamp on, the rest "
            "of the room dark."),
        "actions": [
            {"entity_id": "light.reading_light", "service": "light.turn_on"},
            {"entity_id": "light.floor_lamp", "service": "light.turn_off"},
            {"entity_id": "light.string_lights", "service": "light.turn_off"},
        ],
    },
}


def advisor_preview_prompt(setting: dict) -> str:
    on = [a["entity_id"].replace("light.", "").replace("_", " ")
          for a in setting.get("actions", [])
          if a.get("service") == "light.turn_on"]
    on_text = ", ".join(on) if on else "no lamps on"
    return (
        f"Illustrative cozy room interior for '{setting.get('name', '')}': "
        f"{setting.get('description', '')} Lamps on: {on_text}. "
        "Warm, lived-in evening mood, illustrative only.")
