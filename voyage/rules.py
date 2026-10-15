"""Règles du voyage : dates, nuits, escales."""

from __future__ import annotations

from voyage.config import Trip
from voyage.gflights import Slice
from voyage.pricing import Itinerary


def slice_ok(s: Slice, trip: Trip, direction: str) -> bool:
    """direction : "aller" ou "retour"."""
    rules = trip.escales
    if s.stops > rules["max"]:
        return False
    if any(
        not rules["correspondance_min_minutes"] <= m <= rules["correspondance_max_minutes"]
        for m in s.layovers
    ):
        return False
    limit = rules["duree_vol_direct_minutes"][direction] + rules["temps_de_vol_en_plus_max_minutes"]
    return s.flight_minutes <= limit


def dates_ok(itin: Itinerary, trip: Trip) -> bool:
    arrival = itin.out.legs[-1].arr.date()
    back_departure = itin.ret.legs[0].dep.date()
    return (
        itin.out.legs[0].dep.date() >= trip.depart_au_plus_tot
        and itin.ret.legs[-1].arr.date() <= trip.retour_au_plus_tard
        and (back_departure - arrival).days >= trip.nuits_min
    )


def keep_worthwhile(itins: list[Itinerary], trip: Trip) -> list[Itinerary]:
    """Garde les vols directs, et les escales seulement si elles font économiser assez."""
    direct = [i.total for i in itins if i.stops == 0]
    if not direct:
        return itins
    ceiling = min(direct) * (1 - trip.escales["economie_min_vs_direct"])
    return [i for i in itins if i.stops == 0 or i.total <= ceiling]
