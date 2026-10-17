"""Planification des recherches et assemblage des itinéraires."""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from itertools import product

from fli.search._concurrency import parallel_map

from voyage.config import Trip
from voyage.gflights import GoogleFlights, Offer, Segment
from voyage.pricing import Itinerary, price_itinerary
from voyage.rules import dates_ok, keep_worthwhile, slice_ok

log = logging.getLogger(__name__)
WORKERS = 4


@dataclass
class Outcome:
    itineraries: list[Itinerary]
    requests: int = 0
    errors: list[str] = field(default_factory=list)
    # Meilleure option arrivée/départ de villes différentes, même écartée par la règle des escales.
    best_two_cities: Itinerary | None = None


class Searcher:
    def __init__(self, trip: Trip, airlines: dict, gf: GoogleFlights):
        self.trip, self.airlines, self.gf = trip, airlines, gf
        self.requests, self.errors = 0, []

    # -- requêtes --------------------------------------------------------------

    def _segment(self, origin: str, dest: str, day: date, selected=None) -> Segment:
        # Les durées de correspondance sont filtrées ici et non par Google : en aller-retour,
        # son filtre écarte un aller dès que le meilleur retour associé ne le respecte pas.
        return Segment(origin, dest, day.isoformat(), self.trip.escales["max"], selected=selected)

    def _fetch_all(self, tasks: dict) -> dict:
        """tasks : clé -> (segments, one_way, exclude_basic). Les échecs donnent None."""

        def run(item):
            key, (segments, one_way, exclude_basic) = item
            try:
                return key, self.gf.search(segments, one_way=one_way, exclude_basic=exclude_basic)
            except Exception as exc:  # une page ratée ne doit pas arrêter toute la recherche
                return key, exc

        results = {}
        for key, value in parallel_map(run, list(tasks.items()), max_workers=WORKERS):
            self.requests += 1
            if isinstance(value, Exception):
                self.errors.append(f"{key}: {type(value).__name__}: {value}")
                results[key] = None
            else:
                results[key] = value
        return results

    # -- recherche -------------------------------------------------------------

    def run(self) -> Outcome:
        trip, o = self.trip, self.trip.origine
        pairs = trip.date_pairs()
        cities = trip.destinations
        dep_days = sorted({d for d, _ in pairs})
        ret_days = sorted({r for _, r in pairs})

        # 1. Allers des allers-retours, et allers/retours simples.
        tasks = {}
        for (d, r), city in product(pairs, cities):
            tasks[("rt", d, r, city)] = (
                [self._segment(o, city, d), self._segment(city, o, r)], False, False)
        for d, city in product(dep_days, cities):
            tasks[("ow-out", d, city)] = ([self._segment(o, city, d)], True, False)
        for r, city in product(ret_days, cities):
            tasks[("ow-ret", r, city)] = ([self._segment(city, o, r)], True, False)
        boards = self._fetch_all(tasks)

        # 2. Retours des meilleurs allers.
        tasks, k = {}, trip.recherche["allers_detailles"]
        for (d, r), city in product(pairs, cities):
            outs = self._valid(boards[("rt", d, r, city)], "aller")[:k]
            for out in outs:
                tasks[("rt-ret", d, r, city, out.slice.key)] = (
                    [self._segment(o, city, d, out.slice), self._segment(city, o, r)], False, False)
        returns = self._fetch_all(tasks)

        itins = self._round_trips(tasks, returns)
        itins += self._one_way_pairs(pairs, boards)
        if trip.villes_differentes:
            itins += self._open_jaw_estimates(pairs, boards)
        itins = [i for i in itins if dates_ok(i, trip)]
        itins = self._dedupe(itins)
        for itin in itins:
            self._price(itin)
        itins.sort(key=lambda i: i.score)

        to_check = keep_worthwhile(itins, trip)[: trip.recherche["verifier_tarif_de_base"]]
        two_cities = self._best_two_cities(itins)
        if two_cities and two_cities not in to_check:
            to_check.append(two_cities)
        self._check_basic(to_check)
        itins.sort(key=lambda i: i.score)
        return Outcome(keep_worthwhile(itins, trip), self.requests, self.errors,
                       self._best_two_cities(itins))

    @staticmethod
    def _best_two_cities(itins: list[Itinerary]) -> Itinerary | None:
        return next((i for i in itins if i.out.dest != i.ret.origin), None)

    # -- assemblage ------------------------------------------------------------

    def _valid(self, offers: list[Offer] | None, direction: str) -> list[Offer]:
        good = [
            x for x in offers or []
            if x.price is not None and slice_ok(x.slice, self.trip, direction)
        ]
        return sorted(good, key=lambda x: x.price)

    def _round_trips(self, tasks: dict, returns: dict) -> list[Itinerary]:
        itins = []
        for key, offers in returns.items():
            out = tasks[key][0][0].selected
            for ret in self._valid(offers, "retour"):
                itins.append(Itinerary(
                    "aller-retour", out, ret.slice, ret.price,
                    links=[self.gf.booking_url([out, ret.slice])]))
        return itins

    def _one_way_pairs(self, pairs, boards) -> list[Itinerary]:
        n, itins = self.trip.recherche["allers_simples_combines"], []
        for d, r in pairs:
            for a, b in product(self.trip.destinations, repeat=2):
                if a != b and not self.trip.villes_differentes:
                    continue
                outs = self._valid(boards[("ow-out", d, a)], "aller")[:n]
                rets = self._valid(boards[("ow-ret", r, b)], "retour")[:n]
                for out, ret in product(outs, rets):
                    itins.append(Itinerary(
                        "2 allers simples", out.slice, ret.slice, out.price + ret.price,
                        links=[self.gf.booking_url([out.slice]), self.gf.booking_url([ret.slice])]))
        return itins

    def _open_jaw_estimates(self, pairs, boards) -> list[Itinerary]:
        """Les compagnies tarifent un multi-villes comme la moitié de deux allers-retours.
        Google ne permet plus d'interroger directement le multi-villes : on l'estime ainsi,
        avec le prix aller-retour affiché par Google vers chaque ville pour la même compagnie."""

        def by_carrier(offers, direction=None):
            best = {}
            for x in offers or []:
                if x.price is None or (direction and not slice_ok(x.slice, self.trip, direction)):
                    continue
                c = x.slice.carrier
                if c not in best or x.price < best[c].price:
                    best[c] = x
            return best

        estimates = []
        for d, r in pairs:
            for a, b in product(self.trip.destinations, repeat=2):
                if a == b:
                    continue
                outs = by_carrier(boards[("rt", d, r, a)], "aller")  # aller valide vers a
                rt_b = by_carrier(boards[("rt", d, r, b)])  # niveau de prix aller-retour vers b
                rets = by_carrier(boards[("ow-ret", r, b)], "retour")  # retour valide depuis b
                for c in outs.keys() & rt_b.keys() & rets.keys():
                    out, ret = outs[c].slice, rets[c].slice
                    estimates.append(Itinerary(
                        "multi-villes (estimé)", out, ret, (outs[c].price + rt_b[c].price) / 2,
                        links=[self.gf.booking_url([out]), self.gf.booking_url([ret])]))
        return estimates

    @staticmethod
    def _dedupe(itins: list[Itinerary]) -> list[Itinerary]:
        best = {}
        for i in itins:
            if i.key not in best or i.price < best[i.key].price:
                best[i.key] = i
        return list(best.values())

    def _price(self, itin: Itinerary) -> None:
        price_itinerary(itin, self.airlines, self.trip.passagers, self.trip.bagages_soute)

    # -- vérification du tarif de base -----------------------------------------

    def _check_basic(self, itins: list[Itinerary]) -> None:
        """Redemande les mêmes vols en excluant l'« économie de base » : si le prix monte,
        le prix affiché était un tarif sans valise et on connaît le prix exact du suivant."""
        o, tasks = self.trip.origine, {}
        for i in itins:
            d, r = i.out.legs[0].dep.date(), i.ret.legs[0].dep.date()
            if i.kind == "aller-retour":
                tasks[("nb-rt", i.key)] = (
                    [self._segment(o, i.out.dest, d, i.out), self._segment(i.ret.origin, o, r)],
                    False, True)
            elif i.kind == "2 allers simples":
                tasks[("nb-out", d, i.out.dest)] = ([self._segment(o, i.out.dest, d)], True, True)
                tasks[("nb-ret", r, i.ret.origin)] = ([self._segment(i.ret.origin, o, r)], True, True)
        results = self._fetch_all(tasks)

        def match(offers, s):
            prices = [x.price for x in offers or [] if x.slice.key == s.key and x.price]
            return min(prices) if prices else None

        for i in itins:
            d, r = i.out.legs[0].dep.date(), i.ret.legs[0].dep.date()
            if i.kind == "aller-retour":
                offers = results.get(("nb-rt", i.key))
                if offers is None:
                    continue
                nonbasic = match(offers, i.ret)
            elif i.kind == "2 allers simples":
                a, b = results.get(("nb-out", d, i.out.dest)), results.get(("nb-ret", r, i.ret.origin))
                if a is None or b is None:
                    continue
                pa, pb = match(a, i.out), match(b, i.ret)
                nonbasic = pa + pb if pa and pb else None
            else:
                continue
            # Sur le transatlantique, Google ignore ce filtre : un prix inchangé ne prouve rien
            # (inconnu = on suppose le tarif le moins cher, valises à payer).
            i.base_is_basic = True if nonbasic is None or nonbasic > i.price + 0.5 else None
            i.nonbasic_price = nonbasic
            self._price(i)
