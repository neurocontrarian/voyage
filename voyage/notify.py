"""Alertes par ticket GitHub : chaque commentaire déclenche un courriel de GitHub au
propriétaire du dépôt (mentionné pour être sûr d'être notifié).

La recherche tourne sur un serveur à Montréal. Si elle publiait avec le compte du
propriétaire, GitHub ne lui enverrait aucun courriel (on n'est jamais notifié de ses propres
messages). Le serveur dépose donc ses alertes dans ``data/a_publier/``, et le workflow
« Alertes » les publie avec le robot de GitHub Actions. Ce workflow sert aussi de veilleur :
il signale une panne si le serveur n'a rien publié depuis plusieurs heures.

    python -m voyage.notify publier
    python -m voyage.notify veille --heures 3
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)
API = "https://api.github.com"
DATA = Path(__file__).resolve().parent.parent / "data"
OUTBOX = DATA / "a_publier"
PANNE = ("panne", "⚠️ La surveillance des prix ne fonctionne plus",
         "Ce ticket signale les pannes du programme. Le fermer une fois le problème réglé.")


ALERTE = ("alerte-prix", "✈️ Alertes prix — {nom}",
          "Un commentaire est ajouté ici chaque fois qu'un meilleur prix apparaît, "
          "et un rappel chaque jour à 17 h.")


def post_alerte(trip, message: str) -> None:
    """Publie (ou dépose) un commentaire sur le ticket des alertes de prix."""
    label, title, intro = ALERTE
    notifier().post(label, title.format(nom=trip.nom), intro, message)


class GitHubIssues:
    def __init__(self, repo: str, token: str, owner: str):
        self.repo, self.token, self.owner = repo, token, owner

    @classmethod
    def from_env(cls) -> GitHubIssues | None:
        repo, token = os.environ.get("GITHUB_REPOSITORY"), os.environ.get("GITHUB_TOKEN")
        if not repo or not token:
            return None
        return cls(repo, token, os.environ.get("GITHUB_REPOSITORY_OWNER", repo.split("/")[0]))

    def _call(self, method: str, path: str, body: dict | None = None):
        req = urllib.request.Request(
            f"{API}/repos/{self.repo}{path}",
            method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read() or "null")

    def open_issue(self, label: str) -> int | None:
        found = self._call("GET", f"/issues?state=open&labels={label}&per_page=1")
        return found[0]["number"] if found else None

    def _issue(self, label: str, title: str, intro: str) -> int:
        number = self.open_issue(label)
        if number:
            return number
        try:
            self._call("POST", "/labels", {"name": label, "color": "1d76db"})
        except urllib.error.HTTPError:
            pass  # l'étiquette existe déjà
        issue = self._call("POST", "/issues", {"title": title, "body": intro, "labels": [label]})
        return issue["number"]

    def post(self, label: str, title: str, intro: str, message: str) -> None:
        number = self._issue(label, title, intro)
        self._call("POST", f"/issues/{number}/comments", {"body": f"@{self.owner}\n\n{message}"})
        log.info("Alerte publiée sur le ticket #%s", number)


class Outbox:
    """Dépose l'alerte dans data/a_publier/ ; le workflow « Alertes » la publiera."""

    def post(self, label: str, title: str, intro: str, message: str) -> None:
        OUTBOX.mkdir(parents=True, exist_ok=True)
        path = OUTBOX / f"{time.strftime('%Y%m%d-%H%M%S')}-{label}.json"
        path.write_text(json.dumps(
            {"label": label, "title": title, "intro": intro, "message": message},
            ensure_ascii=False, indent=2))
        log.info("Alerte déposée dans %s", path.relative_to(DATA.parent))


def notifier() -> GitHubIssues | Outbox:
    return GitHubIssues.from_env() or Outbox()


def publish(gh: GitHubIssues) -> int:
    count = 0
    for path in sorted(OUTBOX.glob("*.json")):
        alert = json.loads(path.read_text())
        gh.post(alert["label"], alert["title"], alert["intro"], alert["message"])
        path.unlink()
        count += 1
    return count


def watch(gh: GitHubIssues, hours: float) -> None:
    try:
        state = json.loads((DATA / "etat.json").read_text())
        last = datetime.fromisoformat(state["derniere_execution"])
    except (FileNotFoundError, KeyError, ValueError):
        return  # pas encore de première exécution
    late = (datetime.now(timezone.utc) - last).total_seconds() / 3600
    if late < hours or gh.open_issue(PANNE[0]):
        return
    gh.post(*PANNE, f"Aucune recherche réussie depuis {late:.0f} h (dernière : {last:%Y-%m-%d %H:%M}). "
                    "Vérifier que le serveur est allumé et le journal `serveur.log`.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["publier", "veille"])
    parser.add_argument("--heures", type=float, default=3)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    gh = GitHubIssues.from_env()
    if gh is None:
        log.error("GITHUB_REPOSITORY et GITHUB_TOKEN sont nécessaires")
        return 1
    if args.action == "publier":
        log.info("%d alerte(s) publiée(s)", publish(gh))
    else:
        watch(gh, args.heures)
    return 0


if __name__ == "__main__":
    sys.exit(main())
