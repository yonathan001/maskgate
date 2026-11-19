from decimal import Decimal

from app.core.cost import calculate_cost


def test_calculate_cost_exact_values() -> None:
    # 1000 prompt tokens @ $0.00015/1k, 2000 completion tokens @ $0.0006/1k
    cost = calculate_cost(
        prompt_tokens=1000,
        completion_tokens=2000,
        price_input_per_1k=Decimal("0.00015"),
        price_output_per_1k=Decimal("0.0006"),
    )
    assert cost == Decimal("0.001350")


def test_calculate_cost_zero_tokens() -> None:
    cost = calculate_cost(
        prompt_tokens=0,
        completion_tokens=0,
        price_input_per_1k=Decimal("0.0015"),
        price_output_per_1k=Decimal("0.002"),
    )
    assert cost == Decimal("0.000000")


def test_calculate_cost_fractional_tokens() -> None:
    # 333 tokens @ 0.0015/1k = 0.0004995, 667 tokens @ 0.003/1k = 0.002001
    # total = 0.0025005 -> rounds to 0.002501
    cost = calculate_cost(
        prompt_tokens=333,
        completion_tokens=667,
        price_input_per_1k=Decimal("0.0015"),
        price_output_per_1k=Decimal("0.003"),
    )
    assert cost == Decimal("0.002501")
