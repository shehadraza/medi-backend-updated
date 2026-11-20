import pytest

from app.modules.ai.safety import (
    EMERGENCY_PATTERNS,
    DOSE_CHANGE_PATTERNS,
    DIAGNOSIS_PATTERNS,
    INTERACTION_PATTERNS,
)


@pytest.mark.parametrize("question", [
    "amar buk betha kortese",
    "buk e onek betha hocche",
    "shash nite koshto hocche",
    "amar shash bondho hoye ashtese",
    "onek rokto portese",
])
def test_banglish_emergency_detection(question):
    assert EMERGENCY_PATTERNS.search(question)


@pytest.mark.parametrize("question", [
    "ei oshudh bondho korbo?",
    "dose komabo naki?",
    "ami ki double dose nite pari?",
    "oshudh ar khabo na",
    "prottek din na kheye ekdin por por khabo?",
])
def test_banglish_dose_change_detection(question):
    assert DOSE_CHANGE_PATTERNS.search(question)


@pytest.mark.parametrize("question", [
    "amar ki diabetes hoyeche?",
    "amar ki heart er kono rog ache?",
    "eta ki cancer er lokkhon?",
])
def test_banglish_diagnosis_detection(question):
    assert DIAGNOSIS_PATTERNS.search(question)


@pytest.mark.parametrize("question", [
    "duita oshudh eksathe khete parbo?",
    "ei medicine gula eksathe khele problem hobe?",
    "ei duita medicine er moddhe interaction ache?",
    "eksathe oshudh khele kono khoti hobe?",
])
def test_banglish_interaction_detection(question):
    assert INTERACTION_PATTERNS.search(question)
