from app.redaction.engine import RedactionEngine


def test_redaction_engine_basic_redact_and_restore() -> None:
    engine = RedactionEngine()
    text = "Hello, my name is John Doe and my email is john.doe@example.com."
    redacted_text, redaction_map, pii_types = engine.redact_text(text)

    # Asserts that PII is no longer in text
    assert "john.doe@example.com" not in redacted_text
    assert "<EMAIL_ADDRESS_1>" in redacted_text or "<EMAIL_1>" in redacted_text
    assert len(redaction_map) >= 1
    assert "EMAIL_ADDRESS" in pii_types or "EMAIL" in pii_types

    # Restores text
    restored = engine.restore_text(redacted_text, redaction_map)
    assert "john.doe@example.com" in restored


def test_redaction_engine_same_value_same_placeholder() -> None:
    engine = RedactionEngine()
    text = "Send email to test@example.com or forward to test@example.com."
    redacted_text, redaction_map, _ = engine.redact_text(text)

    # Identical emails must map to the same placeholder
    assert len(redaction_map) == 1
    placeholder = list(redaction_map.keys())[0]
    assert redacted_text.count(placeholder) == 2


def test_redaction_disabled_leaves_text_intact() -> None:
    engine = RedactionEngine()
    text = "Call me at +251911223344."
    redacted, r_map, pii_types = engine.redact_messages(
        [{"role": "user", "content": text}], enabled=False
    )
    assert redacted[0]["content"] == text
    assert len(r_map) == 0
    assert len(pii_types) == 0
