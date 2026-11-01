import json

from conftest import BOUGIE, FIX, VELO

from couverture.ingest import ingest
from couverture.llm import LLM
from couverture.models import Citation, Contrat, Etape, Reponse
from couverture.normalize import normalize, normalize_with_map
from couverture.prompts import SYSTEM_ANALYSE, user_analyse
from couverture.reason import analyser, format_clauses
from couverture.retrieve import retrieve
from couverture.verify import locate, verify


# ---------------------------------------------------------------- normalisation

def test_normalisation_garde_les_positions():
    t = "Les vols commis sans effrac-\ntion lorsque l’assuré était « absent »"
    n, idx = normalize_with_map(t)
    assert "sans effraction lorsque l'assure etait \"absent\"" in n
    j = n.find("assure")
    assert t[idx[j]:idx[j + 5] + 1] == "assuré"


# --------------------------------------------------------------------- ingestion

def test_structure_du_contrat(store):
    cl = store.clauses("F")
    assert [c.numero for c in cl] == [None, "Article 3", "4.1", "4.2", "4.3", "Article 5", "Article 6", "Article 7"]
    assert all("Fictive" not in c.texte for c in cl), "les en-têtes répétés doivent être retirés"
    assert all("Page" not in c.texte for c in cl), "les numéros de page doivent être retirés"
    c42 = next(c for c in cl if c.numero == "4.2")
    assert c42.page_debut == 3 and c42.renvois == ["6"]
    assert "Article 4 Vol et vandalisme" in c42.section_label
    assert "exclusion" in next(c for c in cl if c.numero == "4.3").types
    assert {"incendie", "effraction", "parties communes"} <= set(store.definitions("F"))


def test_pdf_deux_pages(tmp_path):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    pdf = tmp_path / "cg.pdf"
    cv = canvas.Canvas(str(pdf), pagesize=A4)
    for page in (FIX / "cg_fictive.txt").read_text(encoding="utf-8").split("\f"):
        y = 800
        cv.setFont("Helvetica", 8)
        for line in page.splitlines():
            cv.drawString(40, y, line[:130])
            y -= 12
        cv.showPage()
    cv.save()
    c, clauses, _ = ingest(pdf, Contrat("P", "x", "MRH", None, str(pdf)))
    assert c.pages == 4
    assert any(cl.numero == "4.3" and cl.page_debut == 3 for cl in clauses)


# --------------------------------------------------------------------- recherche

def test_recherche_velo(store):
    ctx = retrieve(store, "F", VELO)
    nums = {c.numero for c in ctx.clauses}
    assert {"4.2", "4.3", "Article 6"} <= nums      # 6 n'arrive que par le renvoi de 4.2 ou la recherche
    assert any("parties communes" in r for rs in ctx.raisons.values() for r in rs)


def test_recherche_bougie_trouve_la_clause_sans_mot_commun(store):
    ctx = retrieve(store, "F", BOUGIE)
    nums = {c.numero for c in ctx.clauses}
    # la question ne contient ni « incendie » ni « exclus » : on doit pourtant remonter l'article 3,
    # la définition d'incendie, le mobilier de jardin et l'exclusion d'inoccupation
    assert {"Article 3", "Article 5", "Article 7"} <= nums
    assert None in nums                              # le lexique (définition d'incendie)


# ------------------------------------------------------------------ vérification

def _clauses(store):
    return {c.id: c for c in store.clauses("F")}


def test_citation_exacte_normalisee_et_inventee(store):
    cl = _clauses(store)
    c43 = next(c for c in cl.values() if c.numero == "4.3")
    ok = locate("les vols commis sans effraction lorsque les locaux n'étaient pas fermés à clé", c43)
    assert ok and ok.methode == "exacte" and ok.page == 3
    # apostrophe typographique et accents perdus : retrouvé, et c'est le texte du contrat qui est rendu
    norm = locate("les vols commis sans effraction lorsque les locaux n’etaient pas fermes a cle", c43)
    assert norm and norm.methode == "normalisee" and "fermés à clé" in norm.extrait_source
    # légère paraphrase : rejet en dessous du seuil
    assert locate("les vols sans effraction ne sont jamais garantis quand la porte est ouverte", c43) is None


def _rep(verdict, etapes, excl=("4.3 examinée",), ambig=()):
    return Reponse(question=VELO, contrat_id="F", verdict=verdict, verdict_modele=verdict, resume="",
                   etapes=etapes, ambiguites=list(ambig), informations_manquantes=[],
                   exclusions_examinees=list(excl))


