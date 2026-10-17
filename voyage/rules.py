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
    """Départ à la date prévue, retour à temps, et le nombre de nuits prévu (ou une de moins)."""
    arrival = itin.out.legs[-1].arr.date()
    back_departure = itin.ret.legs[0].dep.date()
    return (
        itin.out.legs[0].dep.date() == trip.depart
        and itin.ret.legs[-1].arr.date() <= trip.retour_au_plus_tard
        and (back_departure - arrival).days in (trip.nuits, trip.nuits - 1)
    )


def _only_if_cheaper(itins: list[Itinerary], is_reference, min_saving: float) -> list[Itinerary]:
    """Garde les itinéraires de référence, et les autres seulement s'ils coûtent au moins
    ``min_saving`` (en fraction) de moins que la meilleure référence."""
    reference = [i.total for i in itins if is_reference(i)]
    if not reference:
        return itins
    ceiling = min(reference) * (1 - min_saving)
    return [i for i in itins if is_reference(i) or i.total <= ceiling]


def keep_worthwhile(itins: list[Itinerary], trip: Trip) -> list[Itinerary]:
    """Garde les vols directs, et les escales seulement si elles font économiser assez ; de
    même, le séjour d'une nuit de moins ne vaut que s'il est nettement moins cher."""
    itins = _only_if_cheaper(itins, lambda i: i.stops == 0, trip.escales["economie_min_vs_direct"])
    return _only_if_cheaper(itins, lambda i: nights(i) == trip.nuits, trip.nuit_en_moins_economie_min)


def nights(itin: Itinerary) -> int:
    return (itin.ret.legs[0].dep.date() - itin.out.legs[-1].arr.date()).days
