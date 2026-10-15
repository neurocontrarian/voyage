"""Point d'entrée : python -m voyage [--essai]"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from fli.models import Airline

from voyage.config import ROOT, load_airlines, load_trip
from voyage.gflights import GoogleFlights, Slice
from voyage.notify import PANNE, notifier
from voyage.pricing import Itinerary
from voyage.search import Searcher

DATA = ROOT / "data"
STATE = DATA / "etat.json"
HISTORY = DATA / "historique.csv"
REPORT = DATA / "dernier_resultat.md"
TZ = ZoneInfo("America/Toronto")
CITY = {
    "YUL": "Montréal", "LIS": "Lisbonne", "OPO": "Porto", "FAO": "Faro", "PDL": "Ponta Delgada",
    "YYZ": "Toronto", "BOS": "Boston", "EWR": "Newark", "JFK": "New York", "PHL": "Philadelphie",
    "IAD": "Washington", "MAD": "Madrid", "CDG": "Paris", "LHR": "Londres", "FRA": "Francfort",
}
DAYS = ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."]
MONTHS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
          "septembre", "octobre", "novembre", "décembre"]

log = logging.getLogger("voyage")


def money(amount: float) -> str:
    return f"{amount:,.0f} $".replace(",", " ")


def city(code: str) -> str:
    return CITY.get(code, code)


def day(dt) -> str:
    return f"{DAYS[dt.weekday()]} {dt.day} {MONTHS[dt.month - 1]}"


def hour(dt) -> str:
    return f"{dt.hour} h {dt.minute:02d}"


def duration(minutes: int) -> str:
    return f"{minutes // 60} h {minutes % 60:02d}"


def airline_name(code: str, airlines: dict) -> str:
    if code in airlines:
        return airlines[code]["nom"]
    try:
        return Airline[code].value
    except KeyError:
        return code


def airlines_of(s: Slice, airlines: dict) -> str:
    return " + ".join(dict.fromkeys(airline_name(leg.airline, airlines) for leg in s.legs))


def both(out: str, ret: str) -> str:
    return out if out == ret else f"{out} (aller) · {ret} (retour)"


def trip_line(s: Slice) -> str:
    dep, arr = s.legs[0].dep, s.legs[-1].arr
    arrival = hour(arr) if arr.date() == dep.date() else f"{day(arr)} {hour(arr)}"
    stops = "direct" if not s.stops else ", ".join(
        f"escale à {city(leg.dest)} ({duration(m)})" for leg, m in zip(s.legs, s.layovers))
    return (f"{day(dep)}, {city(s.origin)} {hour(dep)} → {city(s.dest)} {arrival}"
            f" · {stops} · {duration(s.total_minutes)}")


def links(i: Itinerary) -> str:
    if len(i.links) == 1:
        return f"[Voir sur Google Flights]({i.links[0]})"
    return " · ".join(f"[Voir {what} sur Google Flights]({url})"
                      for what, url in zip(("l'aller", "le retour"), i.links))


def card(i: Itinerary, trip, airlines: dict) -> str:
    """Fiche courte du meilleur voyage : l'essentiel, le détail est sur le site de la compagnie."""
    rows = [
        ("Compagnie", both(airlines_of(i.out, airlines), airlines_of(i.ret, airlines))),
        ("Tarif à choisir", both(*i.fares)),
        ("Aller", trip_line(i.out)),
        ("Retour", trip_line(i.ret)),
        ("Arrivée au Portugal", city(i.out.dest)),
        ("Départ du Portugal", city(i.ret.origin)),
    ]
    if i.kind == "2 allers simples":
        rows.append(("Réservation", "2 billets séparés (un aller simple, un retour simple)"))
    elif i.kind.startswith("multi-villes"):
        rows.append(("Réservation", "« multi-destinations » sur le site de la compagnie (prix estimé)"))
    table = "\n".join(f"| **{k}** | {v} |" for k, v in rows)
    return (f"### {money(i.total)} tout compris\n"
            f"{trip.passagers} personnes, taxes et {trip.bagages_soute} valises en soute incluses\n\n"
            f"| | |\n|---|---|\n{table}\n\n{links(i)}")


def summary_row(i: Itinerary, airlines: dict, note: str = "") -> str:
    stops = "direct" if i.stops == 0 else f"{i.stops} escale" + ("s" if i.stops > 1 else "")
    cities = " / ".join(dict.fromkeys([city(i.out.dest), city(i.ret.origin)]))
    company = both(airlines_of(i.out, airlines), airlines_of(i.ret, airlines))
    return (f"| {money(i.total)}{note} | {company} | {i.out.legs[0].dep.day}/{i.out.legs[0].dep.month}"
            f" → {i.ret.legs[0].dep.day}/{i.ret.legs[0].dep.month} | {stops} | {cities} |")


