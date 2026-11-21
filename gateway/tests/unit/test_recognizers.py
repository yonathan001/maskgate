from app.redaction.recognizers import EthiopianPhoneRecognizer, NationalIdRecognizer


def test_ethiopian_phone_recognizer_matches() -> None:
    rec = EthiopianPhoneRecognizer()

    valid_numbers = [
        "+251 911 223 344",
        "+251911223344",
        "0911223344",
        "0911 22 33 44",
        "+251 712 345 678",
        "0712345678",
        "+251-911-22-33-44",
    ]

    for num in valid_numbers:
        text = f"Contact me at {num} today"
        results = rec.analyze(text=text, entities=["PHONE_NUMBER"])
        assert len(results) > 0, f"Expected match for {num}"
        matched_text = text[results[0].start : results[0].end]
        clean_num = num.replace(" ", "").replace("-", "")
        clean_match = matched_text.replace(" ", "").replace("-", "")
        assert clean_num in clean_match


def test_ethiopian_phone_recognizer_negatives() -> None:
    rec = EthiopianPhoneRecognizer()
    invalid_numbers = [
        "12345678",
        "0811223344",
        "911223344",
        "random letters",
    ]
    for inv in invalid_numbers:
        text = f"Invalid: {inv}"
        results = rec.analyze(text=text, entities=["PHONE_NUMBER"])
        assert len(results) == 0


def test_national_id_recognizer() -> None:
    rec = NationalIdRecognizer()
    text = "User ID is ID-847291048."
    results = rec.analyze(text=text, entities=["NATIONAL_ID"])
    assert len(results) == 1
    assert text[results[0].start : results[0].end] == "ID-847291048"
