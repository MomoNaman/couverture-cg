"""Ligne de commande.

  cg ingest data/cg/assureur_a.pdf --id A --assureur "Assureur A" --produit "MRH" --edition 2022
  cg contrats
  cg recherche A "vol de vélo dans le local commun"        # sans LLM : clauses retenues et pourquoi
  cg analyse  A "Je me fais voler mon vélo ..."             # LLM + vérification
  cg extraire A                                            # fiche structurée par garantie (SQL)
  cg export   --questions questions.json -o web/public/demo.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .ingest import ingest
from .models import Contrat
from .retrieve import retrieve
from .store import Store

COULEUR = {"couvert": "\033[32m", "couvert_sous_conditions": "\033[33m",
           "non_couvert": "\033[31m", "indetermine": "\033[35m"}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="cg", description="Sinistres et conditions générales")
    p.add_argument("--db", default="out/cg.sqlite")
    sp = p.add_subparsers(dest="cmd", required=True)

    a = sp.add_parser("ingest")
    a.add_argument("fichier")
    a.add_argument("--id", required=True)
    a.add_argument("--assureur", required=True)
    a.add_argument("--produit", default="Multirisque habitation")
    a.add_argument("--edition")

    sp.add_parser("contrats")

    r = sp.add_parser("recherche")
    r.add_argument("contrat")
    r.add_argument("question")

    q = sp.add_parser("analyse")
    q.add_argument("contrat")
    q.add_argument("question")
    q.add_argument("--json", action="store_true")

    e = sp.add_parser("extraire")
    e.add_argument("contrat")

    x = sp.add_parser("export")
    x.add_argument("--questions", default="questions.json")
    x.add_argument("--analyser", action="store_true", help="appeler le LLM pour chaque question × contrat")
    x.add_argument("-o", "--out", default="web/public/demo.json")

    args = p.parse_args(argv)
    store = Store(args.db)

    if args.cmd == "ingest":
        c, clauses, lex = ingest(args.fichier, Contrat(args.id, args.assureur, args.produit, args.edition, args.fichier))
        store.add_contrat(c, clauses, lex)
        types = {}
        for cl in clauses:
            for t in cl.types:
                types[t] = types.get(t, 0) + 1
        print(f"{c.id} : {c.pages} pages, {len(clauses)} clauses, {len(lex)} définitions — {types}")

    elif args.cmd == "contrats":
        for c in store.contrats():
            n = store.db.execute("SELECT count(*) FROM clauses WHERE contrat_id=?", (c.id,)).fetchone()[0]
            print(f"{c.id:6} {c.assureur:24} {c.produit:28} {c.edition or '?':8} {c.pages:4} p.  {n} clauses")

    elif args.cmd == "recherche":
        ctx = retrieve(store, args.contrat, args.question)
        print(f"Concepts : {', '.join(ctx.concepts)}\n")
        for c in ctx.clauses:
            print(f"[{c.id}] p.{c.page_debut} {','.join(c.types):28} {c.section_label[:70]}")
            print(f"        ← {'; '.join(ctx.raisons[c.id])}")

    elif args.cmd == "analyse":
        from .llm import LLM
        from .reason import analyser
        rep, _ = analyser(store, LLM(), args.contrat, args.question)
        if args.json:
            print(json.dumps(rep.to_dict(), ensure_ascii=False, indent=2))
        else:
            _print_rep(rep)

    elif args.cmd == "extraire":
        from .extract import extraire_contrat
        from .llm import LLM
        for l in extraire_contrat(store, LLM(), args.contrat):
            print(f"{l['garantie']:22} {l['statut'] or '?':22} vérifiée={l['verifiee']}")

    elif args.cmd == "export":
        from .export import export
        n = export(store, json.loads(Path(args.questions).read_text(encoding="utf-8")), args.out, args.analyser)
        print(f"{args.out} : {n} analyses")
    return 0


def _print_rep(rep) -> None:
    fin = "\033[0m"
    print(f"\nVerdict : {COULEUR.get(rep.verdict, '')}{rep.verdict}{fin}"
          + (f"   (modèle : {rep.verdict_modele})" if rep.verdict != rep.verdict_modele else ""))
    print(f"\n{rep.resume}\n")
    for i, e in enumerate(rep.etapes, 1):
        print(f"{i}. {e.affirmation}")
        for c in e.citations:
            print(f"     « {c.extrait_source} »  [{c.clause_id}, p. {c.page}, {c.methode}]")
    for titre, items in (("Ambiguïtés", rep.ambiguites), ("À demander à l'assuré", rep.informations_manquantes),
                         ("Contrôles", rep.alertes)):
        if items:
            print(f"\n{titre} :")
            for it in items:
                print(f"  - {it}")


if __name__ == "__main__":
    sys.exit(main())
