"""
Minimal in-memory data model — just enough to run the daily/fast loops
against fake data. Not a real schema yet. Field names track the spec.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum


class Confidence(str, Enum):
    CONFIRMED = "confirmed"
    INFERRED = "inferred"


@dataclass
class ScalarField:
    value: object
    confidence: Confidence = Confidence.INFERRED
    updated_at: datetime = field(default_factory=datetime.now)
    decay_days: int = 90  # how long before this needs re-confirming

    def is_stale(self, now: datetime) -> bool:
        return (now - self.updated_at) > timedelta(days=self.decay_days)


@dataclass
class Household:
    """A 'User' in spec terms — the organizer, has a channel."""
    id: str
    name: str
    kids: list = field(default_factory=list)         # list of Person ids (kids)
    offers: dict = field(default_factory=dict)        # name -> ScalarField(tier)
    availability: ScalarField = None
    engagement_score: float = 1.0
    invited_by: str = None


@dataclass
class Person:
    """Anyone known — can be a household member, spouse, kid, non-user adult."""
    id: str
    name: str
    is_minor: bool = False
    household_id: str = None
    tier_a_cleared: bool = False  # background check + training current


@dataclass
class Edge:
    """Directional, contextual trust or like score between two households."""
    from_id: str
    to_id: str
    context: str  # "kid_dropoff" | "general_social"
    kind: str     # "trust" | "likes"
    rung: int = 0
    basis: str = "no_data"
    confirmed_at: datetime = None

    def is_confirmed(self) -> bool:
        return self.basis != "no_data" and self.confirmed_at is not None


@dataclass
class Place:
    id: str
    name: str
    owner_household_id: str
    attributes: dict = field(default_factory=dict)  # e.g. {"bugs": "bad_evenings"}


@dataclass
class EventCandidate:
    """A proposed event moving through the flow."""
    id: str
    kernel_household_ids: list           # the core people (must all confirm)
    place_id: str = None
    program: str = None                  # what you'd do
    status: str = "evaluating"           # evaluating -> kernel_confirming -> broadcasting -> confirmed -> cancelled
    confirmations: dict = field(default_factory=dict)  # household_id -> bool
    logistics: dict = field(default_factory=dict)      # e.g. {"time": ..., "bring": ...}
