"""Export JSON pour l'interface statique (GitHub Pages, sans serveur ni clé)."""
from __future__ import annotations

import json
from pathlib import Path

from .retrieve import retrieve
from .store import Store


def _derniere_reponse(store: Store, contrat_id: str, question: str) -> dict | None:
    r = store.db.execute("SELECT json FROM reponses WHERE contrat_id=? AND question=? ORDER BY id DESC LIMIT 1",
                         (contrat_id, question)).fetchone()
    return json.loads(r["json"]) if r else None


def export(store: Store, questions: list[dict], out: str, analyser: bool = False) -> int:
    llm = None
    if analyser:
        from .llm import LLM
        from .reason import analyser as analyse
        llm = LLM()
    contrats = store.contrats()
    clauses_utiles: dict[str, dict] = {}
    cas = []
    n = 0
    for q in questions:
        for c in contrats:
            ctx = retrieve(store, c.id, q["texte"])
            rep = None
            if llm is not None:
                rep = analyse(store, llm, c.id, q["texte"])[0].to_dict()
            else:
                rep = _derniere_reponse(store, c.id, q["texte"])
            n += rep is not None
            for cl in ctx.clauses:
                clauses_utiles[cl.id] = {**cl.to_dict(), "section_label": cl.section_label}
            cas.append({"question_id": q["id"], "contrat_id": c.id,
                        "recherche": [{"clause_id": cl.id, "raisons": ctx.raisons[cl.id]} for cl in ctx.clauses],
                        "concepts": ctx.concepts, "analyse": rep})
    data = {"contrats": [c.__dict__ for c in contrats], "questions": questions,
            "clauses": clauses_utiles, "cas": cas}
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return n
