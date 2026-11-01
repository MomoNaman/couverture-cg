import { useEffect, useMemo, useRef, useState } from "react";

const VERDICTS = {
  couvert: { label: "Couvert", cls: "v-ok" },
  couvert_sous_conditions: { label: "Couvert sous conditions", cls: "v-cond" },
  non_couvert: { label: "Non couvert", cls: "v-ko" },
  indetermine: { label: "Indéterminé", cls: "v-ind" },
};

const METHODES = { exacte: "texte exact", normalisee: "retrouvée après normalisation", floue: "retrouvée à" };

// "définition : a", "définition : b" -> "définition : a, b"
function resumerRaisons(raisons) {
  const groupes = new Map();
  for (const r of raisons) {
    const [tete, ...reste] = r.split(" : ");
    const k = reste.length ? tete : r;
    if (!groupes.has(k)) groupes.set(k, []);
    if (reste.length) groupes.get(k).push(reste.join(" : "));
  }
  return [...groupes].map(([k, v]) => (v.length ? `${k} : ${v.join(", ")}` : k)).join(" · ");
}

async function charger() {
  for (const f of ["demo.json", "demo.fixture.json"]) {
    try {
      const r = await fetch(f, { cache: "no-store" });
      if (r.ok) return await r.json();
    } catch (_) { /* fichier suivant */ }
  }
  throw new Error("Aucune donnée : lancez `cg export` pour produire web/public/demo.json.");
}

export default function App() {
  const [data, setData] = useState(null);
  const [erreur, setErreur] = useState(null);
  const [qid, setQid] = useState(null);
  const [cid, setCid] = useState(null);
  const [actif, setActif] = useState(null); // { clauseId, debut, fin }
  const [vue, setVue] = useState("analyse");

  useEffect(() => {
    charger().then((d) => {
      setData(d);
      setQid(d.questions[0]?.id);
      setCid(d.contrats[0]?.id);
    }).catch((e) => setErreur(e.message));
  }, []);

  const cas = useMemo(
    () => data?.cas.find((c) => c.question_id === qid && c.contrat_id === cid),
    [data, qid, cid]
  );

  useEffect(() => setActif(null), [qid, cid]);

  if (erreur) return <div className="vide">{erreur}</div>;
  if (!data) return <div className="vide">Chargement…</div>;

  const question = data.questions.find((q) => q.id === qid);
  const contrat = data.contrats.find((c) => c.id === cid);

  return (
    <div className="app">
      <Entete jeu={data.jeu} vue={vue} setVue={setVue} />
      {vue === "methode" ? <Methode /> : (
        <div className="grille">
          <aside className="col-gauche">
            <h2 className="surtitre">Sinistres</h2>
            <ul className="sinistres">
              {data.questions.map((q) => (
                <li key={q.id}>
                  <button className={q.id === qid ? "sinistre actif" : "sinistre"} onClick={() => setQid(q.id)}>
                    <span className="sinistre-titre">{q.titre}</span>
                    <span className="sinistre-texte">{q.texte}</span>
                  </button>
                </li>
              ))}
            </ul>
            <Matrice data={data} qid={qid} cid={cid} choisir={(q, c) => { setQid(q); setCid(c); }} />
          </aside>

          <main className="col-centre">
            <div className="onglets-contrats" role="tablist">
              {data.contrats.map((c) => (
                <button key={c.id} role="tab" aria-selected={c.id === cid}
                        className={c.id === cid ? "onglet actif" : "onglet"} onClick={() => setCid(c.id)}>
                  {c.assureur}
                  <small>{c.edition ? `éd. ${c.edition}` : "édition non datée"} · {c.pages} p.</small>
                </button>
              ))}
            </div>
            <blockquote className="question">{question?.texte}</blockquote>
            {cas?.analyse
              ? <Analyse a={cas.analyse} clauses={data.clauses} actif={actif} setActif={setActif} />
              : <SansAnalyse />}
          </main>

          <aside className="col-droite">
            <Document cas={cas} clauses={data.clauses} contrat={contrat} actif={actif}
                      citations={cas?.analyse ? citationsDe(cas.analyse) : []} setActif={setActif} />
          </aside>
        </div>
      )}
    </div>
  );
}

function Entete({ jeu, vue, setVue }) {
  return (
    <header className="entete">
      <div>
        <h1>Couvert ou pas ?</h1>
        <p className="sous-titre">
          Un sinistre confronté aux conditions générales. Chaque citation affichée a été retrouvée
          mot pour mot dans le contrat ; à défaut, la réponse est « indéterminé ».
        </p>
      </div>
      <nav className="nav">
        <button className={vue === "analyse" ? "actif" : ""} onClick={() => setVue("analyse")}>Analyse</button>
        <button className={vue === "methode" ? "actif" : ""} onClick={() => setVue("methode")}>Méthode</button>
      </nav>
      {jeu === "fictif" && (
        <p className="bandeau">
          Jeu de démonstration : contrat <strong>fictif</strong> et réponses rédigées au format du modèle,
          pour montrer l'interface et la vérification. Les analyses réelles se génèrent avec <code>cg export --analyser</code>.
        </p>
      )}
    </header>
  );
}

