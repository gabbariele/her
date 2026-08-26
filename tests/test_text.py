from her.text import clean_for_tts, iter_sentences, split_sentences


def test_clean_removes_markdown():
    assert clean_for_tts("**ciao** _mondo_ `x`") == "ciao mondo x"
    assert clean_for_tts("prima ```print(1)``` dopo") == "prima dopo"


def test_streaming_splits_on_sentence_end():
    tokens = ["Ciao", "! ", "Sono ", "il tuo ", "ospite, ", "oggi parliamo di radio. ", "Poi vediamo."]
    out = list(iter_sentences(tokens, min_chars=20))
    assert out[0] == "Ciao! Sono il tuo ospite, oggi parliamo di radio."
    assert out[-1] == "Poi vediamo."


def test_decimal_numbers_do_not_split():
    out = split_sentences("Il valore e 3.14 e non cambia mai piu di tanto.", min_chars=10)
    assert out == ["Il valore e 3.14 e non cambia mai piu di tanto."]


def test_short_fragments_are_merged():
    out = list(iter_sentences(["Si. ", "Certo. ", "Pero il punto e un altro, davvero."], min_chars=40))
    assert len(out) == 1


def test_nothing_is_lost():
    tokens = ["a" * 10, ". ", "b" * 10, "! ", "coda senza punto"]
    joined = " ".join(list(iter_sentences(tokens, min_chars=5)))
    for piece in ("a" * 10, "b" * 10, "coda senza punto"):
        assert piece in joined
