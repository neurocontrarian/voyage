"""Accès à Google Flights par sa page publique, via les briques de la librairie fli.

fli (github.com/punitarani/fli) sait encoder une recherche dans le paramètre ``tfs`` de
la page, y compris un aller déjà choisi pour obtenir les retours correspondants, et
décoder les résultats. On y ajoute le champ 25 (« exclure l'économie de base »), que
la page respecte mais que fli n'envoie pas.

Les prix renvoyés sont les totaux taxes incluses pour tous les passagers, dans la devise
demandée.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from fli.search._decoders import parse_flight_row
from fli.search._proto import (
    LegSpec,
    _to_urlsafe_b64,
    _varint_field,
    build_tfs_token,
    encode_tfs_segment,
)
from fli.search._tfs import fetch_payload
from fli.search.client import get_client

PAGE_URL = "https://www.google.com/travel/flights"
BOOKING_URL = "https://www.google.com/travel/flights/booking"
EXCLUDE_BASIC_FIELD = 25


@dataclass(frozen=True)
class Leg:
    airline: str
    flight_number: str
    origin: str
    dest: str
    dep: datetime
    arr: datetime
    minutes: int

    @property
    def code(self) -> str:
        return f"{self.airline}{self.flight_number}"


@dataclass(frozen=True)
class Slice:
    """Un trajet (aller ou retour), direct ou avec correspondance."""

    legs: tuple[Leg, ...]

    @property
    def origin(self) -> str:
        return self.legs[0].origin

    @property
    def dest(self) -> str:
        return self.legs[-1].dest

    @property
    def stops(self) -> int:
        return len(self.legs) - 1

    @property
    def flight_minutes(self) -> int:
        return sum(leg.minutes for leg in self.legs)

    @property
    def layovers(self) -> list[int]:
        return [
            int((b.dep - a.arr).total_seconds() // 60)
            for a, b in zip(self.legs, self.legs[1:])
        ]

    @property
    def total_minutes(self) -> int:
        """Durée du trajet, correspondances comprises."""
        return self.flight_minutes + sum(self.layovers)

    @property
    def carrier(self) -> str:
        """Compagnie du plus long vol : c'est sa politique tarifaire qui s'applique."""
        return max(self.legs, key=lambda leg: leg.minutes).airline

    @property
    def key(self) -> str:
        return f"{self.legs[0].dep:%Y-%m-%d} " + "+".join(leg.code for leg in self.legs)

    def describe(self) -> str:
        first, last = self.legs[0], self.legs[-1]
        via = "direct" if not self.stops else "via " + ", ".join(
            f"{leg.dest} ({m // 60}h{m % 60:02d})"
            for leg, m in zip(self.legs, self.layovers)
        )
        return (
            f"{'+'.join(leg.code for leg in self.legs)} {first.origin} {first.dep:%d/%m %H:%M}"
            f" → {last.dest} {last.arr:%d/%m %H:%M} ({via})"
        )


@dataclass(frozen=True)
class Offer:
    slice: Slice
    price: float | None  # total du voyage pour tous les passagers, tel qu'affiché sur la ligne


@dataclass(frozen=True)
class Segment:
    origin: str
    dest: str
    date: str
    max_stops: int = 1
    min_layover: int | None = None
    max_layover: int | None = None
    selected: Slice | None = None


def _leg_specs(s: Slice) -> list[LegSpec]:
    return [
        LegSpec(
            origin=leg.origin,
            dep_date=f"{leg.dep:%Y-%m-%d}",
            dest=leg.dest,
            airline=leg.airline,
            flight_number=leg.flight_number,
        )
        for leg in s.legs
    ]


def _iata(value) -> str:
    return (getattr(value, "name", None) or str(value)).removeprefix("_")


def _to_slice(result) -> Slice:
    return Slice(
        tuple(
            Leg(
                airline=_iata(leg.airline),
                flight_number=str(leg.flight_number),
                origin=_iata(leg.departure_airport),
                dest=_iata(leg.arrival_airport),
                dep=leg.departure_datetime,
                arr=leg.arrival_datetime,
                minutes=leg.duration,
            )
            for leg in result.legs
        )
    )


class GoogleFlights:
    def __init__(self, currency: str, passengers: int, language: str = "fr", country: str = "CA"):
        self.currency = currency
        self.passengers = passengers
        self.language = language
        self.country = country

    def _tfs(self, segments: list[Segment], one_way: bool, exclude_basic: bool) -> str:
        body = _varint_field(1, 28) + _varint_field(2, 2)
        for seg in segments:
            body += encode_tfs_segment(
                seg.origin,
                seg.dest,
                seg.date,
                legs=_leg_specs(seg.selected) if seg.selected else (),
                max_stops=seg.max_stops,
                min_layover=seg.min_layover,
                max_layover=seg.max_layover,
            )
        body += _varint_field(8, 1) * self.passengers  # adultes
        body += _varint_field(9, 1) + _varint_field(14, 1)  # économie
        body += _varint_field(19, 2 if one_way else 1)
        if exclude_basic:
            body += _varint_field(EXCLUDE_BASIC_FIELD, 1)
        return _to_urlsafe_b64(body)

    def search(
        self, segments: list[Segment], *, one_way: bool, exclude_basic: bool = False
    ) -> list[Offer]:
        """Une page de résultats. Pour un aller-retour sans aller choisi, ce sont les allers
        (prix = aller-retour le moins cher qui commence par cet aller) ; avec un aller choisi,
        ce sont les retours possibles (prix = total exact de l'aller-retour)."""
        tfs = self._tfs(segments, one_way, exclude_basic)
        url = (
            f"{PAGE_URL}?tfs={tfs}&hl={self.language}&gl={self.country}&curr={self.currency}"
        )
        payload = fetch_payload(get_client(), url)  # client partagé, limite de débit gérée par fli
        if payload is None:
            raise RuntimeError("page Google Flights sans résultats exploitables")
        rows = [
            row
            for i in (2, 3)
            if isinstance(payload[i], list) and payload[i] and payload[i][0]
            for row in payload[i][0]
        ]
        offers = []
        for row in rows:
            try:
                result = parse_flight_row(row)
            except (AttributeError, KeyError, ValueError, TypeError, IndexError):
                continue  # ligne publicitaire ou compagnie inconnue de fli
            offers.append(Offer(_to_slice(result), result.price))
        return offers

    def booking_url(self, slices: list[Slice]) -> str:
        tfs = build_tfs_token(
            [_leg_specs(s) for s in slices],
            is_one_way=len(slices) == 1,
            passengers=[1] * self.passengers,
        )
        return f"{BOOKING_URL}?tfs={tfs}&hl={self.language}&gl={self.country}&curr={self.currency}"
