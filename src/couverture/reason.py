"""Analyse d'un sinistre : recherche -> raisonnement -> vérification."""
from __future__ import annotations

from .llm import LLM, LLMError
from .models import Citation, Clause, Etape, Reponse
from .prompts import SYSTEM_ANALYSE, SYSTEM_EXPANSION, user_analyse
from .retrieve import Contexte, retrieve
from .store import Store
from .verify import verify

VERDICTS = {"couvert", "couvert_sous_conditions", "non_couvert", "indetermine"}


def format_clauses(clauses: list[Clause]) -> str:
    blocs = []
    for c in clauses:
        types = ", ".join(c.types)
        pages = f"p. {c.page_debut}" + (f"-{c.page_fin}" if c.page_fin != c.page_debut else "")
        blocs.append(f"[{c.id}] ({pages} ; {types}) {c.section_label}\n{c.texte}")
    return "\n\n---\n\n".join(blocs)


def expand(llm: LLM | None, question: str) -> list[str]:
    if llm is None:
        return []
    try:
        return [t for t in llm.complete_json(SYSTEM_EXPANSION, question, 400).get("termes", []) if isinstance(t, str)]
    except (LLMError, ValueError):
        return []


def parse_reponse(d: dict, question: str, contrat_id: str) -> Reponse:
    v = d.get("verdict", "indetermine")
    v = v if v in VERDICTS else "indetermine"
    etapes = [Etape(affirmation=e.get("affirmation", ""),
                    citations=[Citation(clause_id=c.get("clause_id", ""), extrait=c.get("extrait", ""))
                               for c in e.get("citations", []) if isinstance(c, dict)])
              for e in d.get("etapes", []) if isinstance(e, dict)]
    ambig = []
    for a in d.get("ambiguites", []):
        if isinstance(a, dict):
            ambig.append(("[décisif] " if a.get("decisive") else "") + a.get("texte", ""))
        elif isinstance(a, str):
            ambig.append(a)
    return Reponse(question=question, contrat_id=contrat_id, verdict=v, verdict_modele=v,
                   resume=d.get("resume", ""), etapes=etapes, ambiguites=ambig,
                   informations_manquantes=[str(x) for x in d.get("informations_manquantes", [])],
                   exclusions_examinees=[str(x) for x in d.get("exclusions_examinees", [])])


def analyser(store: Store, llm: LLM, contrat_id: str, question: str, expansion: bool = True) -> tuple[Reponse, Contexte]:
    contrat = store.contrat(contrat_id)
    ctx = retrieve(store, contrat_id, question, extra_terms=expand(llm, question) if expansion else None)
    label = f"{contrat.assureur} — {contrat.produit}" + (f" (édition {contrat.edition})" if contrat.edition else "")
    d = llm.complete_json(SYSTEM_ANALYSE, user_analyse(question, label, format_clauses(ctx.clauses)))
    rep = parse_reponse(d, question, contrat_id)
    rep.clauses_consultees = [c.id for c in ctx.clauses]
    rep = verify(rep, {c.id: c for c in ctx.clauses})
    store.save_reponse(rep)
    return rep, ctx
