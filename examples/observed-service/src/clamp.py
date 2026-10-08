def clamp(value: int, lower: int, upper: int) -> int:
    return max(lower, min(value, upper))
