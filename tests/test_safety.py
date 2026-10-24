"""Tes unit untuk aturan keselamatan yang tidak bergantung pada model."""
from safety import detect_red_flags, load_safety_config, red_flag_message


def test_red_flag_always_triggers_independently_of_model_output() -> None:
    cfg = load_safety_config()
    flags = detect_red_flags(selected_symptoms=[], explicit_red_flags=["chest_pain"], config=cfg)
    message = red_flag_message(flags, cfg)
    assert flags
    assert any(flag["id"] == "chest_pain" for flag in flags)
    assert "Jangan menunggu hasil model" in message or "jangan menunggu" in message.lower()


def test_red_flag_alias_in_symptom_selection() -> None:
    flags = detect_red_flags(selected_symptoms=["chest_pain"])
    assert any(flag["id"] == "chest_pain" for flag in flags)
