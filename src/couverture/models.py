from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Literal

ClauseType = Literal["definition", "garantie", "exclusion", "condition", "franchise", "obligation", "autre"]
Verdict = Literal["couvert", "couvert_sous_conditions", "non_couvert", "indetermine"]


@dataclass
class Contrat:
    id: str
    assureur: str
    produit: str
    edition: str | None
    source: str          # chemin ou URL du PDF
    pages: int = 0


@dataclass
class Clause:
    id: str                       # ex. "A-0042", stable pour un contrat
    contrat_id: str
    ordre: int                    # position dans le document
    page_debut: int
    page_fin: int
    numero: str | None            # "1.8.1.1", "Art. 12"... si détecté
    titre: str
    section: list[str]            # chemin hiérarchique des titres parents
    texte: str
    types: list[str] = field(default_factory=list)
    renvois: list[str] = field(default_factory=list)  # numéros cités ("article 12")

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def section_label(self) -> str:
        tete = f"{self.numero} {self.titre}".strip() if self.numero else self.titre
        return " › ".join(self.section + ([tete] if tete else []))


@dataclass
class Citation:
    clause_id: str
    extrait: str                  # ce que le modèle prétend citer
    verifiee: bool = False
    extrait_source: str | None = None   # passage exact retrouvé dans le document
    page: int | None = None
    debut: int | None = None      # offsets dans clause.texte, pour le surlignage
    fin: int | None = None
    methode: str | None = None    # "exacte" | "normalisee" | "floue"


@dataclass
class Etape:
    affirmation: str
    citations: list[Citation] = field(default_factory=list)


@dataclass
class Reponse:
    question: str
    contrat_id: str
    verdict: Verdict
    verdict_modele: Verdict
    resume: str
    etapes: list[Etape]
    ambiguites: list[str]
    informations_manquantes: list[str]
    exclusions_examinees: list[str]
    alertes: list[str] = field(default_factory=list)      # ajoutées par le vérificateur
    clauses_consultees: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)
