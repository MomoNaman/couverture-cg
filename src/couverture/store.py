"""Stockage SQLite : une base pour tous les contrats.

- contrats, clauses : le texte structuré, avec page et section.
- clauses_fts : index plein texte (BM25, accents ignorés) pour la recherche.
- definitions : lexique propre à chaque contrat.
- garanties : extraction structurée une fois par contrat (voir extract.py) ;
  c'est ce qui permet de tenir des centaines de contrats et de les interroger en SQL.
- reponses : chaque analyse de sinistre, avec ses citations vérifiées (traçabilité).
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .models import Clause, Contrat

SCHEMA = """
CREATE TABLE IF NOT EXISTS contrats (
  id TEXT PRIMARY KEY, assureur TEXT, produit TEXT, edition TEXT, source TEXT, pages INTEGER
);
CREATE TABLE IF NOT EXISTS clauses (
  id TEXT PRIMARY KEY, contrat_id TEXT REFERENCES contrats(id), ordre INTEGER,
  page_debut INTEGER, page_fin INTEGER, numero TEXT, titre TEXT, section TEXT,
  texte TEXT, types TEXT, renvois TEXT
);
CREATE INDEX IF NOT EXISTS clauses_contrat ON clauses(contrat_id, ordre);
CREATE VIRTUAL TABLE IF NOT EXISTS clauses_fts USING fts5(
  id UNINDEXED, contrat_id UNINDEXED, titre, section, texte,
  tokenize = "unicode61 remove_diacritics 2"
);
CREATE TABLE IF NOT EXISTS definitions (
  contrat_id TEXT, terme TEXT, clause_id TEXT, PRIMARY KEY (contrat_id, terme)
);
CREATE TABLE IF NOT EXISTS garanties (
  contrat_id TEXT, garantie TEXT, statut TEXT, conditions TEXT, plafond TEXT, franchise TEXT,
  exclusions TEXT, citations TEXT, verifiee INTEGER, PRIMARY KEY (contrat_id, garantie)
);
CREATE TABLE IF NOT EXISTS reponses (
  id INTEGER PRIMARY KEY AUTOINCREMENT, contrat_id TEXT, question TEXT, verdict TEXT,
  verdict_modele TEXT, json TEXT, cree_le TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


class Store:
    def __init__(self, path: str | Path = "out/cg.sqlite"):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path))
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    # ------------------------------------------------------------- écriture
    def add_contrat(self, contrat: Contrat, clauses: list[Clause], lexique: dict[str, str]) -> None:
        cur = self.db.cursor()
        cur.execute("DELETE FROM clauses WHERE contrat_id=?", (contrat.id,))
        cur.execute("DELETE FROM clauses_fts WHERE contrat_id=?", (contrat.id,))
        cur.execute("DELETE FROM definitions WHERE contrat_id=?", (contrat.id,))
        cur.execute("INSERT OR REPLACE INTO contrats VALUES (?,?,?,?,?,?)",
                    (contrat.id, contrat.assureur, contrat.produit, contrat.edition, contrat.source, contrat.pages))
        for c in clauses:
            cur.execute("INSERT INTO clauses VALUES (?,?,?,?,?,?,?,?,?,?,?)", (
                c.id, c.contrat_id, c.ordre, c.page_debut, c.page_fin, c.numero, c.titre,
                json.dumps(c.section, ensure_ascii=False), c.texte,
                json.dumps(c.types), json.dumps(c.renvois)))
            cur.execute("INSERT INTO clauses_fts VALUES (?,?,?,?,?)",
                        (c.id, c.contrat_id, c.titre, " ".join(c.section), c.texte))
        cur.executemany("INSERT OR REPLACE INTO definitions VALUES (?,?,?)",
                        [(contrat.id, t, cid) for t, cid in lexique.items()])
        self.db.commit()

    def save_reponse(self, rep) -> None:
        self.db.execute("INSERT INTO reponses (contrat_id, question, verdict, verdict_modele, json) VALUES (?,?,?,?,?)",
                        (rep.contrat_id, rep.question, rep.verdict, rep.verdict_modele,
                         json.dumps(rep.to_dict(), ensure_ascii=False)))
        self.db.commit()

    # -------------------------------------------------------------- lecture
    def contrats(self) -> list[Contrat]:
        return [Contrat(**dict(r)) for r in self.db.execute("SELECT * FROM contrats ORDER BY id")]

    def contrat(self, cid: str) -> Contrat:
        r = self.db.execute("SELECT * FROM contrats WHERE id=?", (cid,)).fetchone()
        if not r:
            raise KeyError(f"contrat inconnu : {cid}")
        return Contrat(**dict(r))

    @staticmethod
    def _row_to_clause(r: sqlite3.Row) -> Clause:
        d = dict(r)
        d["section"] = json.loads(d["section"])
        d["types"] = json.loads(d["types"])
        d["renvois"] = json.loads(d["renvois"])
        return Clause(**d)

    def clause(self, clause_id: str) -> Clause | None:
        r = self.db.execute("SELECT * FROM clauses WHERE id=?", (clause_id,)).fetchone()
        return self._row_to_clause(r) if r else None

    def clauses(self, contrat_id: str) -> list[Clause]:
        rows = self.db.execute("SELECT * FROM clauses WHERE contrat_id=? ORDER BY ordre", (contrat_id,))
        return [self._row_to_clause(r) for r in rows]

    def search(self, contrat_id: str, fts_query: str, k: int = 8) -> list[tuple[str, float]]:
        """BM25 (titre et section pèsent plus que le corps). Retourne [(clause_id, score)]."""
        if not fts_query.strip():
            return []
        try:
            rows = self.db.execute(
                "SELECT id, bm25(clauses_fts, 0, 0, 4.0, 2.0, 1.0) AS s FROM clauses_fts "
                "WHERE clauses_fts MATCH ? AND contrat_id = ? ORDER BY s LIMIT ?",
                (fts_query, contrat_id, k)).fetchall()
        except sqlite3.OperationalError:
            return []
        return [(r["id"], -r["s"]) for r in rows]

    def definitions(self, contrat_id: str) -> dict[str, str]:
        return {r["terme"]: r["clause_id"] for r in
                self.db.execute("SELECT terme, clause_id FROM definitions WHERE contrat_id=?", (contrat_id,))}

    def by_numero(self, contrat_id: str, numero: str) -> list[Clause]:
        rows = self.db.execute(
            "SELECT * FROM clauses WHERE contrat_id=? AND (numero=? OR numero LIKE ? OR numero LIKE ?) ORDER BY ordre LIMIT 3",
            (contrat_id, numero, f"%{numero}", f"{numero}.%"))
        return [self._row_to_clause(r) for r in rows]