FOOTER = ("_Prix = Google Flights taxes incluses + valises selon le tarif indiqué. "
          "Vérifier sur le site de la compagnie avant d'acheter._")


def report(trip, outcome, airlines: dict, now: datetime) -> str:
    """Contenu de data/dernier_resultat.md : la fiche du meilleur voyage, puis les suivants."""
    if not outcome.itineraries:
        return f"## {trip.nom} — {now:%Y-%m-%d %H:%M}\n\nAucun résultat."
    best, others = outcome.itineraries[0], outcome.itineraries[1: trip.alerte["top"]]
    # † : moins cher que le premier choix, mais classé après à cause d'une préférence qualité.
    rows = [summary_row(i, airlines, " †" if i.total < best.total else "") for i in others]
    two = outcome.best_two_cities
    if two and two is not best and two not in others:
        rows.append(summary_row(two, airlines, " *"))
    lines = [f"## {trip.nom} — recherche du {now:%Y-%m-%d à %H:%M}", "", card(best, trip, airlines)]
    if rows:
        lines += ["", "#### Autres options", "",
                  "| Prix | Compagnie | Dates | Escales | Villes |", "|---|---|---|---|---|", *rows]
        if any(i.total < best.total for i in others):
            penalized = ", ".join(f"{p['nom']} +{p['penalite_qualite'] * 100:.0f} %"
                                  for p in airlines.values() if p.get("penalite_qualite"))
            lines.append(f"\n† moins cher, mais classé après (préférence qualité : {penalized})")
        if two and two not in outcome.itineraries:
            lines.append("\n\\* deux villes différentes ; l'escale ne fait pas économiser 15 % "
                         "par rapport au meilleur vol direct")
    return "\n".join([*lines, "", FOOTER])


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def append_history(now, best, best_direct, outcome) -> None:
    new = not HISTORY.exists()
    with HISTORY.open("a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["horodatage", "meilleur_total", "meilleur_direct_total", "meilleur",
                        "itineraires", "pages", "echecs"])
        w.writerow([
            now.isoformat(timespec="minutes"),
            round(best.total) if best else "",
            round(best_direct.total) if best_direct else "",
            best.key if best else "",
            len(outcome.itineraries), outcome.requests, len(outcome.errors),
        ])


def main() -> int:
    parser = argparse.ArgumentParser(description="Surveillance de prix de vols")
    parser.add_argument("--essai", action="store_true",
                        help="affiche le résultat sans publier d'alerte ni modifier data/")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    trip, airlines = load_trip(), load_airlines()
    gf = GoogleFlights(trip.devise, trip.passagers)
    outcome = Searcher(trip, airlines, gf).run()
    now = datetime.now(TZ)
    text = report(trip, outcome, airlines, now)
    print(text)
    for err in outcome.errors[:10]:
        log.warning(err)
    if args.essai:
        return 0

    DATA.mkdir(exist_ok=True)
    state = load_state()
    gh = notifier()
    best = outcome.itineraries[0] if outcome.itineraries else None
    best_direct = next((i for i in outcome.itineraries if i.stops == 0), None)
    append_history(now, best, best_direct, outcome)

    if best is None:
        state["echecs"] = state.get("echecs", 0) + 1
        if state["echecs"] == trip.alerte["echecs_avant_alerte"]:
            gh.post(*PANNE, f"{state['echecs']} exécutions d'affilée sans résultat. Erreurs :\n\n```\n"
                    + "\n".join(outcome.errors[:15]) + "\n```")
        STATE.write_text(json.dumps(state, indent=2, ensure_ascii=False))
        return 1

    state["echecs"] = 0
    REPORT.write_text(text + "\n")
    # Le record porte sur le classement (prix + préférences de qualité). Un ancien état sans
    # « score » date d'avant les préférences : on repart d'un nouveau classement.
    record = state.get("record") if "score" in state.get("record", {}) else None
    if record is None or best.score <= record["score"] - trip.alerte["baisse_min"]:
        if record:
            counted = f", compté {money(record['score'])}" if record["score"] != record["total"] else ""
            previous = f" (précédent : {money(record['total'])}{counted}, le {record['date']})"
        elif state.get("record"):
            previous = " (classement recalculé avec les préférences de qualité des compagnies)"
        else:
            previous = ""
        gh.post("alerte-prix", f"✈️ Alertes prix — {trip.nom}",
                "Un commentaire est ajouté ici chaque fois qu'un meilleur prix apparaît.",
                f"**Nouveau meilleur prix**{previous}\n\n{card(best, trip, airlines)}\n\n{FOOTER}")
        state["record"] = {"total": round(best.total), "score": round(best.score),
                           "cle": best.key, "date": f"{now:%Y-%m-%d %H:%M}"}
    state["derniere_execution"] = now.isoformat(timespec="minutes")
    STATE.write_text(json.dumps(state, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
