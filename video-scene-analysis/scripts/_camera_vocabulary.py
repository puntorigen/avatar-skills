"""Camera angle slugs aligned with avatar pipeline (e.g. lolo/angles/prompts/)."""

# Primary `camera.angle` values — English snake_case pipeline IDs.
CAMERA_ANGLE_IDS = (
    "eye_level",
    "low_angle",
    "low_angle_v2",
    "high_angle",
    "three_quarter",
    "dutch_tilt",
    "negative_space",
    "pull_out",
    "zoom_in",
    "none",
)

CAMERA_ANGLE_LABELS_ES = {
    "eye_level": "Frontal nivel de ojos (baseline)",
    "low_angle": "Contrapicado leve (~16°)",
    "low_angle_v2": "Contrapicado pronunciado (variante v2)",
    "high_angle": "Picado",
    "three_quarter": "Tres cuartos (~30°)",
    "dutch_tilt": "Inclinación holandesa",
    "negative_space": "Sujeto desplazado con espacio libre para captions",
    "pull_out": "Alejamiento / plano más abierto",
    "zoom_in": "Acercamiento / plano más cerrado",
    "none": "Sin ángulo de pipeline (B-roll u otro inserto)",
}

CAMERA_FRAMINGS = {
    "extreme_close_up": "Primerísimo primer plano",
    "close_up": "Primer plano",
    "medium_close_up": "Plano medio corto",
    "medium_shot": "Plano medio",
    "medium_wide": "Plano americano",
    "wide_shot": "Plano general",
    "unknown": "Sin clasificar",
}
