"""Deterministic travel reasoning: what a place is, and whether a journey is real.

Nothing in this package calls a model. Routing, validation and ranking are
arithmetic over provider data, which is what makes them explainable and what
keeps them off the 250-requests-a-day budget. `budget_gate.py` remains the only
path to an LLM, and no path from here reaches it.
"""
