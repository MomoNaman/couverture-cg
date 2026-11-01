"""Vérification : rien n'est montré à l'utilisateur sans avoir été retrouvé dans le contrat.

1. Chaque citation doit être retrouvée dans la clause indiquée : à l'identique,
   puis après normalisation (accents, apostrophes, espaces, césures), puis, en
   dernier recours, par alignement flou à 92 % minimum. Le passage affiché est
   alors celui du document, pas celui du modèle.
2. Une citation introuvable est retirée et signalée.
3. Le verdict est recalculé selon des règles explicites :
   - « couvert » exige au moins une citation vérifiée d'une clause de garantie,
     et la mention des exclusions examinées ;
   - « non couvert » exige une exclusion ou une condition citée et vérifiée :
     l'absence d'une garantie dans les extraits lus ne vaut pas exclusion ;
   - une ambiguïté marquée décisive, ou une information manquante qui change
     l'issue, ramène le verdict à « indéterminé ».
"""
from __future__ import annotations

from difflib import SequenceMatcher

from .models import Citation, Clause, Reponse
from .normalize import loose, normalize, normalize_with_map

SEUIL_FLOU = 0.92


def locate(extrait: str, clause: Clause) -> Citation | None:
    """Retrouve `extrait` dans le texte de la clause ; renvoie les offsets d'origine."""
    texte = clause.texte
    e = extrait.strip().strip('"«» ')
    if not e:
        return None
    # 1. exact
    i = texte.find(e)
    if i >= 0:
        return _cit(clause, e, i, i + len(e), "exacte")
    # 2. normalisé, avec retour aux positions d'origine
    nt, idx = normalize_with_map(texte)
    ne = normalize(e)
    j = nt.find(ne)
    if j >= 0 and ne:
        a, b = idx[j], idx[j + len(ne) - 1] + 1
        return _cit(clause, texte[a:b], a, b, "normalisee")
    # 3. flou : meilleure fenêtre de même longueur (en mots)
    if len(ne) < 25:
        return None          # trop court pour un rapprochement flou fiable
    words_t = nt.split(" ")
    n = len(ne.split(" "))
    target = loose(e)
    best, best_pos = 0.0, None
    starts = [0]
    for w in words_t[:-1]:
        starts.append(starts[-1] + len(w) + 1)
    for k in range(0, max(1, len(words_t) - n + 1)):
        for span in (n - 1, n, n + 1):
            if span <= 0 or k + span > len(words_t):
                continue
            cand = " ".join(words_t[k:k + span])
            r = SequenceMatcher(None, loose(cand), target, autojunk=False).ratio()
            if r > best:
                best, best_pos = r, (starts[k], starts[k] + len(cand))
    if best >= SEUIL_FLOU and best_pos:
        a, b = idx[best_pos[0]], idx[best_pos[1] - 1] + 1
        return _cit(clause, texte[a:b], a, b, f"floue ({best:.0%})")
    return None


def _cit(clause: Clause, source: str, a: int, b: int, methode: str) -> Citation:
    # page approximative : si la clause s'étend sur plusieurs pages, on interpole
    page = clause.page_debut
    if clause.page_fin > clause.page_debut and clause.texte:
        page = clause.page_debut + round((clause.page_fin - clause.page_debut) * a / len(clause.texte))
    return Citation(clause_id=clause.id, extrait=source, verifiee=True, extrait_source=source,
                    page=page, debut=a, fin=b, methode=methode)


def verify(rep: Reponse, clauses: dict[str, Clause]) -> Reponse:
    alertes: list[str] = []
    types_cites: set[str] = set()
    n_ok = n_ko = 0

    for etape in rep.etapes:
        gardees = []
        for c in etape.citations:
            clause = clauses.get(c.clause_id)
            if clause is None:
                n_ko += 1
                alertes.append(f"Citation rejetée : la clause {c.clause_id} n'a pas été fournie au modèle.")
                continue
            loc = locate(c.extrait, clause)
            if loc is None:
                n_ko += 1
                alertes.append(f"Citation rejetée ({c.clause_id}) : passage introuvable dans le contrat — « {c.extrait[:90]} »")
                continue
            n_ok += 1
            types_cites.update(clause.types)
            gardees.append(loc)
        etape.citations = gardees
        if not gardees:
            alertes.append(f"Affirmation sans appui vérifié : « {etape.affirmation[:110]} »")

    verdict = rep.verdict_modele
    if verdict in ("couvert", "couvert_sous_conditions"):
        if "garantie" not in types_cites:
            verdict = "indetermine"
            alertes.append("Verdict ramené à « indéterminé » : aucune clause de garantie n'est citée et vérifiée.")
        elif not rep.exclusions_examinees:
            verdict = "indetermine"
            alertes.append("Verdict ramené à « indéterminé » : les exclusions n'ont pas été examinées.")
    elif verdict == "non_couvert":
        if not types_cites & {"exclusion", "condition", "definition"}:
            verdict = "indetermine"
            alertes.append("Verdict ramené à « indéterminé » : aucune exclusion, condition ou définition "
                           "citée et vérifiée. Ne pas trouver la garantie ne prouve pas qu'elle n'existe pas.")
    decisives = [a for a in rep.ambiguites if a.lower().startswith(("décisif", "decisif", "[décisif]", "[decisif]"))]
    if decisives and verdict != "indetermine":
        verdict = "indetermine"
        alertes.append("Verdict ramené à « indéterminé » : une ambiguïté décisive est relevée dans le contrat.")
    if n_ok == 0 and verdict != "indetermine":
        verdict = "indetermine"
        alertes.append("Verdict ramené à « indéterminé » : aucune citation n'a pu être vérifiée.")

    rep.verdict = verdict
    rep.alertes = alertes + rep.alertes
    return rep
