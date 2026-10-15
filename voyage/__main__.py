"""Point d'entrée : python -m voyage [--essai]"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from voyage.config import ROOT, load_airlines, load_trip
from voyage.gflights import GoogleFlights
from voyage.notify import PANNE, notifier
from voyage.pricing import Itinerary
from voyage.search import Searcher

DATA = ROOT / "data"
STATE = DATA / "etat.json"
HISTORY = DATA / "historique.csv"
REPORT = DATA / "dernier_resultat.md"
TZ = ZoneInfo("America/Toronto")
CITY = {"LIS": "Lisbonne", "OPO": "Porto", "FAO": "Faro", "YUL": "Montréal"}

log = logging.getLogger("voyage")


def money(amount: float) -> str:
    return f"{amount:,.0f} $".replace(",", " ")


def city(code: str) -> str:
    return CITY.get(code, code)


def describe(i: Itinerary, rank: int) -> str:
    cities = " → ".join(dict.fromkeys([city(i.out.dest), city(i.ret.origin)]))
    stops = "direct" if i.stops == 0 else f"{i.stops} escale(s)"
    links = " · ".join(f"[lien {n}]({u})" for n, u in enumerate(i.links, 1)) if len(i.links) > 1 \
        else f"[voir sur Google Flights]({i.links[0]})" if i.links else ""
    out = [
        f"{rank}. **{money(i.total)}** — {i.kind}, {cities}, "
        f"{i.out.legs[0].dep:%d/%m} → {i.ret.legs[-1].arr:%d/%m}, {stops}",
        f"   - Aller : {i.out.describe()}",
        f"   - Retour : {i.ret.describe()}",
        *(f"   - {line}" for line in i.lines),
    ]
    if links:
        out.append(f"   - {links}")
    return "\n".join(out)


def report(trip, outcome, now: datetime) -> str:
    top = outcome.itineraries[: trip.alerte["top"]]
    lines = [
        f"## {trip.nom} — {now:%Y-%m-%d %H:%M} (heure de Montréal)",
        "",
        f"{trip.passagers} passagers, {trip.bagages_soute} valises en soute, "
        f"{outcome.requests} pages Google Flights consultées, {len(outcome.errors)} échec(s).",
        "",
        *(describe(i, n) + "\n" for n, i in enumerate(top, 1)),
        *two_cities_section(outcome, top),
        "_Total = prix Google Flights taxes incluses + valises selon le tarif le plus avantageux "
        "de chaque compagnie (`config/compagnies.yaml`). Classement : certaines compagnies sont "
        "comptées plus cher pour leur qualité (`penalite_qualite`), le prix affiché reste le vrai. Les montants « estimé » viennent des "
        "règles des compagnies : vérifier le prix final sur leur site avant d'acheter. "
        "« multi-villes (estimé) » = à réserver en « multi-destinations » sur le site de la "
        "compagnie ; « 2 allers simples » = deux billets séparés._",
    ]
    return "\n".join(lines)


def two_cities_section(outcome, top) -> list[str]:
    best = outcome.best_two_cities
    if best is None or best in top:
        return []
    note = "" if best in outcome.itineraries else \
        " (écartée : l'escale ne fait pas économiser assez par rapport au meilleur direct)"
    return [f"**Pour info — meilleure option arrivée et départ de villes différentes**{note} :",
            "", describe(best, 0).replace("0. ", "", 1) + "\n"]


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
    text = report(trip, outcome, now)
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
                f"### Nouveau meilleur choix : {money(best.total)}{previous}\n\n{text}")
        state["record"] = {"total": round(best.total), "score": round(best.score),
                           "cle": best.key, "date": f"{now:%Y-%m-%d %H:%M}"}
    state["derniere_execution"] = now.isoformat(timespec="minutes")
    STATE.write_text(json.dumps(state, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
