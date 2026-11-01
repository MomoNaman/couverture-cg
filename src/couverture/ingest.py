"""Du PDF aux clauses.

On ne découpe pas le contrat en blocs de N tokens : on reconstruit sa structure
(titres numérotés, articles, chapitres), parce qu'une clause d'assurance ne se
comprend qu'avec son titre, sa section et ses renvois. Chaque clause garde sa
page, pour être citée et vérifiée.
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from .models import Clause, Contrat
from .normalize import normalize

# --------------------------------------------------------------------------- PDF

def pdf_pages(path: str | Path) -> list[str]:
    """Texte page par page, en traitant les mises en page à deux colonnes."""
    import pdfplumber

    pages: list[str] = []
    with pdfplumber.open(str(path)) as pdf:
        for page in pdf.pages:
            pages.append(_page_text(page))
    return pages


def _page_text(page) -> str:
    words = page.extract_words(keep_blank_chars=False, use_text_flow=False)
    if not words:
        return ""
    mid = page.width / 2
    crossing = sum(1 for w in words if w["x0"] < mid - 5 and w["x1"] > mid + 5)
    left = sum(1 for w in words if w["x1"] <= mid)
    right = sum(1 for w in words if w["x0"] >= mid)
    two_cols = crossing < 0.03 * len(words) and left > 0.25 * len(words) and right > 0.25 * len(words)
    if two_cols:
        l = page.crop((0, 0, mid, page.height)).extract_text() or ""
        r = page.crop((mid, 0, page.width, page.height)).extract_text() or ""
        return l + "\n" + r
    return page.extract_text() or ""


def text_pages(path: str | Path) -> list[str]:
    """Fichier texte : les pages sont séparées par un saut de page (\\f)."""
    return Path(path).read_text(encoding="utf-8").split("\f")


# ------------------------------------------------------------- en-têtes / pieds

def strip_running_lines(pages: list[str], seuil: float = 0.4) -> list[str]:
    """Retire les lignes répétées sur une large part des pages (en-têtes, pieds, n° de page)."""
    if len(pages) < 4:
        return pages

    def key(line: str) -> str:
        return re.sub(r"\d+", "#", normalize(line)).strip()

    counts = Counter()
    for p in pages:
        counts.update({key(l) for l in p.splitlines() if l.strip()})
    repeated = {k for k, c in counts.items() if c >= seuil * len(pages) and len(k) < 120}
    pagenum = re.compile(r"^\s*(page\s*)?#(\s*/\s*#|\s*sur\s*#)?\s*$")
    out = []
    for p in pages:
        lines = [l for l in p.splitlines()
                 if l.strip() and key(l) not in repeated and not pagenum.match(key(l))]
        out.append("\n".join(lines))
    return out


# ------------------------------------------------------------------- structure

_HEAD_PATTERNS = [
    # Article 12 – Vol / ARTICLE 3 : / Art. 4
    re.compile(r"^(?P<num>(?:article|art\.)\s*\d+[a-z]?(?:\.\d+)*)\s*[-–:.)]?\s*(?P<titre>.{0,90})$", re.I),
    # Chapitre II / Titre 3 / Section 1
    re.compile(r"^(?P<num>(?:chapitre|titre|section|partie)\s+[\dIVXLC]+)\s*[-–:.)]?\s*(?P<titre>.{0,90})$", re.I),
    # 1.8.1 Vol, actes de vandalisme
    re.compile(r"^(?P<num>\d{1,2}(?:\.\d{1,2}){1,4})\.?\s+(?P<titre>[A-ZÀ-Ý«\"].{0,90})$"),
    # 5. LES EXCLUSIONS / 5) Dégâts des eaux
    re.compile(r"^(?P<num>\d{1,2})[.)]\s+(?P<titre>[A-ZÀ-Ý].{2,80})$"),
]


def _match_heading(line: str):
    s = line.strip()
    if len(s) > 110 or s.endswith((",", ";")):
        return None
    for pat in _HEAD_PATTERNS:
        m = pat.match(s)
        if m:
            titre = m.group("titre").strip(" -–:.")
            # une phrase longue qui commence par "1. " est un item de liste, pas un titre
            if len(titre.split()) > 12 and titre[-1:] == ".":
                return None
            return m.group("num").strip(), titre
    # TITRE EN CAPITALES seul sur sa ligne
    letters = [c for c in s if c.isalpha()]
    if 4 <= len(letters) and len(s) <= 70 and sum(c.isupper() for c in letters) / len(letters) > 0.9 \
            and len(s.split()) <= 8:
        return None, s.title() if s.isupper() else s
    return None


def _depth(num: str | None) -> int:
    """Profondeur dans l'arbre : titres en capitales et chapitres en haut, puis articles et sous-points."""
    if not num:
        return 0
    n = normalize(num)
    if n.startswith(("partie", "titre", "chapitre")):
        return 0
    if n.startswith("section"):
        return 1
    if n.startswith(("article", "art")):
        return 1 + n.count(".")
    return 1 + n.count(".")


