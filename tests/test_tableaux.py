from couverture.ingest import ingest
from couverture.models import Contrat
from couverture.retrieve import retrieve
from couverture.store import Store
from couverture.tables import fold_header

LIGNES = [
    ["Garantie", "Plafond", "Franchise", "Condition"],
    ["Incendie", "Capital contenu", "150 EUR", "-"],
    ["Vol dans l'habitation", "Capital contenu", "150 EUR", "Effraction"],
    ["Vol de vélo", "1 500 EUR", "250 EUR", "Antivol homologué"],
    ["Bris de glace", "3 000 EUR", "Sans franchise", "-"],
    ["Dégâts des eaux", "Capital contenu", "150 EUR", "-"],
]


def _pdf(path):
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet
    st = getSampleStyleSheet()
    doc = SimpleDocTemplate(str(path), pagesize=A4)
    t = Table(LIGNES)
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, "black")]))
    doc.build([Paragraph("Article 9 - Plafonds et franchises", st["Normal"]),
               Paragraph("Les montants ci-dessous s'appliquent par sinistre.", st["Normal"]), t])


def test_une_ligne_de_tableau_par_unite(tmp_path):
    pdf = tmp_path / "t.pdf"
    _pdf(pdf)
    c, clauses, lex = ingest(pdf, Contrat("T", "x", "MRH", None, str(pdf)))
    rows = [cl for cl in clauses if "tableau" in cl.types]
    assert len(rows) == 5
    velo = next(r for r in rows if "vélo" in r.texte)
    assert velo.texte == "Garantie : Vol de vélo | Plafond : 1 500 EUR | Franchise : 250 EUR | Condition : Antivol homologué"
    assert "Article 9" in velo.section_label
    s = Store(tmp_path / "t.sqlite")
    s.add_contrat(c, clauses, lex)
    ctx = retrieve(s, "T", "Quel est le plafond pour le vol de mon vélo ?")
    ids = [x.id for x in ctx.clauses if "tableau" in x.types]
    assert velo.id in ids and len(ids) < 5          # la ligne utile, pas tout le tableau


def test_entete_sur_deux_lignes():
    head, body = fold_header([["Garantie", "Plafond", ""], ["", "Habitation", "Dépendances"],
                              ["Vol", "10 000", "1 000"], ["Incendie", "50 000", "5 000"]])
    assert head == ["Garantie", "Plafond Habitation", "Plafond Dépendances"]
    assert len(body) == 2
