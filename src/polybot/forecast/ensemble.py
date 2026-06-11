"""GFS/ECMWF ensemble members — the uncertainty signal.

The edge mechanism is model-vs-stale-price: hourly-updating ensembles
shift probability between temperature buckets faster than thin books
reprice. Member spread gives us the distribution width that a point
forecast alone can't.

Candidate free sources (pick in phase 2): NOMADS (GFS ensemble),
open-meteo ensemble API (GFS + ECMWF members, simplest to start).
"""


def get_ensemble_members(lat: float, lon: float, date: str) -> list[float]:
    """Return predicted daily-high temps (one per ensemble member).

    TODO(phase 2): fetch members, extract daily max for the target
    date in the station's local timezone.
    """
    raise NotImplementedError
