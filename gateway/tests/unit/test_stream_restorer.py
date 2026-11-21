from app.redaction.stream import StreamRestorer


def test_stream_restorer_split_at_every_position() -> None:
    original_text = "Contact <PERSON_1> at <EMAIL_1> or call <PHONE_1>."
    placeholders = {
        "<PERSON_1>": "Alice Smith",
        "<EMAIL_1>": "alice@example.com",
        "<PHONE_1>": "+251911223344",
    }
    expected_restored = "Contact Alice Smith at alice@example.com or call +251911223344."

    # Test splitting at every single index position [1 .. len(original_text) - 1]
    for split_idx in range(1, len(original_text)):
        chunk1 = original_text[:split_idx]
        chunk2 = original_text[split_idx:]

        restorer = StreamRestorer(placeholders)
        restored_parts = []

        out1 = restorer.feed(chunk1)
        if out1:
            restored_parts.append(out1)

        out2 = restorer.feed(chunk2)
        if out2:
            restored_parts.append(out2)

        out_final = restorer.flush()
        if out_final:
            restored_parts.append(out_final)

        full_restored = "".join(restored_parts)
        assert full_restored == expected_restored, (
            f"Failed at split index {split_idx}: '{full_restored}' != '{expected_restored}'"
        )


def test_stream_restorer_single_char_chunks() -> None:
    original_text = "Hello <PERSON_1>!"
    placeholders = {"<PERSON_1>": "Bob"}
    expected = "Hello Bob!"

    restorer = StreamRestorer(placeholders)
    restored_parts = []
    for ch in original_text:
        out = restorer.feed(ch)
        if out:
            restored_parts.append(out)
    final = restorer.flush()
    if final:
        restored_parts.append(final)

    assert "".join(restored_parts) == expected


def test_stream_restorer_placeholder_at_end() -> None:
    placeholders = {"<PERSON_1>": "Charlie"}
    expected = "The user is Charlie"

    restorer = StreamRestorer(placeholders)
    out1 = restorer.feed("The user is <PER")
    out2 = restorer.feed("SON_1>")
    out3 = restorer.flush()
    assert (out1 + out2 + out3) == expected
