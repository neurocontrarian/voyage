"""Règles du voyage : dates, nuits, escales."""

from __future__ import annotations

from voyage.config import Scenario, Trip
from voyage.gflights import Slice
from voyage.pricing import Itinerary


def slice_ok(s: Slice, trip: Trip) -> bool:
    """Trajet acceptable : escales permises par au moins un scénario, durée totale (attente en
    escale comprise) sous le maximum, et aucun vol d'une compagnie exclue."""
    return (
        s.stops <= trip.escales_max
        and s.total_minutes <= trip.duree_trajet_max_minutes
        and not any(leg.airline in trip.compagnies_exclues for leg in s.legs)
    )


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
