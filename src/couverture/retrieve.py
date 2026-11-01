"""Recherche des clauses utiles à un sinistre.

Un sinistre se décompose en facettes : l'événement (vol, incendie...), le bien
(vélo, mobilier de jardin), le lieu (local commun, extérieur), les circonstances
(pas d'effraction, absence pendant les vacances). On cherche chaque facette
séparément, puis on complète par la structure du contrat, parce que les clauses
décisives ne partagent souvent aucun mot avec la question :

- les exclusions et conditions de la même section que la garantie trouvée ;
- le chapitre des exclusions générales ;
- les définitions des termes employés (« incendie », « dépendances », « effraction ») ;
- les clauses vers lesquelles renvoient les clauses retenues (« voir article 12 »).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .models import Clause
from .normalize import normalize
from .store import Store

# Lexique métier : facette -> concept -> formes à chercher (préfixes FTS5 avec *).
LEXIQUE: dict[str, dict[str, list[str]]] = {
    "evenement": {
        "vol": ["vol", "vole*", "derob*", "cambriol*", "effraction", "escalade", "fausses cles", "vandalisme"],
        "incendie": ["incendie", "feu", "flamme*", "embrasement", "combustion", "explosion"],
        "chaleur": ["chaleur", "brulure*", "roussi*", "fusion", "fondu*", "surchauffe", "bougie*", "rayonnement"],
        "degats_eaux": ["degat* des eaux", "fuite*", "infiltration*", "debordement*"],
        "climatique": ["tempete", "grele", "neige", "canicule", "intemperie*"],
        "bris": ["bris", "casse", "accidentel*"],
    },
    "bien": {
        "velo": ["velo*", "bicyclette*", "cycle*", "deux roues", "trottinette*", "engins de deplacement"],
        "mobilier_jardin": ["mobilier de jardin", "jardin", "mobilier exterieur", "terrasse", "biens exterieurs",
                            "plein air"],
        "contenu": ["contenu", "mobilier", "biens mobiliers", "objets"],
    },
    "lieu": {
        "communs": ["local commun", "locaux communs", "parties communes", "cave*", "garage*", "dependance*",
                    "local a velos", "parking*", "sous-sol"],
        "exterieur": ["exterieur", "en plein air", "jardin", "cour", "balcon", "terrasse", "non clos"],
        "habitation": ["habitation", "logement", "locaux d'habitation", "batiment"],
    },
    "circonstance": {
        "sans_effraction": ["effraction", "ferme* a cle", "verrouill*", "non ferme*", "porte ouverte",
                            "negligence", "mesures de prevention", "moyens de protection"],
        "absence": ["inoccupation", "inhabit*", "absence", "vacances", "jours consecutifs"],
    },
}

# Déclencheurs dans la question -> concepts activés
DECLENCHEURS: dict[str, list[str]] = {
    "vol": ["vol", "vole", "derob", "cambriol", "pique"],
    "incendie": ["incendie", "feu", "brule", "flamme"],
    "chaleur": ["bougie", "fond", "fondu", "chaleur", "brul", "soleil", "canicule"],
    "degats_eaux": ["eau", "fuite", "inond"],
    "velo": ["velo", "bicyclette", "vtt", "trottinette"],
    "mobilier_jardin": ["jardin", "terrasse", "table de jardin", "salon de jardin"],
    "communs": ["local commun", "parties communes", "cave", "garage", "local velo", "local a velo", "immeuble"],
    "exterieur": ["jardin", "dehors", "exterieur", "terrasse", "balcon"],
    "sans_effraction": ["pas ferme", "non ferme", "ouvert", "sans effraction", "pas verrouill"],
    "absence": ["vacances", "absent", "absence", "parti"],
}


@dataclass
class Contexte:
    contrat_id: str
    concepts: list[str]
    clauses: list[Clause]
    raisons: dict[str, list[str]] = field(default_factory=dict)  # clause_id -> pourquoi elle est là


def famille(c: Clause) -> str:
    """Article auquel appartient une clause : « 4 » pour 4.1, 4.2.3 ou Article 4."""
    if c.numero:
        m = re.search(r"(\d+)", c.numero)
        if m:
            return "n" + m.group(1)
    return "s" + (c.section[-1] if c.section else c.titre)


def detect_concepts(question: str) -> list[str]:
    q = normalize(question)
    found = [c for c, trig in DECLENCHEURS.items() if any(t in q for t in trig)]
    return found or ["contenu"]


def _fts(terms: list[str]) -> str:
    parts = []
    for t in terms:
        t = normalize(t).replace("'", " ")
        if " " in t.strip():
            parts.append('"' + t.replace("*", "").strip() + '"')
        else:
            parts.append(t)
    return " OR ".join(parts)


def _concept_terms(concept: str) -> list[str]:
    for fac in LEXIQUE.values():
        if concept in fac:
            return fac[concept]
    return [concept]


def retrieve(store: Store, contrat_id: str, question: str, extra_terms: list[str] | None = None,
             k_par_concept: int = 5, plafond: int = 28) -> Contexte:
    concepts = detect_concepts(question)
    raisons: dict[str, list[str]] = {}

    def add(cid: str, why: str):
        raisons.setdefault(cid, [])
        if why not in raisons[cid]:
            raisons[cid].append(why)

    # 1. une recherche par concept, plus les termes proposés par le LLM le cas échéant
    for c in concepts:
        for cid, _ in store.search(contrat_id, _fts(_concept_terms(c)), k_par_concept):
            add(cid, f"recherche : {c}")
    if extra_terms:
        for cid, _ in store.search(contrat_id, _fts(extra_terms), k_par_concept):
            add(cid, "recherche : reformulation")
    # croisement : clauses qui touchent deux concepts à la fois (ex. vélo ET local commun)
    for i, a in enumerate(concepts):
        for b in concepts[i + 1:]:
            q = f"({_fts(_concept_terms(a))}) AND ({_fts(_concept_terms(b))})"
            for cid, _ in store.search(contrat_id, q, 4):
                add(cid, f"croisement : {a} × {b}")

    toutes = store.clauses(contrat_id)
    par_id = {c.id: c for c in toutes}

    # 2. structure : exclusions / conditions du même article (4.1, 4.2, 4.3 ; Article 4)
    familles = {famille(par_id[cid]) for cid in raisons if cid in par_id}
    for c in toutes:
        if famille(c) in familles and set(c.types) & {"exclusion", "condition", "franchise", "obligation"}:
            add(c.id, "même article : exclusion/condition")
    # exclusions générales
    for c in toutes:
        lbl = normalize(c.section_label)
        if "exclusion" in lbl and ("general" in lbl or "commun" in lbl):
            add(c.id, "exclusions générales")

    # 3. définitions des termes présents dans la question et les clauses retenues
    lex = store.definitions(contrat_id)
    corpus = normalize(question + " " + " ".join(par_id[c].texte for c in raisons if c in par_id))
    for terme, cid in lex.items():
        if re.search(r"\b" + re.escape(terme) + r"\b", corpus):
            add(cid, f"définition : {terme}")

    # 4. renvois explicites
    for cid in list(raisons):
        cl = par_id.get(cid)
        for num in (cl.renvois if cl else []):
            for cible in store.by_numero(contrat_id, num):
                add(cible.id, f"renvoi depuis {cl.numero or cl.id}")

    # priorité : recherche directe > structure > définitions ; puis ordre du document
    def prio(cid: str) -> tuple:
        r = raisons[cid]
        rang = 0 if any(x.startswith(("recherche", "croisement")) for x in r) else \
            1 if any(x.startswith(("définition", "renvoi")) for x in r) else 2
        return (rang, -len(r))

    retenus = sorted(raisons, key=prio)[:plafond]
    clauses = sorted((par_id[c] for c in retenus if c in par_id), key=lambda c: c.ordre)
    return Contexte(contrat_id, concepts, clauses, {c.id: raisons[c.id] for c in clauses})
