"""Calcul du prix final : prix Google (taxes incluses) + valises, selon le tarif le plus
avantageux de chaque compagnie."""

from __future__ import annotations

from dataclasses import dataclass, field

from voyage.config import money
from voyage.gflights import Slice


@dataclass
class Itinerary:
    kind: str  # "aller-retour", "2 allers simples" ou "multi-villes (estimé)"
    out: Slice
    ret: Slice
    price: float  # total Google Flights pour tous les passagers, taxes incluses
    links: list[str] = field(default_factory=list)
    # Vérification « économie de base » : True = le prix affiché est un tarif de base (Google
    # le retire avec le filtre), None = inconnu (non vérifié, ou prix inchangé, ce qui ne
    # prouve rien sur le transatlantique), False = confirmé que ce n'en est pas un.
    base_is_basic: bool | None = None
    nonbasic_price: float | None = None
    total: float = 0.0
    extras: float = 0.0  # part du total ajoutée au prix des vols : valises, surclassement
    score: float = 0.0  # prix utilisé pour le classement (préférences de qualité incluses)
    fares: tuple[str, str] = ("", "")  # tarif à choisir à l'aller et au retour
    lines: list[str] = field(default_factory=list)

    @property
    def stops(self) -> int:
        return self.out.stops + self.ret.stops

    @property
    def key(self) -> str:
        return f"{self.kind} | {self.out.key} | {self.ret.key}"

    @property
    def cities(self) -> str:
        a, b = self.out.dest, self.ret.origin
        return a if a == b else f"{a} → {b}"


@dataclass
class Option:
    family: str
    extra: float  # coût ajouté au prix Google, tous passagers
    upgrade: float
    bags: float
    advantages: str
    estimated: bool


def bag_cost(family: dict, passengers: int, bags: int) -> float:
    remaining = max(0, bags - family["bagages_inclus"] * passengers)
    if not remaining:
        return 0.0
    first_fee, second_fee = family["frais_bagage"]
    # Chaque passager paie d'abord sa 1re valise ; au-delà, ce sont des 2es valises.
    firsts = min(remaining, passengers) if family["bagages_inclus"] == 0 else 0
    return firsts * first_fee + (remaining - firsts) * second_fee


def base_index(policy: dict, base_is_basic: bool | None) -> int:
    """Tarif correspondant au prix affiché par Google. Sans information, on prend le moins
    cher de la liste (hypothèse prudente : aucune valise incluse)."""
    if base_is_basic is False:
        for i, family in enumerate(policy["tarifs"]):
            if family.get("google_basic") is not True:
                return i
    return 0


def slice_options(policy: dict, start: int, passengers: int, bags: int) -> list[Option]:
    options, upgrade = [], 0.0
    for i, family in enumerate(policy["tarifs"]):
        if i < start:
            continue
        if i > start:
            upgrade += family.get("supplement", 0) * passengers
        cost = bag_cost(family, passengers, bags)
        options.append(
            Option(family["nom"], upgrade + cost, upgrade, cost, family["avantages"], i > start)
        )
    return options


def _policy(airlines: dict, code: str) -> dict:
    return airlines.get(code) or airlines["*"]


def price_itinerary(itin: Itinerary, airlines: dict, passengers: int, bags: int) -> None:
    """Remplit ``itin.total`` et ``itin.lines`` (détail du calcul, en français)."""
    scenarios = []

    # Scénario 1 : prix Google + options des tarifs à partir du tarif présumé affiché.
    extra, lines, fares = 0.0, [], []
    for label, s in (("aller", itin.out), ("retour", itin.ret)):
        policy = _policy(airlines, s.carrier)
        options = slice_options(policy, base_index(policy, itin.base_is_basic), passengers, bags)
        best = min(options, key=lambda o: o.extra)
        extra += best.extra
        lines.append(_option_line(label, policy, best, options))
        fares.append(best.family)
    scenarios.append((itin.price, extra, lines, fares))

    # Scénario 2 : prix exact du tarif « non-base » obtenu de Google + valises de ce tarif.
    if itin.base_is_basic and itin.nonbasic_price:
        extra, lines = 0.0, [f"prix Google hors économie de base : {money(itin.nonbasic_price)}"]
        fares = []
        for label, s in (("aller", itin.out), ("retour", itin.ret)):
            policy = _policy(airlines, s.carrier)
            family = policy["tarifs"][base_index(policy, False)]
            cost = bag_cost(family, passengers, bags)
            extra += cost
            fares.append(family["nom"])
            lines.append(
                f"{label} {policy['nom']} {family['nom']} : valises {money(cost)} ({family['avantages']})"
            )
        scenarios.append((itin.nonbasic_price, extra, lines, fares))

    flights, itin.extras, lines, fares = min(scenarios, key=lambda sc: sc[0] + sc[1])
    itin.total = flights + itin.extras
    itin.fares = tuple(fares)
    itin.lines = [f"prix Google (taxes incluses, {passengers} pers.) : {money(itin.price)}", *lines]

    # Préférence de qualité : chaque trajet compte pour moitié du voyage.
    policies = [_policy(airlines, s.carrier) for s in (itin.out, itin.ret)]
    weight = sum(p.get("penalite_qualite", 0) for p in policies) / 2
    itin.score = itin.total * (1 + weight)
    if weight:
        penalized = {p["nom"]: p["penalite_qualite"] for p in policies if p.get("penalite_qualite")}
        who = ", ".join(f"{name} +{p * 100:.0f} %" for name, p in penalized.items())
        itin.lines.append(
            f"classement : compté {money(itin.score)} (préférence qualité : {who} sur ses trajets)"
        )


def _option_line(label: str, policy: dict, best: Option, options: list[Option]) -> str:
    parts = [f"{label} {policy['nom']} — tarif {best.family}"]
    if best.upgrade:
        parts.append(f"surclassement {money(best.upgrade)} (estimé)")
    parts.append(f"valises {money(best.bags)}" if best.bags else "valises incluses")
    line = ", ".join(parts) + f" ({best.advantages})"
    better = [o for o in options if o.extra > best.extra]
    if better:
        nxt = better[0]
        line += f" ; {nxt.family} pour +{money(nxt.extra - best.extra)} : {nxt.advantages}"
    return line
