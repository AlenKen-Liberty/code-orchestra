Number = int | float | complex


def add(a: Number, b: Number) -> Number:
    """Return the sum of two numbers.

    Args:
        a: First addend.
        b: Second addend.

    Returns:
        The sum of a and b.

    Raises:
        TypeError: If the operands do not support addition together.

    Example:
        >>> add(2, 3)
        5
        >>> add(-1, 0.5)
        -0.5
    """
    try:
        return a + b
    except TypeError as exc:
        raise TypeError("add() arguments must support addition") from exc
