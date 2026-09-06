-- travel_plans: remember which places a name could have meant.
--
-- When resolution is ambiguous, `choose_place` already collects every candidate
-- TfNSW returned — and until now they were mentioned in a sentence and then
-- thrown away, so the only way to act on them was to retype a better guess.
--
-- Names alone would not be enough even if they were kept: two Newtowns are the
-- same word in a list and different points on a map. Each option therefore
-- carries its own coordinate, which is what lets the Travel page put a pin
-- beside it and makes the choice answerable in a tap.
--
-- `unresolved` says WHICH end failed. "I couldn't place that" reads identically
-- whether it was where you are leaving from or where you are going, and those
-- need different answers from the user.

alter table public.travel_plans
    add column if not exists place_options jsonb not null default '[]'::jsonb,
    add column if not exists unresolved text;

alter table public.travel_plans
    drop constraint if exists travel_plans_unresolved_check;

alter table public.travel_plans
    add constraint travel_plans_unresolved_check
    check (unresolved is null or unresolved in ('origin', 'destination'));

comment on column public.travel_plans.place_options is
    'Candidate places the request could have meant, when resolution was '
    'ambiguous. Each carries name, lat, lng, kind and a map_url so the UI can '
    'offer a verifiable choice rather than a list of identical-looking names.';

comment on column public.travel_plans.unresolved is
    'Which end failed to resolve: origin or destination. NULL when the plan '
    'succeeded, or when it failed for a reason other than resolution.';
