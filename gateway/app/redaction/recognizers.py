from presidio_analyzer import Pattern, PatternRecognizer


class EthiopianPhoneRecognizer(PatternRecognizer):
    """
    Recognizes Ethiopian phone numbers:
    Formats:
      +251 9XX XXX XXX, +251 7XX XXX XXX
      +2519XXXXXXXX, +2517XXXXXXXX
      09XXXXXXXX, 07XXXXXXXX
      Variants with hyphens and spaces
    """

    PATTERNS = [
        Pattern(
            name="ethiopian_phone_international",
            regex=r"(?:\+251|00251)[\s-]?(?:9|7)[\s-]?(?:\d[\s-]?){8}\b",
            score=0.85,
        ),
        Pattern(
            name="ethiopian_phone_local",
            regex=r"\b0(?:9|7)[\s-]?(?:\d[\s-]?){8}\b",
            score=0.75,
        ),
    ]

    def __init__(self) -> None:
        super().__init__(
            supported_entity="PHONE_NUMBER",
            patterns=self.PATTERNS,
            name="EthiopianPhoneRecognizer",
        )


class NationalIdRecognizer(PatternRecognizer):
    """Recognizes generic national ID format patterns like ID-123456789."""

    PATTERNS = [
        Pattern(
            name="generic_national_id",
            regex=r"\bID-[A-Za-z0-9]{6,16}\b",
            score=0.80,
        ),
    ]

    def __init__(self) -> None:
        super().__init__(
            supported_entity="NATIONAL_ID",
            patterns=self.PATTERNS,
            name="NationalIdRecognizer",
        )