function Matrice({ data, qid, cid, choisir }) {
  if (data.contrats.length < 2) return null;
  return (
    <section className="matrice">
      <h2 className="surtitre">Tous les contrats</h2>
      <table>
        <thead>
          <tr><th></th>{data.contrats.map((c) => <th key={c.id} title={c.assureur}>{c.id}</th>)}</tr>
        </thead>
        <tbody>
          {data.questions.map((q) => (
            <tr key={q.id}>
              <th scope="row">{q.titre}</th>
              {data.contrats.map((c) => {
                const a = data.cas.find((x) => x.question_id === q.id && x.contrat_id === c.id)?.analyse;
                const v = a ? VERDICTS[a.verdict] : null;
                const sel = q.id === qid && c.id === cid;
                return (
                  <td key={c.id}>
                    <button className={`pastille ${v ? v.cls : "v-none"} ${sel ? "sel" : ""}`}
                            title={v ? v.label : "non analysé"} onClick={() => choisir(q.id, c.id)}>
                      {v ? v.label.split(" ")[0] : "—"}
                    </button>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function citationsDe(a) {
  return a.etapes.flatMap((e, i) => e.citations.map((c) => ({ ...c, etape: i })));
}

function Analyse({ a, clauses, actif, setActif }) {
  const v = VERDICTS[a.verdict];
  const degrade = a.verdict !== a.verdict_modele;
  const rejets = a.alertes.filter((x) => x.startsWith("Citation rejetée"));
  const autres = a.alertes.filter((x) => !x.startsWith("Citation rejetée"));
  const nCit = citationsDe(a).length;
  return (
    <article className="analyse">
      <div className={`tampon ${v.cls}`}>
        <span className="tampon-label">{v.label}</span>
        {degrade && <span className="tampon-note">le modèle concluait « {VERDICTS[a.verdict_modele].label.toLowerCase()} »</span>}
      </div>
      <p className="resume">{a.resume}</p>

      <ol className="etapes">
        {a.etapes.map((e, i) => (
          <li key={i} className={e.citations.length ? "" : "sans-appui"}>
            <p>{e.affirmation}</p>
            {e.citations.length === 0 && <p className="note-rejet">Affirmation retirée : sa citation est introuvable dans le contrat.</p>}
            {e.citations.map((c, j) => {
              const cl = clauses[c.clause_id];
              const on = actif && actif.clauseId === c.clause_id && actif.debut === c.debut;
              return (
                <button key={j} className={on ? "citation on" : "citation"}
                        onClick={() => setActif({ clauseId: c.clause_id, debut: c.debut, fin: c.fin })}>
                  <span className="citation-texte">« {c.extrait_source} »</span>
                  <span className="citation-ref">
                    {cl?.numero || cl?.titre} · p. {c.page} · <span className="verif">✓ {METHODES[c.methode?.split(" ")[0]] || c.methode}{c.methode?.includes("(") ? " " + c.methode.split(" ")[1].replace(/[()]/g, "") : ""}</span>
                  </span>
                </button>
              );
            })}
          </li>
        ))}
      </ol>

      {a.ambiguites.length > 0 && (
        <section className="bloc">
          <h3>Ce que le contrat ne tranche pas</h3>
          <ul>{a.ambiguites.map((x, i) => {
            const dec = x.startsWith("[décisif]");
            return <li key={i}>{dec && <span className="etiquette">décisif</span>}{x.replace("[décisif] ", "")}</li>;
          })}</ul>
        </section>
      )}
      {a.informations_manquantes.length > 0 && (
        <section className="bloc">
          <h3>À demander à l'assuré</h3>
          <ul>{a.informations_manquantes.map((x, i) => <li key={i}>{x}</li>)}</ul>
        </section>
      )}
      {a.exclusions_examinees.length > 0 && (
        <section className="bloc discret">
          <h3>Exclusions examinées</h3>
          <ul>{a.exclusions_examinees.map((x, i) => <li key={i}>{x}</li>)}</ul>
        </section>
      )}
      <section className="bloc controles">
        <h3>Contrôles automatiques</h3>
        <p className="compteur">
          {nCit} citation{nCit > 1 ? "s" : ""} vérifiée{nCit > 1 ? "s" : ""} dans le texte
          {rejets.length > 0 && <> · <strong>{rejets.length} rejetée{rejets.length > 1 ? "s" : ""}</strong></>}
        </p>
        <ul>
          {rejets.map((x, i) => <li key={"r" + i} className="rejet">{x.replace("Citation rejetée ", "")}</li>)}
          {autres.map((x, i) => <li key={"a" + i}>{x}</li>)}
        </ul>
      </section>
    </article>
  );
}

function SansAnalyse() {
  return (
    <div className="sans-analyse">
      <p><strong>Pas encore d'analyse pour ce couple sinistre × contrat.</strong></p>
      <p>Les clauses que la recherche a retenues sont à droite, avec la raison de chacune. Pour produire
        le verdict : <code>cg export --analyser</code> (clé LLM requise).</p>
    </div>
  );
}

function Document({ cas, clauses, contrat, actif, citations, setActif }) {
  const ref = useRef(null);
  useEffect(() => {
    if (!actif || !ref.current) return;
    const el = ref.current.querySelector(`[data-clause="${actif.clauseId}"] mark.on`)
      || ref.current.querySelector(`[data-clause="${actif.clauseId}"]`);
    el?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [actif]);

  if (!cas) return null;
  const citees = new Set(citations.map((c) => c.clause_id));
  return (
    <div className="document" ref={ref}>
      <h2 className="surtitre">Clauses consultées — {contrat?.assureur}</h2>
      <p className="doc-intro">
        {cas.recherche.length} clauses retenues par la recherche, dans l'ordre du contrat.
        Le modèle ne voit que celles-ci.
      </p>
      {cas.recherche.map(({ clause_id, raisons }) => {
        const cl = clauses[clause_id];
        if (!cl) return null;
        const spans = citations.filter((c) => c.clause_id === clause_id);
        return (
          <section key={clause_id} data-clause={clause_id}
                   className={`clause ${citees.has(clause_id) ? "citee" : ""} ${actif?.clauseId === clause_id ? "focus" : ""}`}>
            <header>
              <span className="clause-num">{cl.numero || cl.titre}</span>
              <span className="clause-page">p. {cl.page_debut}{cl.page_fin !== cl.page_debut ? `–${cl.page_fin}` : ""}</span>
              <span className="types">{cl.types.filter((t) => t !== "autre").map((t) => <i key={t}>{t}</i>)}</span>
            </header>
            <p className="clause-section">{cl.section_label}</p>
            <Surligne texte={cl.texte} spans={spans} actif={actif} setActif={setActif} />
            <p className="raisons">Retenue par : {resumerRaisons(raisons)}</p>
          </section>
        );
      })}
    </div>
  );
}

function Surligne({ texte, spans, actif, setActif }) {
  const tri = [...spans].filter((s) => s.debut != null).sort((a, b) => a.debut - b.debut);
  const morceaux = [];
  let pos = 0;
  tri.forEach((s, i) => {
    if (s.debut < pos) return; // chevauchement : on garde le premier
    morceaux.push(texte.slice(pos, s.debut));
    const on = actif && actif.clauseId === s.clause_id && actif.debut === s.debut;
    morceaux.push(
      <mark key={i} className={on ? "on" : ""} onClick={() => setActif({ clauseId: s.clause_id, debut: s.debut, fin: s.fin })}>
        {texte.slice(s.debut, s.fin)}
      </mark>
    );
    pos = s.fin;
  });
  morceaux.push(texte.slice(pos));
  return <p className="clause-texte">{morceaux}</p>;
}

function Methode() {
  return (
    <article className="methode">
      <h2>Ce que fait le système, et ce qu'il refuse de faire</h2>
      <ol>
        <li><strong>Lire la structure, pas des blocs de texte.</strong> Le PDF est découpé selon ses titres
          (articles, sous-points, lexique). Chaque clause garde son numéro, sa section, sa page et ses renvois.</li>
        <li><strong>Chercher par facettes.</strong> Le sinistre est décomposé (événement, bien, lieu, circonstance).
          Chaque facette est cherchée avec le vocabulaire du contrat (« vélo » → « bicyclette », « engins de
          déplacement »), puis la recherche est complétée par la structure : exclusions du même article, exclusions
          générales, définitions des termes employés, clauses vers lesquelles le texte renvoie.</li>
        <li><strong>Raisonner sur les seules clauses retenues.</strong> Le modèle qualifie l'événement selon les
          définitions du contrat, cherche la garantie, examine les exclusions, et cite chaque affirmation.</li>
        <li><strong>Vérifier avant d'afficher.</strong> Chaque citation est retrouvée dans la clause indiquée
          (à l'identique, après normalisation, ou à 92 % minimum). Le passage affiché est celui du document.
          Une citation introuvable est retirée.</li>
        <li><strong>Préférer l'abstention étayée.</strong> « Non couvert » exige une exclusion ou une condition citée :
          ne pas trouver une garantie ne prouve pas qu'elle n'existe pas. Une ambiguïté décisive donne « indéterminé »,
          avec ce qu'il faudrait savoir pour trancher.</li>
        <li><strong>Des centaines de contrats.</strong> Chaque contrat est extrait une fois selon une grille de garanties
          vers une table SQL (statut, conditions, plafond, franchise, citations vérifiées). Les questions de portefeuille
          deviennent des requêtes ; l'analyse fine ne relit qu'un contrat, à la bonne édition.</li>
      </ol>
      <p className="limite">Ce que l'outil ne dit pas : les conditions particulières, qui peuvent étendre ou restreindre
        la garantie, ne sont pas lues. Une analyse n'est pas une décision d'indemnisation.</p>
    </article>
  );
}
