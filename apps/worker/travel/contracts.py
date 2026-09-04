"""The shapes travel reasoning passes around.

Small on purpose: two dataclasses and an enum's worth of string constants. The
point is that a resolved place carries *why* it was chosen and what it beat, so
a wrong answer can be explained after the fact instead of guessed at. Prose is
never the carrier of facts.
"""
from dataclasses import dataclass, field


# ResolvedPlace.state. Kept distinct because collapsing them is what produced
# "there's a limitation with the public transport data" when the truth was
# "I looked up the wrong Newtown".
RESOLVED = "resolved"
AMBIGUOUS = "ambiguous"       # several candidates, no way to choose between them
IMPLAUSIBLE = "implausible"   # found something, and it cannot be what was meant
NOT_FOUND = "not_found"       # the provider knows no such place


@dataclass
class PlaceCandidate:
    """One thing the provider offered when asked about a name."""
    name: str
    lat: float
    lng: float
    kind: str = ""                       # EFA `type`: stop | poi | address | …
    quality: int | None = None           # EFA `matchQuality`, higher is better
    is_best: bool = False                # EFA `isBest`
    distance_km: float | None = None     # from the origin, when there is one

    def as_coords(self) -> tuple:
        return (self.lat, self.lng)


@dataclass
class ResolvedPlace:
    """What "Newtown" turned out to mean, and what else it could have meant."""
    requested: str
    state: str
    source: str = ""                     # coords | saved_place | provider
    selected: PlaceCandidate | None = None
    alternatives: list = field(default_factory=list)
    reason: str = ""                     # shown to the user when it failed

    @property
    def ok(self) -> bool:
        return self.state == RESOLVED and self.selected is not None

    def coords(self):
        return self.selected.as_coords() if self.selected else None
