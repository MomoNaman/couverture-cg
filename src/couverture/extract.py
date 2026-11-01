"""Tenir des centaines de contrats : extraire une fois, interroger en SQL.

On ne relit pas des centaines de PDF à chaque question. À l'ingestion, chaque
contrat passe une grille fixe de garanties ; la fiche obtenue (statut,
conditions, plafond, franchise, exclusions), avec ses citations vérifiées,
devient une ligne de la table `garanties`. Les questions de portefeuille
(« quels contrats couvrent le vol de vélo dans les parties communes ? ») sont
alors des requêtes SQL, et l'analyse fine d'un sinistre ne relit qu'un contrat.
"""
from __future__ import annotations

import json

from .llm import LLM, LLMError
from .prompts import SYSTEM_EXTRACTION
from .reason import format_clauses
from .retrieve import retrieve
from .store import Store
from .verify import locate

GRILLE: dict[str, str] = {
    "vol": "vol avec effraction dans l'habitation",
    "vol_dependances": "vol dans une cave, un garage ou un local commun de l'immeuble",
    "velo": "vol ou dommage d'un vélo ou d'un engin de déplacement",
    "incendie": "incendie, explosion, fumée",
    "chaleur_sans_flamme": "dommage dû à la chaleur, brûlure ou fusion sans incendie",
    "biens_exterieurs": "mobilier de jardin et biens laissés à l'extérieur",
    "degats_eaux": "dégât des eaux",
    "inoccupation": "inoccupation prolongée du logement, absence pendant les vacances",
    "bris_glace": "bris de glace",
    "responsabilite_civile": "responsabilité civile vie privée",
}


def extraire_contrat(store: Store, llm: LLM, contrat_id: str) -> list[dict]:
    lignes = []
    for gid, description in GRILLE.items():
        ctx = retrieve(store, contrat_id, description, plafond=16)
        par_id = {c.id: c for c in ctx.clauses}
        try:
            d = llm.complete_json(SYSTEM_EXTRACTION, f"Garantie : {description}\n\n{format_clauses(ctx.clauses)}", 1500)
        except LLMError as e:
            d = {"statut": "erreur", "conditions": [str(e)], "citations": []}
        cits = []
        for c in d.get("citations", []):
            cl = par_id.get(c.get("clause_id", ""))
            loc = locate(c.get("extrait", ""), cl) if cl else None
            if loc:
                cits.append(loc.__dict__)
        verifiee = int(bool(cits)) if d.get("statut") != "absente_des_extraits" else 1
        ligne = dict(contrat_id=contrat_id, garantie=gid, statut=d.get("statut"),
                     conditions=json.dumps(d.get("conditions") or [], ensure_ascii=False),
                     plafond=d.get("plafond"), franchise=d.get("franchise"),
                     exclusions=json.dumps(d.get("exclusions") or [], ensure_ascii=False),
                     citations=json.dumps(cits, ensure_ascii=False), verifiee=verifiee)
        store.db.execute("INSERT OR REPLACE INTO garanties VALUES (:contrat_id,:garantie,:statut,:conditions,"
                         ":plafond,:franchise,:exclusions,:citations,:verifiee)", ligne)
        lignes.append(ligne)
    store.db.commit()
    return lignes
