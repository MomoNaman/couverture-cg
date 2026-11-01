"""Accès au modèle, sans dépendance : HTTP direct.

Configuration par variables d'environnement :
  LLM_PROVIDER = anthropic | openai | azure | replay
  LLM_MODEL    = nom du modèle (ou du déploiement Azure)
  LLM_API_KEY  = clé
  LLM_BASE_URL = optionnel (endpoint compatible OpenAI, ou ressource Azure)
  LLM_REPLAY_DIR = pour `replay` : dossier de réponses enregistrées (tests, démo hors ligne)

Toutes les réponses brutes sont journalisées dans out/llm_log.jsonl.
"""
from __future__ import annotations

import hashlib
import json
import os
import urllib.request
from pathlib import Path


class LLMError(RuntimeError):
    pass


class LLM:
    def __init__(self, provider: str | None = None, model: str | None = None):
        self.provider = (provider or os.getenv("LLM_PROVIDER", "anthropic")).lower()
        self.model = model or os.getenv("LLM_MODEL", "claude-sonnet-5-5")
        self.key = os.getenv("LLM_API_KEY", "")
        self.base = os.getenv("LLM_BASE_URL", "")
        self.replay_dir = Path(os.getenv("LLM_REPLAY_DIR", "tests/replay"))
        self.log = Path(os.getenv("LLM_LOG", "out/llm_log.jsonl"))

    @staticmethod
    def key_for(system: str, user: str) -> str:
        return hashlib.sha256((system + "\n---\n" + user).encode()).hexdigest()[:16]

    def complete_json(self, system: str, user: str, max_tokens: int = 3000) -> dict:
        h = self.key_for(system, user)
        if self.provider == "replay":
            f = self.replay_dir / f"{h}.json"
            if not f.exists():
                raise LLMError(f"pas de réponse enregistrée pour {h} dans {self.replay_dir}")
            raw = f.read_text(encoding="utf-8")
        else:
            if not self.key:
                raise LLMError("LLM_API_KEY manquant")
            raw = getattr(self, f"_{self.provider}")(system, user, max_tokens)
            self.log.parent.mkdir(parents=True, exist_ok=True)
            with self.log.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({"hash": h, "model": self.model, "raw": raw}, ensure_ascii=False) + "\n")
        return parse_json(raw)

    # --- fournisseurs -------------------------------------------------------
    def _post(self, url: str, headers: dict, payload: dict) -> dict:
        req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            raise LLMError(f"HTTP {e.code} : {e.read()[:400]!r}") from e

    def _anthropic(self, system: str, user: str, max_tokens: int) -> str:
        url = (self.base or "https://api.anthropic.com") + "/v1/messages"
        d = self._post(url, {"x-api-key": self.key, "anthropic-version": "2023-06-01",
                             "content-type": "application/json"},
                       {"model": self.model, "max_tokens": max_tokens, "temperature": 0,
                        "system": system, "messages": [{"role": "user", "content": user}]})
        return "".join(b.get("text", "") for b in d.get("content", []))

    def _openai(self, system: str, user: str, max_tokens: int) -> str:
        url = (self.base or "https://api.openai.com/v1") + "/chat/completions"
        d = self._post(url, {"authorization": f"Bearer {self.key}", "content-type": "application/json"},
                       {"model": self.model, "max_tokens": max_tokens, "temperature": 0,
                        "response_format": {"type": "json_object"},
                        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})
        return d["choices"][0]["message"]["content"]

    def _azure(self, system: str, user: str, max_tokens: int) -> str:
        version = os.getenv("AZURE_API_VERSION", "2024-10-21")
        url = f"{self.base.rstrip('/')}/openai/deployments/{self.model}/chat/completions?api-version={version}"
        d = self._post(url, {"api-key": self.key, "content-type": "application/json"},
                       {"max_tokens": max_tokens, "temperature": 0, "response_format": {"type": "json_object"},
                        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})
        return d["choices"][0]["message"]["content"]


def parse_json(raw: str) -> dict:
    s = raw.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1].rsplit("```", 1)[0]
    a, b = s.find("{"), s.rfind("}")
    if a < 0 or b < 0:
        raise LLMError(f"réponse non JSON : {raw[:200]!r}")
    return json.loads(s[a:b + 1])
