"""Règles du voyage : dates, nuits, escales."""

from __future__ import annotations

from voyage.config import Scenario, Trip
from voyage.gflights import Slice
from voyage.pricing import Itinerary


def slice_ok(s: Slice, trip: Trip, direction: str) -> bool:
    """direction : "aller" ou "retour". Escales permises par au moins un scénario."""
    rules = trip.escales
    if s.stops > trip.escales_max:
        return False
    if any(
        not rules["correspondance_min_minutes"] <= m <= rules["correspondance_max_minutes"]
        for m in s.layovers
    ):
        return False
    limit = rules["duree_vol_direct_minutes"][direction] + rules["temps_de_vol_en_plus_max_minutes"]
    return s.flight_minutes <= limit


def fits(itin: Itinerary, sc: Scenario) -> bool:
    """L'itinéraire respecte les dates, les nuits et les escales du scénario."""
    departure = itin.out.legs[0].dep.date()
    back = itin.ret.legs[-1].arr.date()
    return (
        sc.depart_du <= departure <= sc.dernier_depart
        and sc.premier_retour <= back <= sc.retour_au
        and nights(itin) >= sc.nuits_min
        and max(itin.out.stops, itin.ret.stops) <= sc.escales_max
    )


def nights(itin: Itinerary) -> int:
    return (itin.ret.legs[0].dep.date() - itin.out.legs[-1].arr.date()).days
