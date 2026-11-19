from decimal import ROUND_HALF_UP, Decimal


def calculate_cost(
    prompt_tokens: int,
    completion_tokens: int,
    price_input_per_1k: Decimal,
    price_output_per_1k: Decimal,
) -> Decimal:
    """
    Computes request cost in USD from token counts and prices per 1k tokens.
    Returns Decimal with 6 decimal places.
    """
    input_cost = (Decimal(prompt_tokens) / Decimal(1000)) * price_input_per_1k
    output_cost = (Decimal(completion_tokens) / Decimal(1000)) * price_output_per_1k
    total = input_cost + output_cost
    return total.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