def test_non_couvert_sans_exclusion_citee_devient_indetermine(store):
    cl = _clauses(store)
    c5 = next(c for c in cl.values() if c.numero == "Article 5")
    rep = _rep("non_couvert", [Etape("Le mobilier de jardin n'est garanti que contre l'incendie et la tempête.",
                                     [Citation(c5.id, "Le mobilier de jardin est garanti contre l'incendie et la tempête")])])
    out = verify(rep, cl)
    # une garantie limitée n'est pas une exclusion citée : le silence du contrat ne prouve rien
    assert out.verdict == "indetermine"
    assert out.verdict_modele == "non_couvert"


def test_citation_inventee_retiree_et_verdict_degrade(store):
    cl = _clauses(store)
    c42 = next(c for c in cl.values() if c.numero == "4.2")
    rep = _rep("couvert", [Etape("Les vélos sont toujours couverts.",
                                 [Citation(c42.id, "les vélos sont couverts en toutes circonstances")])])
    out = verify(rep, cl)
    assert out.etapes[0].citations == []
    assert out.verdict == "indetermine"
    assert any("introuvable" in a for a in out.alertes)


def test_ambiguite_decisive(store):
    cl = _clauses(store)
    c42 = next(c for c in cl.values() if c.numero == "4.2")
    rep = _rep("couvert_sous_conditions",
               [Etape("Vélo garanti s'il est attaché.",
                      [Citation(c42.id, "Les vélos entreposés dans les parties communes de l'immeuble sont garantis")])],
               ambig=["[décisif] 4.2 et 4.3 se contredisent pour un local non fermé à clé"])
    assert verify(rep, cl).verdict == "indetermine"


# -------------------------------------------------------------- bout en bout (replay)

def test_analyse_bout_en_bout_avec_replay(store, tmp_path, monkeypatch):
    """Le LLM est remplacé par une réponse enregistrée : on teste toute la chaîne sans clé."""
    ctx = retrieve(store, "F", VELO)
    user = user_analyse(VELO, "Assureur fictif — MRH (édition test)", format_clauses(ctx.clauses))
    c42 = next(c for c in ctx.clauses if c.numero == "4.2")
    c43 = next(c for c in ctx.clauses if c.numero == "4.3")
    reponse_modele = {
        "verdict": "indetermine",
        "resume": "Le contrat garantit les vélos attachés dans les parties communes, mais exclut les vols sans effraction dans un local non fermé à clé.",
        "etapes": [
            {"affirmation": "Les vélos dans les parties communes sont garantis s'ils sont attachés.",
             "citations": [{"clause_id": c42.id, "extrait": "Les vélos entreposés dans les parties communes de l’immeuble sont garantis lorsqu’ils sont attachés à un point fixe par un antivol"}]},
            {"affirmation": "Le vol sans effraction dans un local non fermé à clé est exclu.",
             "citations": [{"clause_id": c43.id, "extrait": "les vols commis sans effraction lorsque les locaux n'étaient pas fermés à clé"}]},
            {"affirmation": "Phrase inventée par le modèle.",
             "citations": [{"clause_id": c43.id, "extrait": "le vélo n'est jamais couvert dans une cave commune"}]},
        ],
        "exclusions_examinees": [f"{c43.id} : vol sans effraction, local non fermé"],
        "ambiguites": [{"texte": "4.2 et 4.3 ne disent pas laquelle prime pour un vélo attaché dans un local non fermé", "decisive": True}],
        "informations_manquantes": ["Le vélo était-il attaché à un point fixe par un antivol ?"],
    }
    replay = tmp_path / "replay"
    replay.mkdir()
    (replay / f"{LLM.key_for(SYSTEM_ANALYSE, user)}.json").write_text(json.dumps(reponse_modele), encoding="utf-8")
    monkeypatch.setenv("LLM_PROVIDER", "replay")
    monkeypatch.setenv("LLM_REPLAY_DIR", str(replay))
    rep, _ = analyser(store, LLM(), "F", VELO, expansion=False)
    assert rep.verdict == "indetermine"
    assert len(rep.etapes[0].citations) == 1 and rep.etapes[0].citations[0].methode == "normalisee"
    assert rep.etapes[2].citations == []
    assert store.db.execute("SELECT count(*) FROM reponses").fetchone()[0] == 1
