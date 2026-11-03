"""Regression cases for tiny.en word omissions on long Shorts."""
import pytest

from backend.app.models import WordTiming
from backend.app.services.alignment import AlignmentError, match_script


SCRIPT = (
    "The cybersecurity chief issued a serious warning about the growing risk of attacks. "
    "We are talking about electricity grids water systems factories heating systems and "
    "supermarket refrigeration around the country. "
    "Governments and security engineers are preparing for autonomous threats to critical "
    "infrastructure while new safeguards are being deployed every day."
)


def recognized(text: str, step: float = 0.28) -> list[WordTiming]:
    return [
        WordTiming(word, 0.4 + i * step, 0.4 + i * step + 0.22)
        for i, word in enumerate(text.split())
    ]


def test_factories_asr_omission_has_bounded_local_timing():
    words = recognized(SCRIPT.replace(" factories ", " "))
    aligned = match_script(SCRIPT, words, 20)
    index = SCRIPT.split().index("factories")
    assert [word.text for word in aligned] == SCRIPT.split()
    assert words[index - 3].start <= aligned[index].start < aligned[index].end
    assert aligned[index].end <= words[index + 2].end


def test_two_exact_neighbors_can_recover_omission_near_other_asr_error():
    # Tiny.en can distort an adjacent word in addition to omitting one.
    transcribed = SCRIPT.replace("electricity grids water", "electricity grid water")
    transcribed = transcribed.replace(" factories ", " ")
    aligned = match_script(SCRIPT, recognized(transcribed), 20)
    assert [word.text for word in aligned] == SCRIPT.split()
    assert aligned[SCRIPT.split().index("factories")].end > aligned[SCRIPT.split().index("factories")].start


def test_omission_across_long_pause_is_not_invented():
    words = recognized(SCRIPT.replace(" factories ", " "))
    index = SCRIPT.split().index("factories")
    for word in words[index:]:
        word.start += 3.0
        word.end += 3.0
    with pytest.raises(AlignmentError, match="Script/audio mismatch"):
        match_script(SCRIPT, words, 25)


def test_compound_tokenization_without_omission_keeps_script_caption():
    script = SCRIPT.replace("cybersecurity", "cyber-security")
    aligned = match_script(script, recognized(SCRIPT), 20)
    assert [word.text for word in aligned] == script.split()


def test_repeated_phrase_is_not_accepted_as_new_speech():
    script = "Google just sent AI hardware into space. A prototype satellite reached orbit."
    spoken = (
        "Google just sent AI hardware into space. "
        "Google just sent AI hardware into space. "
        "A prototype satellite reached orbit."
    )
    aligned = match_script(script, recognized(spoken), 10)
    assert aligned[7].text == "A"
    assert aligned[7].start == pytest.approx(recognized(spoken)[14].start)
