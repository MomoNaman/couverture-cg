"""Normalisation de texte avec correspondance vers le texte d'origine.

La vérification des citations compare des versions normalisées (sans accents,
apostrophes unifiées, espaces fusionnés, césures recollées), mais doit pouvoir
renvoyer le passage *exact* du document. On garde donc, pour chaque caractère
du texte normalisé, sa position dans le texte d'origine.
"""
from __future__ import annotations

import re
import unicodedata

_QUOTES = {
    "’": "'", "‘": "'", "ʼ": "'", "`": "'", "´": "'",
    "“": '"', "”": '"', "«": '"', "»": '"',
    "–": "-", "—": "-", "‑": "-", "­": "",
    "œ": "oe", "Œ": "oe", "æ": "ae", "Æ": "ae",
    " ": " ", " ": " ", " ": " ",
}


def _fold_char(ch: str) -> str:
    if ch in _QUOTES:
        return _QUOTES[ch]
    decomposed = unicodedata.normalize("NFKD", ch)
    out = "".join(c for c in decomposed if not unicodedata.combining(c))
    return out.lower()


def normalize_with_map(text: str) -> tuple[str, list[int]]:
    """Retourne (texte_normalisé, index) où index[i] = position d'origine du i-ème caractère."""
    out: list[str] = []
    idx: list[int] = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        # césure de fin de ligne : "effrac-\ntion" -> "effraction"
        if ch == "-" and i + 1 < n and text[i + 1] == "\n" and out and out[-1].isalpha():
            j = i + 1
            while j < n and text[j].isspace():
                j += 1
            if j < n and text[j].islower():
                i = j
                continue
        if ch == "\u00ab":                      # « guillemet ouvrant : on mange l'espace qui suit
            out.append('"')
            idx.append(i)
            i += 1
            while i < n and text[i] in " \u00a0\u202f\u2009":
                i += 1
            continue
        if ch == "\u00bb" and out and out[-1] == " ":   # espace avant » : retiré
            out.pop()
            idx.pop()
        if ch.isspace():
            if out and out[-1] != " ":
                out.append(" ")
                idx.append(i)
            i += 1
            continue
        for c in _fold_char(ch):
            if c.isspace():
                if out and out[-1] != " ":
                    out.append(" ")
                    idx.append(i)
            else:
                out.append(c)
                idx.append(i)
        i += 1
    # retire l'espace final éventuel
    while out and out[-1] == " ":
        out.pop()
        idx.pop()
    return "".join(out), idx


def normalize(text: str) -> str:
    return normalize_with_map(text)[0]


_PUNCT = re.compile(r"[\"'.,;:!?()\[\]…]+")


def loose(text: str) -> str:
    """Version encore plus tolérante (ponctuation ignorée), pour le repli flou."""
    return re.sub(r"\s+", " ", _PUNCT.sub(" ", normalize(text))).strip()
