"""Tableaux des conditions générales : une ligne = une unité de recherche.

Les CG impriment souvent leurs plafonds et franchises en tableau : une ligne par
garantie, des colonnes « garantie | plafond | franchise | condition ». Indexer le
tableau entier noie la ligne utile ; on indexe donc chaque ligne avec ses en-têtes
(« Garantie : Vol | Plafond : 10 % du capital | ... »), qui se lit comme une phrase
et se cite comme n'importe quel passage. Quand la recherche remonte la majorité
des lignes d'un même tableau, la question porte sur le tableau entier, et on
l'élargit (voir retrieve.elargir_tableaux).
"""
from __future__ import annotations

import re

from .models import Clause


def _clean(cell) -> str:
    return re.sub(r"\s+", " ", str(cell or "")).strip()


def fold_header(rows: list[list[str]]) -> tuple[list[str], list[list[str]]]:
    """En-tête sur deux lignes (cellule fusionnée) : on recopie le libellé vers la droite et on concatène."""
    head, body = rows[0], rows[1:]
    if "" in head and len(body) >= 2:
        filled, last = [], ""
        for h in head:
            last = h or last
            filled.append(last)
        sub = body[0]
        if not any(re.search(r"\d", c) for c in sub) and any(re.search(r"\d", c) for c in body[1]):
            return [f"{a} {b}".strip() for a, b in zip(filled, sub)], body[1:]
        head = filled
    return head, body


def table_rows(contrat_id: str, pages_tables: list[list[list[list]]], section_par_page: dict[int, list[str]],
               start: int) -> list[Clause]:
    """pages_tables[p] = tableaux de la page p+1, chacun liste de lignes de cellules."""
    out: list[Clause] = []
    tid = 0
    for pno, tables in enumerate(pages_tables, start=1):
        for t in tables:
            rows = [[_clean(c) for c in r] for r in t if r and any(_clean(c) for c in r)]
            if len(rows) < 2 or len(rows[0]) < 2:
                continue
            tid += 1
            head, body = fold_header(rows)
            head = [h or f"colonne {i + 1}" for i, h in enumerate(head)]
            for k, r in enumerate(body, start=1):
                texte = " | ".join(f"{h} : {c}" for h, c in zip(head, r) if c)
                if not texte:
                    continue
                out.append(Clause(
                    id=f"{contrat_id}-T{tid:02d}L{k:02d}", contrat_id=contrat_id, ordre=start + len(out),
                    page_debut=pno, page_fin=pno, numero=f"Tableau {tid}, ligne {k}",
                    titre=r[0][:80], section=section_par_page.get(pno, []), texte=texte,
                    types=["tableau"], renvois=[],
                ))
    return out


def pdf_tables(path) -> list[list[list[list]]]:
    import pdfplumber
    with pdfplumber.open(str(path)) as pdf:
        return [p.extract_tables() or [] for p in pdf.pages]
