"""Deterministic plausibility. Does this itinerary answer the question asked?

Two itineraries reached chat as "Best option" and neither was survivable:

    leave 6:20 PM, arrive 3:07 PM — 1248 min, 4 changes, 783 min waiting
    1953 min via Werris Creek, 1260 min waiting, for a 15 km trip

The first arrives before it departs. Both wait more than half a day. Neither
needed a model to be recognised as wrong, and both were shown to the user
anyway, because nothing between the provider and the answer had an opinion
about whether a journey was real.

Every rule here is arithmetic on numbers `summarise_journey` already produces.
Each rejection carries its reason, so the trace says why an option vanished
rather than leaving the answer looking arbitrary.

The rules overlap on purpose. The Werris Creek itinerary fails five of them
independently, and that redundancy is the design: the gate should not depend on
knowing which upstream bug produced its input.
"""

# A single wait longer than this is not a connection, it is a gap in service.
MAX_SINGLE_WAIT_MIN = 90

# Waiting more than this share of the total is a journey mostly spent standing
# still. 0.5 is deliberately loose — a real off-peak connection can be a third.
MAX_WAIT_FRACTION = 0.5

# Door to door, against the straight-line driving estimate. Public transport is
# genuinely slower than a car, and 4x covers a bad off-peak trip with two
# changes; 1953 minutes against a 20-minute drive is 97x.
MAX_DURATION_MULTIPLE = 4.0

# The backstop when there is no driving estimate to compare against. Nothing
# inside Greater Sydney takes six hours on public transport.
MAX_ABSOLUTE_DURATION_MIN = 360


def _minutes(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def rejection_reason(summary, now, arrive_by=None, drive_only_min=None,
                     allow_overnight=False):
    """Why this journey is not usable, or None if it is. Pure.

    `now` and `arrive_by` are aware datetimes. `drive_only_min` is the driving
    comparison when one was fetched; without it the absolute cap applies.
    """
    if not summary:
        return "the provider returned an empty journey"

    depart = summary.get("depart")
    arrive = summary.get("arrive")
    if depart is None or arrive is None:
        return "it has no usable departure or arrival time"

    # The one that needs no thresholds at all. An itinerary that arrives before
    # it leaves is not a bad option, it is not an option.
    if arrive <= depart:
        return "it arrives before it departs"

    if depart < now:
        return "it has already departed"

    if arrive_by is not None and arrive > arrive_by:
        return "it arrives after the time you need to be there"

    duration = _minutes(summary.get("duration_min"))
    if duration is None:
        duration = (arrive - depart).total_seconds() / 60.0

    if not allow_overnight and arrive.date() > depart.date():
        return "it arrives on a later day, which is not what you asked for"

    wait = _minutes(summary.get("wait_min"))
    if wait is not None:
        if wait > MAX_SINGLE_WAIT_MIN:
            return f"it involves {wait:.0f} minutes of waiting"
        if duration and wait > duration * MAX_WAIT_FRACTION:
            return (f"more than half of it — {wait:.0f} of {duration:.0f} "
                    "minutes — is spent waiting")

    drive = _minutes(drive_only_min)
    if drive and drive > 0:
        if duration > drive * MAX_DURATION_MULTIPLE:
            return (f"it takes {duration:.0f} minutes against a {drive:.0f}-minute "
                    "drive, which is too far off to be a real option")
    elif duration > MAX_ABSOLUTE_DURATION_MIN:
        return f"it takes {duration:.0f} minutes, which cannot be right"

    return None


def gate_journeys(summaries, now, arrive_by=None, drive_only_min=None,
                  allow_overnight=False):
    """Split journeys into (kept, [(journey, reason), …]). Pure.

    Returns rejections rather than discarding them so the failure message can
    say what was found and why none of it worked — the difference between
    "no services run" and "every option waits four hours", which are different
    problems with different answers.
    """
    kept, rejected = [], []
    for summary in summaries or []:
        reason = rejection_reason(summary, now, arrive_by, drive_only_min,
                                  allow_overnight)
        if reason:
            rejected.append((summary, reason))
        else:
            kept.append(summary)
    return kept, rejected


def rejection_summary(rejected) -> str:
    """One sentence naming the distinct reasons, commonest first.

    Deduplicated: five journeys rejected for the same reason is one fact about
    the trip, not five.
    """
    if not rejected:
        return ""
    counts = {}
    for _summary, reason in rejected:
        counts[reason] = counts.get(reason, 0) + 1
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return "; ".join(reason for reason, _n in ordered[:3])
