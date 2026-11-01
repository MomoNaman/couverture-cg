# Couvert ou pas ?

Un sinistre est-il couvert par des conditions générales d'assurance habitation ? Le système répond
**couvert, couvert sous conditions, non couvert ou indéterminé**, explique pourquoi, et montre les
clauses sur lesquelles il s'appuie, surlignées dans le texte du contrat, avec leur page.

Le verdict n'est pas le point central. Ce qui compte, c'est que **rien n'est affiché sans avoir été
retrouvé dans le contrat**, et que le système **sait dire « indéterminé »** quand le texte se lit de
deux façons ou qu'un fait manque.

## Le problème à résoudre

Injecter un PDF de 100 pages dans un chatbot marche sur un contrat, puis cède pour trois raisons :

1. **Les clauses décisives ne ressemblent pas à la question.** « La bougie fond sur la table » ne
   partage aucun mot avec « dommages causés par la seule action de la chaleur, sans qu'il y ait eu
   incendie ». Une recherche par similarité sur des blocs de texte la manque.
2. **Une clause ne se lit pas seule.** Une garantie a ses conditions plus loin, ses exclusions dans
   un autre chapitre, et ses mots sont définis dans le lexique (« incendie » = combustion *avec flammes*).
3. **Un modèle cite de mémoire.** Il reformule, recolle deux passages, invente un article plausible.

## Ce que fait le pipeline

```
PDF ──► structure ──► recherche par facettes ──► raisonnement ──► vérification ──► verdict
        (articles,     (+ exclusions du même      (citations      (chaque citation
         lexique,       article, exclusions        obligatoires)   retrouvée mot pour
         renvois,       générales, définitions,                    mot, ou retirée ;
         pages)         renvois)                                   règles de verdict)
```

| Étape | Module | Ce qu'elle garantit |
|---|---|---|
| Ingestion | `ingest.py` | Découpage selon les titres (articles, 4.2.1, lexique), en-têtes et pieds retirés, deux colonnes gérées. Chaque clause garde numéro, section, page, renvois et type (garantie, exclusion, condition, définition…). |
| Tableaux | `tables.py` | Chaque ligne d'un tableau de plafonds/franchises devient une unité, avec ses en-têtes (« Garantie : Vol de vélo \| Plafond : 1 500 EUR »). Si la majorité des lignes répond, le tableau est rendu entier. |
| Recherche | `retrieve.py` | Le sinistre est décomposé en facettes (événement, bien, lieu, circonstance), cherchées avec le vocabulaire des contrats, puis complétées par la structure. Chaque clause retenue dit **pourquoi** elle l'est. |
| Raisonnement | `reason.py`, `prompts.py` | Le modèle suit l'ordre d'un gestionnaire (qualifier, garantie, exclusions, faits manquants) et cite chaque affirmation. |
| Vérification | `verify.py` | Citation retrouvée à l'identique, après normalisation, ou à 92 % minimum, et c'est **le texte du contrat** qui est affiché. Citation introuvable : retirée. « Non couvert » exige une exclusion citée : le silence du contrat ne prouve rien. Une ambiguïté décisive donne « indéterminé ». |
| Portefeuille | `extract.py`, `store.py` | Des centaines de contrats : extraction une fois par contrat vers une table SQL `garanties` ; voir plus bas. |

Le modèle conclut ; c'est le code qui décide de ce qui est montré, et qui peut ramener le verdict à
« indéterminé ». L'écart entre `verdict_modele` et `verdict` est conservé et affiché.

## Tenir des centaines de contrats

On ne relit pas des centaines de PDF à chaque question.

- **Une base, un index.** Tous les contrats dans SQLite (FTS5, BM25, accents ignorés), filtrés par
  `contrat_id`. L'édition du contrat fait partie de son identité : deux éditions sont deux contrats.
- **Une extraction par contrat, à l'ingestion.** Une grille fixe de garanties (vol, vol dans les
  dépendances, vélo, incendie, chaleur sans flamme, biens extérieurs, inoccupation…) est remplie
  pour chaque contrat, avec citations vérifiées : `cg extraire A`. Les questions de portefeuille
  deviennent des requêtes :
  ```sql
  SELECT contrat_id, statut, conditions FROM garanties
  WHERE garantie = 'vol_dependances' AND statut = 'incluse' AND verifiee = 1;
  ```
- **L'analyse fine ne relit qu'un contrat**, celui de l'assuré, à la bonne édition.
- **Le lexique métier est versionné** (`retrieve.LEXIQUE`) : quand un contrat emploie un terme
  absent (« engins de déplacement personnel »), on l'ajoute une fois, et tous les contrats en profitent.
- **Chaque réponse est journalisée** (table `reponses`, `out/llm_log.jsonl`) : on peut mesurer le
  taux de citations rejetées par contrat, et repérer les documents mal découpés.

## Installation et usage

```bash
pip install -e ".[dev]"
pytest -q                                   # 12 tests, sans clé ni réseau

cg ingest data/cg/assureur_a.pdf --id A --assureur "Assureur A" --edition 2022
cg recherche A "vol de vélo dans le local commun non fermé"   # clauses retenues et pourquoi, sans LLM

export LLM_PROVIDER=anthropic LLM_MODEL=claude-sonnet-5-5 LLM_API_KEY=...
#      (ou openai / azure avec LLM_BASE_URL)
cg analyse A "Je me fais voler mon vélo dans le local commun..."
cg export --analyser -o web/public/demo.json  # toutes les questions × tous les contrats
```

Interface (React, statique) :

```bash
cd web && npm install && npm run dev        # ou npm run build -> web/dist
```

Sans `demo.json`, l'interface charge `demo.fixture.json` : un **contrat fictif** (celui des tests)
et deux réponses rédigées au format du modèle, dont une citation inventée pour montrer le rejet.
C'est indiqué en tête de page. Le déploiement sur GitHub Pages est automatique (`.github/workflows/pages.yml`).

## Limites, dites franchement

- Les **conditions particulières** ne sont pas lues ; elles peuvent étendre ou restreindre une garantie.
- La détection des titres repose sur des motifs ; un PDF scanné demande un OCR en amont, et un
  contrat à la mise en page atypique peut être mal découpé (le test : `cg recherche` montre les clauses).
- La vérification prouve qu'un passage **existe** dans le contrat, pas qu'il est bien interprété.
  C'est pour ça que l'interface montre le passage dans son contexte.
- Les noms d'assureurs sont à anonymiser avant publication des extraits.

## Arborescence

```
src/couverture/   normalize, ingest, tables, store, retrieve, prompts, llm, reason, verify, extract, export, cli
tests/            contrat fictif, tests d'ingestion, de recherche, de vérification, bout en bout (replay)
scripts/          demo_fictive.py : données de démonstration de l'interface
web/              interface React (Vite)
questions.json    les sinistres posés à tous les contrats
```
