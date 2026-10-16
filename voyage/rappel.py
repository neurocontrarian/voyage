"""Rappel quotidien (17 h) : meilleure offre de tous les temps et meilleure offre du jour,
même quand aucun nouveau record n'est tombé. Ne lance aucune recherche : lit data/etat.json.

    python -m voyage.rappel
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from voyage import tendances
from voyage.config import ROOT, load_trip
from voyage.notify import notifier

DATA = ROOT / "data"
TZ = ZoneInfo("America/Toronto")
FOOTER = "_Vérifier le prix sur le site de la compagnie avant d'acheter._"


def money(amount: float) -> str:
    return f"{amount:,.0f} $".replace(",", " ")


def section(title: str, entry: dict | None, when: str) -> str:
    if not entry:
        return f"#### {title}\n\nAucune donnée."
    return f"#### {title} ({when})\n\n{entry.get('fiche') or '### ' + money(entry['total']) + ' tout compris'}"


def message(state: dict, now: datetime, trends: str) -> str:
    record, today = state.get("record"), state.get("jour")
    if today and today["date"] != f"{now:%Y-%m-%d}":
        today = None  # aucune recherche réussie aujourd'hui
    if today and record and today["cle"] == record["cle"] and today["total"] == record["total"]:
        body = section("Meilleure offre — de tous les temps ET d'aujourd'hui", record,
                       f"trouvée le {record['date']}")
    else:
        body = "\n\n".join([
            section("Meilleure offre de tous les temps", record,
                    f"trouvée le {record['date']}" if record else ""),
            section("Meilleure offre d'aujourd'hui", today, f"à {today['heure']}" if today else "")
            if today else "#### Meilleure offre d'aujourd'hui\n\nAucune recherche réussie aujourd'hui."])
    return f"**Rappel de 17 h**\n\n{body}\n\n{trends}\n\n{FOOTER}"


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        state = json.loads((DATA / "etat.json").read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        state = {}
    if not state.get("record"):
        logging.info("Pas encore de résultat : pas de rappel")
        return 0
    now = datetime.now(TZ)
    trip = load_trip()
    tendances.TRENDS.write_text(tendances.report())
    notifier().post("alerte-prix", f"✈️ Alertes prix — {trip.nom}",
                    "Un commentaire est ajouté ici chaque fois qu'un meilleur prix apparaît, "
                    "et un rappel chaque jour à 17 h.",
                    message(state, now, tendances.advice()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
