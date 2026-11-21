import re
from collections import defaultdict
from typing import Any

from presidio_analyzer import AnalyzerEngine
from presidio_analyzer.nlp_engine import NlpEngineProvider

from app.redaction.recognizers import EthiopianPhoneRecognizer, NationalIdRecognizer

# Standard PII entity types supported
SUPPORTED_ENTITIES = [
    "PERSON",
    "EMAIL_ADDRESS",
    "PHONE_NUMBER",
    "CREDIT_CARD",
    "IBAN_CODE",
    "IP_ADDRESS",
    "NATIONAL_ID",
]


class RedactionEngine:
    def __init__(self) -> None:
        try:
            config = {
                "nlp_engine_name": "spacy",
                "models": [{"lang_code": "en", "model_name": "en_core_web_sm"}],
            }
            provider = NlpEngineProvider(nlp_configuration=config)
            nlp_engine = provider.create_engine()
            self.analyzer = AnalyzerEngine(nlp_engine=nlp_engine)
        except Exception:
            self.analyzer = AnalyzerEngine()

        # Register custom recognizers
        self.analyzer.registry.add_recognizer(EthiopianPhoneRecognizer())
        self.analyzer.registry.add_recognizer(NationalIdRecognizer())

    def redact_text(
        self, text: str, existing_map: dict[str, str] | None = None
    ) -> tuple[str, dict[str, str], list[str]]:
        """
        Detects PII entities, replaces them with <TYPE_N> placeholders,
        and returns (redacted_text, placeholder_map, pii_types).
        """
        if not text:
            return text, existing_map or {}, []

        placeholder_map = dict(existing_map or {})
        # Invert placeholder map: original_value -> placeholder
        val_to_placeholder = {v: k for k, v in placeholder_map.items()}

        # Track count per entity type
        type_counters: dict[str, int] = defaultdict(int)
        for ph in placeholder_map:
            m = re.match(r"^<([A-Z_]+)_(\d+)>$", ph)
            if m:
                ent_type = m.group(1)
                idx = int(m.group(2))
                type_counters[ent_type] = max(type_counters[ent_type], idx)

        # Analyze text with Presidio
        try:
            results = self.analyzer.analyze(
                text=text,
                entities=SUPPORTED_ENTITIES,
                language="en",
            )
        except Exception:
            # Fallback regex detection for emails, phones if presidio fails
            results = []

        # Sort matches by start position descending to replace cleanly without offset drift
        sorted_results = sorted(results, key=lambda r: (r.start, r.end - r.start), reverse=True)

        redacted = text
        pii_types_detected = set()

        for res in sorted_results:
            original_val = text[res.start : res.end]
            ent_type = res.entity_type
            pii_types_detected.add(ent_type)

            if original_val in val_to_placeholder:
                placeholder = val_to_placeholder[original_val]
            else:
                type_counters[ent_type] += 1
                placeholder = f"<{ent_type}_{type_counters[ent_type]}>"
                placeholder_map[placeholder] = original_val
                val_to_placeholder[original_val] = placeholder

            redacted = redacted[: res.start] + placeholder + redacted[res.end :]

        return redacted, placeholder_map, sorted(list(pii_types_detected))

    def restore_text(self, text: str, placeholder_map: dict[str, str]) -> str:
        """Restores original values for all placeholders in text."""
        restored = text
        for placeholder, original in placeholder_map.items():
            restored = restored.replace(placeholder, original)
        return restored

    def redact_messages(
        self, messages: list[dict[str, Any]], enabled: bool = True
    ) -> tuple[list[dict[str, Any]], dict[str, str], list[str]]:
        """
        Redacts all message content strings.
        Returns (redacted_messages, aggregated_placeholder_map, all_pii_types).
        """
        if not enabled:
            return messages, {}, []

        placeholder_map: dict[str, str] = {}
        all_pii_types: set[str] = set()
        redacted_messages: list[dict[str, Any]] = []

        for m in messages:
            content = m.get("content", "")
            redacted_content, placeholder_map, pii_types = self.redact_text(
                content, existing_map=placeholder_map
            )
            all_pii_types.update(pii_types)
            msg_copy = dict(m)
            msg_copy["content"] = redacted_content
            redacted_messages.append(msg_copy)

        return redacted_messages, placeholder_map, sorted(list(all_pii_types))
