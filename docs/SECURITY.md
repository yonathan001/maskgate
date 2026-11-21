# Maskgate Security & Privacy Specification

## Overview

Maskgate enforces strict privacy and compliance guarantees before any prompt leaves the gateway infrastructure.

```
Client Request (Raw PII)
       │
       ▼
[Redaction Engine] ──(Detects PII & maps to <TYPE_N>)──> Provider Request (Sanitized)
       │                                                         │
       │ (In-memory map only, discarded after request)           ▼
       │                                                 Provider Response (Placeholders)
       ▼                                                         │
[Stream / Text Restorer] <───────────────────────────────────────┘
       │
       ▼
Client Response (Restored Text)
```

---

## Supported PII Entities

| Entity Type | Detection Engine | Description | Examples |
| --- | --- | --- | --- |
| `EMAIL_ADDRESS` | Microsoft Presidio | Standard email address detection | `user@example.com` |
| `PHONE_NUMBER` | Presidio + Custom Regex | International & Ethiopian phone formats | `+251911223344`, `0911223344` |
| `PERSON` | Presidio Spacy NLP | Person names (probabilistic) | `Alice Smith`, `John Doe` |
| `CREDIT_CARD` | Presidio Checksum | Major credit card formats (Luhn check) | Visa, Mastercard, AMEX |
| `IBAN_CODE` | Presidio Checksum | International bank account numbers | Standard IBAN formats |
| `IP_ADDRESS` | Presidio Pattern | IPv4 and IPv6 network addresses | `192.168.1.1` |
| `NATIONAL_ID` | Custom Regex Pattern | Configurable ID formats | `ID-94829104` |

---

## Hard Rules & Verification

1. **No Raw PII Upstream:** Private values are replaced with `<TYPE_N>` placeholders prior to reaching external LLM providers (verified in `tests/privacy/test_privacy_zero_leak.py`).
2. **Zero-Persistence In-Memory Map:** The placeholder-to-original mapping exists exclusively in ephemeral memory during request execution and is never written to disk, PostgreSQL, Redis, or logs.
3. **No Raw Logging by Default:** Request logs and OpenTelemetry traces record metadata only (`pii_count`, `pii_types`, tokens, latency). `LOG_RAW_PAYLOADS=false` by default.
4. **Placeholder Restoration in Streams:** `StreamRestorer` buffers partial chunk boundaries (e.g. `<PER` + `SON_1>`) to prevent fragmented placeholder leaks, verified by split-at-every-position property tests.

---

## Known Limits & Gaps

- **Name Detection is Probabilistic:** Spacy NER detects names based on statistical models. Rare names, unconventional casing, or nicknames may occasionally pass through or cause false positives.
- **Syntactic Alteration by Model:** If an upstream LLM mutates a placeholder (e.g. transforms `<PERSON_1>` to `<person_1>` or drops brackets), exact restoration may miss.
