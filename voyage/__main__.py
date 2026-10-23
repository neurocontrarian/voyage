"""Point d'entrée : python -m voyage [--essai]"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import sys
from datetime import datetime

from fli.models import Airline

from voyage.config import DATA, HISTORY, STATE, TZ, load_airlines, load_state, load_trip, money
from voyage.gflights import GoogleFlights, Slice
from voyage.notify import PANNE, notifier, post_alerte
from voyage.pricing import Itinerary
from voyage.search import ScenarioResult, Searcher

REPORT = DATA / "dernier_resultat.md"
CITY = {
    "YUL": "Montréal", "LIS": "Lisbonne", "CMN": "Casablanca", "PDL": "Ponta Delgada", "OPO": "Porto", "FAO": "Faro",
    "YYZ": "Toronto", "BOS": "Boston", "EWR": "Newark", "JFK": "New York", "PHL": "Philadelphie",
    "IAD": "Washington", "MAD": "Madrid", "CDG": "Paris", "LHR": "Londres", "FRA": "Francfort",
}
DAYS = ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."]
MONTHS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
          "septembre", "octobre", "novembre", "décembre"]

log = logging.getLogger("voyage")


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
        ("Détail du prix", f"vols {money(i.total - i.extras)} (taxes incluses)"
                           + (f" + valises et tarif {money(i.extras)}" if i.extras else " + aucune valise à payer")),
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


def stops_text(i: Itinerary) -> str:
    out, ret = i.out.stops, i.ret.stops
    if not out and not ret:
        return "direct"
    return "escale " + ("aller et retour" if out and ret else "à l'aller" if out else "au retour")


def summary_cells(i: Itinerary, airlines: dict) -> list[str]:
    cities = " / ".join(dict.fromkeys([city(i.out.dest), city(i.ret.origin)]))
    company = both(airlines_of(i.out, airlines), airlines_of(i.ret, airlines))
    dep, ret = i.out.legs[0].dep, i.ret.legs[0].dep
    return [money(i.total), company, f"{dep.day}/{dep.month} → {ret.day}/{ret.month}",
            stops_text(i), cities]


def summary_row(i: Itinerary, airlines: dict, note: str = "") -> str:
    cells = summary_cells(i, airlines)
    cells[0] += note
    return "| " + " | ".join(cells) + " |"


def summary_line(i: Itinerary, airlines: dict) -> str:
    """Le voyage en une ligne (rappel de 17 h)."""
    return " · ".join(summary_cells(i, airlines))


FOOTER = ("_Prix = Google Flights taxes incluses + valises selon le tarif indiqué. "
          "Vérifier sur le site de la compagnie avant d'acheter._")


def scenario_section(r: ScenarioResult, trip, airlines: dict, shown: dict) -> list[str]:
    """Fiche du meilleur voyage du scénario, puis les suivants. ``shown`` : clé -> numéro du
    scénario dont la fiche est déjà affichée (pour ne pas répéter la même fiche)."""
    lines = ["", f"## {r.scenario.titre}", ""]
    if not r.itineraries:
        return lines + ["Aucun vol trouvé sur Google Flights pour ce scénario."]
    best, others = r.itineraries[0], r.itineraries[1: trip.alerte["top"]]
    if best.key in shown:
        lines.append(f"Meilleur voyage : {money(best.total)}, le même qu'au scénario {shown[best.key]}.")
    else:
        shown[best.key] = r.scenario.numero
        lines.append(card(best, trip, airlines))
    # † : moins cher que le premier choix, mais classé après à cause d'une préférence qualité.
    rows = [summary_row(i, airlines, " †" if i.total < best.total else "") for i in others]
    two = r.best_two_cities
    if two and two is not best and two not in others:
        rows.append(summary_row(two, airlines, " *"))
    if rows:
        lines += ["", "#### Autres options", "",
                  "| Prix | Compagnie | Dates | Escales | Villes |", "|---|---|---|---|---|", *rows]
        if any(i.total < best.total for i in others):
            penalized = ", ".join(f"{p['nom']} +{p['penalite_qualite'] * 100:.0f} %"
                                  for p in airlines.values() if p.get("penalite_qualite"))
            lines.append(f"\n† moins cher, mais classé après (préférence qualité : {penalized})")
        if two and two is not best and two not in others:
            lines.append("\n\\* meilleure option avec deux villes différentes")
    return lines


def report(trip, outcome, airlines: dict, now: datetime) -> str:
    """Contenu de data/dernier_resultat.md : pour chaque scénario, la fiche du meilleur voyage,
    puis les suivants."""
    lines, shown = [f"# {trip.nom} — recherche du {now:%Y-%m-%d à %H:%M}"], {}
    for r in outcome.scenarios:
        lines += scenario_section(r, trip, airlines, shown)
    return "\n".join([*lines, "", FOOTER])


def entry(best: Itinerary, now: datetime, fiche: str, airlines: dict) -> dict:
    """Ce qu'on retient d'une offre dans etat.json (record ou meilleure offre du jour)."""
    return {"date": f"{now:%Y-%m-%d %H:%M}", "total": round(best.total), "score": round(best.score),
            "cle": best.key, "fiche": fiche, "resume": summary_line(best, airlines)}


def rules_id(trip, sc) -> str:
    """Empreinte des règles d'un scénario : si elles changent, son record ne compte plus."""
    rules = (sc, trip.origine, trip.destinations, trip.villes_differentes, trip.passagers,
             trip.bagages_soute, trip.duree_trajet_max_minutes, sorted(trip.compagnies_exclues))
    return hashlib.sha1(repr(rules).encode()).hexdigest()[:10]


