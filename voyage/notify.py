"""Alertes par ticket GitHub : chaque commentaire déclenche un courriel de GitHub au
propriétaire du dépôt (mentionné pour être sûr d'être notifié)."""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request

log = logging.getLogger(__name__)
API = "https://api.github.com"


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

    def _issue(self, label: str, title: str, intro: str) -> int:
        found = self._call("GET", f"/issues?state=open&labels={label}&per_page=1")
        if found:
            return found[0]["number"]
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