_TYPE_RULES: list[tuple[str, list[str], int]] = [
    # (type, mots-clés, nombre d'occurrences requis dans le corps si le titre ne les contient pas)
    ("definition", ["definition", "on entend par", "au sens du present contrat", "lexique", "glossaire"], 1),
    ("exclusion", ["exclu", "ne sont pas garanti", "ne garantissons pas", "ne couvre pas", "ne couvrons pas",
                   "n'est pas garanti", "ne sont jamais", "ne sont pas couvert", "n'est pas couvert"], 1),
    ("garantie", ["nous garantissons", "l'assureur garantit", "est garanti", "sont garantis", "nous couvrons",
                  "nous indemnisons", "nous prenons en charge", "est couvert", "sont couverts",
                  "ce que nous garantissons"], 1),
    ("condition", ["a condition", "sous reserve", "uniquement si", "seulement si", "pour beneficier",
                   "doit etre", "doivent etre", "lorsqu'ils sont", "lorsqu'elles sont", "par effraction"], 1),
    ("franchise", ["franchise", "plafond", "limite d'indemnite", "dans la limite"], 1),
    ("obligation", ["vous devez", "l'assure doit", "obligation", "mesures de prevention", "dans un delai"], 1),
]


def classify(titre: str, texte: str) -> list[str]:
    t = normalize(titre)
    body = normalize(texte)
    types = []
    for typ, kws, seuil in _TYPE_RULES:
        if any(k in t for k in kws) or sum(body.count(k) for k in kws) >= seuil:
            types.append(typ)
    return types or ["autre"]


_REF = re.compile(r"(?:article|art\.|paragraphe|point|§|chapitre)\s*(\d+(?:\.\d+)*)", re.I)
_REF_NUM = re.compile(r"\((?:voir|cf\.?)\s*(\d+(?:\.\d+)+)\)", re.I)


def find_refs(texte: str) -> list[str]:
    refs = {m.group(1) for m in _REF.finditer(texte)} | {m.group(1) for m in _REF_NUM.finditer(texte)}
    return sorted(refs)


_LEAF = ("lexique", "definitions", "glossaire", "preambule", "sommaire", "table des matieres")


def _is_leaf_chapter(label: str) -> bool:
    """Un lexique ou un sommaire n'est le parent d'aucun article qui le suit."""
    return normalize(label).strip().startswith(_LEAF)


def split_clauses(contrat_id: str, pages: list[str], max_chars: int = 1800) -> list[Clause]:
    """Découpe le texte en clauses selon les titres détectés ; les longues sont redécoupées par paragraphes."""
    stack: list[tuple[int, str]] = []   # (profondeur, libellé)
    clauses: list[Clause] = []
    cur = {"num": None, "titre": "Préambule", "section": [], "lines": [], "p0": 1, "p1": 1}

    def flush():
        texte = "\n".join(cur["lines"]).strip()
        if not texte:
            return
        for part in _chunk(texte, max_chars):
            clauses.append(Clause(
                id=f"{contrat_id}-{len(clauses) + 1:04d}", contrat_id=contrat_id, ordre=len(clauses),
                page_debut=cur["p0"], page_fin=cur["p1"], numero=cur["num"], titre=cur["titre"],
                section=list(cur["section"]), texte=part,
                types=classify(cur["titre"], part), renvois=find_refs(part),
            ))

    for pno, page in enumerate(pages, start=1):
        for line in page.splitlines():
            h = _match_heading(line)
            if h:
                flush()
                num, titre = h
                d = _depth(num)
                while stack and (stack[-1][0] >= d or _is_leaf_chapter(stack[-1][1])):
                    stack.pop()
                section = [lbl for _, lbl in stack]
                label = f"{num} {titre}".strip() if num else titre
                stack.append((d, label))
                cur = {"num": num, "titre": titre or (num or ""), "section": section,
                       "lines": [], "p0": pno, "p1": pno}
            else:
                cur["lines"].append(line)
                cur["p1"] = pno
    flush()
    return clauses


def _chunk(texte: str, max_chars: int) -> list[str]:
    if len(texte) <= max_chars:
        return [texte]
    paras = re.split(r"\n(?=\s*(?:[-•–▪]|\d+[.)]|[a-z][.)])\s)|\n{2,}", texte)
    out, buf = [], ""
    for p in paras:
        if buf and len(buf) + len(p) > max_chars:
            out.append(buf.strip())
            buf = ""
        buf += ("\n" if buf else "") + p
    if buf.strip():
        out.append(buf.strip())
    return out


# ------------------------------------------------------------------ définitions

_DEF_LINE = re.compile(r"^\s*[-•–]?\s*(?P<terme>[A-ZÀ-Ý«][^:]{1,60}?)\s*[:–-]\s+(?P<def>.{10,})$")


def extract_definitions(clauses: list[Clause]) -> dict[str, str]:
    """Lexique terme -> id de clause, depuis les clauses de type définition."""
    lex: dict[str, str] = {}
    for c in clauses:
        if "definition" not in c.types:
            continue
        for line in c.texte.splitlines():
            m = _DEF_LINE.match(line)
            if m:
                terme = normalize(m.group("terme")).strip(' "«»')
                if 2 <= len(terme) <= 50:
                    lex.setdefault(terme, c.id)
    return lex


# ---------------------------------------------------------------------- façade

def ingest(path: str | Path, contrat: Contrat) -> tuple[Contrat, list[Clause], dict[str, str]]:
    path = Path(path)
    pages = pdf_pages(path) if path.suffix.lower() == ".pdf" else text_pages(path)
    contrat.pages = len(pages)
    pages = strip_running_lines(pages)
    clauses = split_clauses(contrat.id, pages)
    return contrat, clauses, extract_definitions(clauses)