def alert_message(news: list, trip, airlines: dict) -> str:
    """news : (scénario, meilleur voyage, ancien record ou None) des scénarios améliorés."""
    parts, shown = [], {}
    for sc, best, previous in news:
        head = f"**Nouveau meilleur prix — {sc.titre}**"
        if previous:
            counted = (f", compté {money(previous['score'])}"
                       if previous["score"] != previous["total"] else "")
            head += f" (précédent : {money(previous['total'])}{counted}, le {previous['date']})"
        if best.key in shown:
            parts.append(f"{head}\n\nLe même voyage qu'au scénario {shown[best.key]}.")
        else:
            shown[best.key] = sc.numero
            parts.append(f"{head}\n\n{card(best, trip, airlines)}")
    return "\n\n---\n\n".join([*parts, FOOTER])


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
    # Record et meilleure offre du jour de chaque scénario. Le record porte sur le classement
    # (prix + préférences de qualité). Un scénario dont les règles changent repart de zéro.
    for legacy in ("record", "jour"):  # état d'avant les scénarios
        state.pop(legacy, None)
    old, news = state.get("scenarios", {}), []
    state["scenarios"] = {}
    for r in outcome.scenarios:
        sc, number = r.scenario, str(r.scenario.numero)
        mine = old.get(number) or {}
        if mine.get("regles") != rules_id(trip, sc):
            mine = {"nom": sc.nom, "regles": rules_id(trip, sc)}
        state["scenarios"][number] = mine
        if not r.itineraries:
            continue
        best = r.itineraries[0]
        fiche, record = card(best, trip, airlines), mine.get("record")
        if record is None or best.score <= record["score"] - trip.alerte["baisse_min"]:
            news.append((sc, best, record))
            mine["record"] = entry(best, now, fiche, airlines)
        today = mine.get("jour")
        if not today or not today["date"].startswith(f"{now:%Y-%m-%d}") or best.score < today["score"]:
            mine["jour"] = entry(best, now, fiche, airlines)
    if news:
        post_alerte(trip, alert_message(news, trip, airlines))
    state["derniere_execution"] = now.isoformat(timespec="minutes")
    STATE.write_text(json.dumps(state, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
