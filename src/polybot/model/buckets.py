"""Temperature-bucket probability distributions.

Same shape as PropEdge's quantile models: forecast inputs -> fair
probability per market bucket -> compare to market price.
"""


def bucket_probabilities(
    members: list[float], buckets: list[tuple[float, float]]
) -> list[float]:
    """Map ensemble members onto market temperature buckets.

    TODO(phase 2): start with empirical member counts per bucket
    (plus smoothing for tail buckets with zero members); consider a
    fitted skew-normal later. Must sum to 1 across the full ladder.
    """
    raise NotImplementedError


def bias_correction(station: str) -> float:
    """Historical model-vs-observation bias for a station.

    TODO(phase 2/3): compute from past forecasts vs resolved values
    once we have logged data. Return 0.0 until then.
    """
    return 0.0
