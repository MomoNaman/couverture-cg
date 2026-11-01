from pathlib import Path

import pytest

from couverture.ingest import ingest
from couverture.models import Contrat
from couverture.store import Store

FIX = Path(__file__).parent / "fixtures"
VELO = "Je me fais voler mon vélo dans le local commun de l'immeuble, qui n'était pas fermé à clé. Suis-je couvert ?"
BOUGIE = ("Un assuré laisse une bougie sur la table de son jardin pendant ses vacances. "
          "Avec la chaleur, la bougie fond et abîme la table. Est-ce couvert ?")


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "t.sqlite")
    c, clauses, lex = ingest(FIX / "cg_fictive.txt", Contrat("F", "Assureur fictif", "MRH", "test", "fixture"))
    s.add_contrat(c, clauses, lex)
    return s
