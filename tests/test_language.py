"""Spoken language: found from the script, decides number spelling and ignored hesitations."""

from autocut import text


def test_detect_language():
    assert text.detect_language("La révolte en France n'est pas que politique, et elle est dans la rue.") == "fr"
    assert text.detect_language("The protests in France are not only political, and they are in the streets.") == "en"


def test_english_normalization():
    try:
        text.set_language("en")
        assert text.normalize("In 2019, 40% of them") == ["in", "two", "thousand", "and", "nineteen",
                                                         "forty", "percent", "of", "them"]
        assert "um" in text.FILLERS and "euh" not in text.FILLERS
    finally:
        text.set_language("fr")
    assert text.normalize("40%") == ["quarante", "pour", "cent"]
    assert "euh" in text.FILLERS
