"""Turning what the user said into one place on the map, or an honest failure.

The bug this replaces took the FIRST candidate with a parseable coordinate,
whatever it was. "Sans Souci" resolved near Narrabri, 500 km away, and produced
a 1953-minute itinerary via Werris Creek. "Newtown" resolved to the wrong
Newtown and produced a 56-minute walk-heavy trip that looked plausible enough
to be believed. In both cases everything downstream was correct about a place
the user had not asked for.

EFA hands back the evidence needed to choose properly and it was being thrown
away: `isBest`, `matchQuality`, `type`, and a coordinate that can be measured
against where the journey starts. All four are used here, deterministically —
no model call, so this stays off the 250/day budget and stays explainable.
"""
from .contracts import (PlaceCandidate, ResolvedPlace,
                        RESOLVED, AMBIGUOUS, IMPLAUSIBLE, NOT_FOUND)

# Beyond this, a place is not what was meant by a local trip. Sydney to
# Newcastle is 120 km, so 150 covers any reasonable commute while still
# catching Narrabri at 500. Only applied when the request did not ask for
# somewhere far away.
MAX_PLACE_KM = 150.0

# Two candidates this far apart are genuinely different places rather than two
# entrances to the same one, so a tie between them is worth asking about.
DISTINCT_PLACE_KM = 15.0

# Preference between kinds, used only to break an exact tie on the provider's
# own scores. A stop is the most useful answer to "how do I get to X" and a
# locality centroid the least: it is a point in a suburb, not a destination.
_KIND_RANK = {
    "stop": 0, "platform": 0, "poi": 1, "singlehouse": 2,
    "address": 2, "street": 3, "locality": 4, "suburb": 4,
}
_DEFAULT_KIND_RANK = 3


def _kind_rank(kind: str) -> int:
    return _KIND_RANK.get((kind or "").strip().lower(), _DEFAULT_KIND_RANK)


def candidate_from_location(loc, coord_pair, origin_ll=None, haversine=None):
    """One EFA location to a PlaceCandidate, or None if it has no coordinate."""
    coord = coord_pair(loc.get("coord"))
    if not coord:
        return None
    quality = loc.get("matchQuality")
    try:
        quality = int(quality) if quality is not None else None
    except (TypeError, ValueError):
        quality = None
    distance_km = None
    if origin_ll and haversine:
        distance_km = haversine(origin_ll, coord) / 1000.0
    return PlaceCandidate(
        name=(loc.get("disassembledName") or loc.get("name") or "").strip(),
        lat=coord[0], lng=coord[1],
        kind=(loc.get("type") or "").strip(),
        quality=quality,
        is_best=bool(loc.get("isBest")),
        distance_km=distance_km,
    )


def _sort_key(candidate):
    # isBest first — it is the provider's own answer to "which did you mean".
    # Then its match score, then the kind, then proximity. Every term is
    # ordered so that smaller is better, so one sorted() does the whole thing.
    return (
        0 if candidate.is_best else 1,
        -(candidate.quality if candidate.quality is not None else -1),
        _kind_rank(candidate.kind),
        candidate.distance_km if candidate.distance_km is not None else 0.0,
    )


def choose_place(requested, candidates, *, allow_long_distance=False,
                 max_km=MAX_PLACE_KM, source="provider") -> ResolvedPlace:
    """The best candidate, or a reason there isn't one. Pure and testable.

    Order of operations matters and follows the owner's stated preference:
    take the best candidate, reject the implausible, and ask only when the
    survivors tie or all of them fail. Asking is a last resort — a question
    the user has to answer is a worse outcome than a right answer.
    """
    usable = [c for c in candidates if c is not None]
    if not usable:
        return ResolvedPlace(requested=requested, state=NOT_FOUND, source=source,
                             reason=f"I couldn't find '{requested}' on the transit map.")

    ranked = sorted(usable, key=_sort_key)

    if allow_long_distance:
        near, far = ranked, []
    else:
        near = [c for c in ranked
                if c.distance_km is None or c.distance_km <= max_km]
        far = [c for c in ranked if c not in near]

    if not near:
        nearest = min(far, key=lambda c: c.distance_km)
        return ResolvedPlace(
            requested=requested, state=IMPLAUSIBLE, source=source,
            alternatives=far[:3],
            reason=(f"The only '{requested}' I can find is {nearest.name}, "
                    f"about {nearest.distance_km:.0f} km away. If you did mean "
                    "that one, say so and I'll plan it; otherwise give me a "
                    "suburb or a stop name."))

    best = near[0]

    # A tie is two candidates the provider ranked identically, that are far
    # enough apart to be different places. Anything the provider called `isBest`
    # is not a tie — it already answered the question.
    rivals = [c for c in near[1:]
              if not best.is_best
              and c.quality == best.quality
              and _kind_rank(c.kind) == _kind_rank(best.kind)
              and _km_between(best, c) > DISTINCT_PLACE_KM]
    if rivals:
        options = ", ".join(c.name for c in [best] + rivals[:2] if c.name)
        return ResolvedPlace(
            requested=requested, state=AMBIGUOUS, source=source,
            selected=None, alternatives=[best] + rivals[:2],
            reason=(f"'{requested}' could be more than one place — {options}. "
                    "Which did you mean?"))

    return ResolvedPlace(requested=requested, state=RESOLVED, source=source,
                         selected=best, alternatives=near[1:4])


def _km_between(a, b) -> float:
    """Straight-line km between two candidates, good enough to tell places apart.

    Equirectangular rather than haversine: this decides "same place or not" at a
    15 km threshold, where the two agree to well under a percent, and it keeps
    this module free of an import from the executor it is meant to serve.
    """
    import math
    mean_lat = math.radians((a.lat + b.lat) / 2.0)
    dx = math.radians(a.lng - b.lng) * math.cos(mean_lat)
    dy = math.radians(a.lat - b.lat)
    return math.hypot(dx, dy) * 6371.0


def saved_place_match(text, places) -> dict | None:
    """A saved place whose label the user just typed, or None.

    `trip_plan {"origin": "home"}` sent the literal string "home" to EFA, which
    matched some other Home in NSW and produced an itinerary leaving at 6:20 PM
    and arriving at 3:07 PM — 1248 minutes, 783 of them waiting. Omitting the
    origin had always worked, because that path reads saved_places; naming it
    did not, because that path did not. This closes the gap.
    """
    wanted = (text or "").strip().lower()
    if not wanted:
        return None
    for place in places or []:
        label = (place.get("label") or "").strip().lower()
        if label and label == wanted:
            return place
    # "my home", "home address" — the label with a word of politeness on it.
    for place in places or []:
        label = (place.get("label") or "").strip().lower()
        if label and wanted in (f"my {label}", f"{label} address", f"the {label}"):
            return place
    return None
