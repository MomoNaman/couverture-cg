"""Construit web/public/demo.fixture.json : le contrat FICTIF des tests et deux réponses
rédigées à la main au format du modèle (dont une citation inventée, pour montrer le rejet).
Sert uniquement au développement de l'interface et à montrer le format ; affiché comme tel."""
import json, os, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from couverture.ingest import ingest
from couverture.llm import LLM
from couverture.models import Contrat
from couverture.prompts import SYSTEM_ANALYSE, user_analyse
from couverture.reason import analyser, format_clauses
from couverture.retrieve import retrieve
from couverture.store import Store
from couverture.export import export

tmp = Path(tempfile.mkdtemp())
store = Store(tmp / "f.sqlite")
c, cl, lex = ingest(ROOT / "tests/fixtures/cg_fictive.txt", Contrat("F", "Assureur fictif", "Multirisque habitation", "test", "tests/fixtures/cg_fictive.txt"))
store.add_contrat(c, cl, lex)
qs = json.loads((ROOT / "questions.json").read_text(encoding="utf-8"))
by = lambda ctx, num: next(x.id for x in ctx.clauses if x.numero == num)

def ctx_of(q):
    return retrieve(store, "F", q)

reponses = {}
q = qs[0]["texte"]; ctx = ctx_of(q)
reponses[q] = {
 "verdict": "indetermine",
 "resume": "Le contrat prévoit une garantie pour les vélos rangés dans les parties communes, mais seulement s'ils sont attachés à un point fixe, et il exclut les vols sans effraction dans des locaux non fermés à clé. Les deux clauses ne disent pas laquelle l'emporte : la réponse dépend de l'antivol et de la lecture retenue par l'assureur.",
 "etapes": [
  {"affirmation": "Le local à vélos de l'immeuble relève des « parties communes » au sens du contrat, et non des dépendances privatives.",
   "citations": [{"clause_id": by(ctx, None), "extrait": "Parties communes : les locaux et espaces de l'immeuble à l'usage de plusieurs occupants, tels que les locaux à vélos"}]},
  {"affirmation": "Un vélo dans les parties communes est garanti s'il est attaché à un point fixe par un antivol.",
   "citations": [{"clause_id": by(ctx, "4.2"), "extrait": "Les vélos entreposés dans les parties communes de l’immeuble sont garantis lorsqu’ils sont attachés à un point fixe par un antivol"}]},
  {"affirmation": "Le contrat exclut les vols sans effraction lorsque les locaux n'étaient pas fermés à clé.",
   "citations": [{"clause_id": by(ctx, "4.3"), "extrait": "les vols commis sans effraction lorsque les locaux n'étaient pas fermés à clé"}]},
  {"affirmation": "L'assuré doit fermer à clé les locaux qu'il occupe.",
   "citations": [{"clause_id": by(ctx, "Article 6"), "extrait": "l'assuré doit fermer à clé les accès des locaux qu'il occupe"}]},
  {"affirmation": "Les vélos ne sont jamais couverts hors du logement.",
   "citations": [{"clause_id": by(ctx, "4.3"), "extrait": "les vélos ne sont jamais couverts en dehors du logement de l'assuré"}]}
 ],
 "exclusions_examinees": [f"{by(ctx,'4.3')} : vol sans effraction dans des locaux non fermés à clé — s'applique si l'on considère le local commun comme « les locaux »", f"{by(ctx,'Article 7')} : exclusions générales — aucune ne vise ce cas"],
 "ambiguites": [{"texte": "4.2 garantit le vélo attaché dans les parties communes sans exiger que le local soit fermé ; 4.3 exclut le vol sans effraction quand « les locaux » ne sont pas fermés. Le contrat ne dit pas si « les locaux » désigne aussi un local commun que l'assuré ne contrôle pas.", "decisive": True},
                {"texte": "L'article 6 vise « les locaux qu'il occupe » : un local commun est-il occupé par l'assuré ?", "decisive": False}],
 "informations_manquantes": ["Le vélo était-il attaché à un point fixe par un antivol ? Si non, 4.2 ne s'applique pas et le vol n'est pas garanti.", "Le local est-il normalement fermé à clé par le syndic ? Cela pèse sur la lecture de 4.3."]
}
q = qs[1]["texte"]; ctx = ctx_of(q)
reponses[q] = {
 "verdict": "non_couvert",
 "resume": "Une bougie qui fond sous l'effet de la chaleur n'est pas un incendie au sens du contrat, qui exige des flammes. Les dommages dus à la seule chaleur sont expressément exclus. La garantie du mobilier de jardin ne couvre que l'incendie et la tempête.",
 "etapes": [
  {"affirmation": "Le contrat définit l'incendie comme une combustion avec flammes ; une bougie qui fond sans s'enflammer n'en est pas un.",
   "citations": [{"clause_id": by(ctx, None), "extrait": "Incendie : la combustion avec flammes en dehors d'un foyer normal."}]},
  {"affirmation": "Les dommages causés par la seule chaleur, sans incendie, sont exclus.",
   "citations": [{"clause_id": by(ctx, "Article 3"), "extrait": "Sont exclus les dommages causés par la seule action de la chaleur ou par le contact direct d'une source de chaleur, sans qu'il y ait eu incendie"}]},
  {"affirmation": "Le mobilier de jardin n'est garanti à l'extérieur que contre l'incendie et la tempête.",
   "citations": [{"clause_id": by(ctx, "Article 5"), "extrait": "Le mobilier de jardin est garanti contre l'incendie et la tempête lorsqu'il se trouve à l'extérieur"}]}
 ],
 "exclusions_examinees": [f"{by(ctx,'Article 3')} : chaleur sans incendie — s'applique", f"{by(ctx,'Article 7')} : inoccupation de plus de 60 jours — ne s'applique pas à des vacances ordinaires, à confirmer"],
 "ambiguites": [{"texte": "Si la bougie a brièvement pris feu avant de fondre, on revient dans la garantie incendie de l'article 5.", "decisive": False}],
 "informations_manquantes": ["La bougie a-t-elle pris feu, ou a-t-elle seulement fondu ? Avec des flammes, le dommage relève de l'incendie, garanti pour le mobilier de jardin.", "Combien de temps a duré l'absence ? Au-delà de 60 jours, l'exclusion générale d'inoccupation s'applique."]
}
replay = tmp / "replay"; replay.mkdir()
for q, d in reponses.items():
    ctx = ctx_of(q)
    user = user_analyse(q, "Assureur fictif — Multirisque habitation (édition test)", format_clauses(ctx.clauses))
    (replay / f"{LLM.key_for(SYSTEM_ANALYSE, user)}.json").write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
os.environ.update(LLM_PROVIDER="replay", LLM_REPLAY_DIR=str(replay))
for q in reponses:
    analyser(store, LLM(), "F", q, expansion=False)
out = ROOT / "web/public/demo.fixture.json"
export(store, qs, str(out))
data = json.loads(out.read_text(encoding="utf-8")); data["jeu"] = "fictif"
out.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
for cas in data["cas"]:
    a = cas["analyse"]; print(cas["question_id"], a["verdict_modele"], "->", a["verdict"], len(a["alertes"]), "alertes")
