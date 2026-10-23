/* Test de parité : le moteur JavaScript de la démo doit prendre exactement
   les mêmes décisions que le paquet Python sur les appels de démo.

     python scripts/exporter_demo.py /tmp/donnees.json /tmp/reference.json
     node scripts/parite.js /tmp/donnees.json /tmp/reference.json            */
"use strict";
const fs = require("fs");
const path = require("path");
const assert = require("assert");
const M = require(path.join(__dirname, "..", "demo", "engine.js"));

const [fichierDonnees, fichierReference] = process.argv.slice(2);
const donnees = JSON.parse(fs.readFileSync(fichierDonnees, "utf8"));
const reference = JSON.parse(fs.readFileSync(fichierReference, "utf8"));
let verifications = 0;

function egal(obtenu, attendu, message) {
  assert.deepStrictEqual(obtenu, attendu, message);
  verifications++;
}

for (const sc of donnees.scenarios) {
  const ref = reference[sc.id];
  const appel = M.parserAppel(sc.transcription, sc.id);
  const r = M.rejouer(appel, sc.extraction, sc.relances, sc.crm_avant);

  egal(appel.tours.length, ref.appel.tours, `${sc.id} : nombre de tours`);
  egal(appel.duree, ref.appel.duree, `${sc.id} : durée`);
  egal(appel.date_longue, ref.appel.date, `${sc.id} : date`);

  for (const [chemin, attendu] of Object.entries(ref.verification)) {
    const obtenu = r.verification.resultats[chemin];
    egal([obtenu.statut, obtenu.ligne], [attendu.statut, attendu.ligne], `${sc.id} : citation ${chemin}`);
  }
  egal(Object.keys(r.verification.resultats), Object.keys(ref.verification), `${sc.id} : chemins des citations`);

  const c = ref.conformite;
  egal(r.conformite.recueil.map((l) => [l.cle, l.statut, l.question]), c.recueil.map((l) => [l.cle, l.statut, l.question]), `${sc.id} : recueil`);
  egal(r.conformite.questions, c.questions, `${sc.id} : questions`);
  const regles = (liste) => liste.map((x) => [x.id, x.statut, x.detail, x.action, x.reference, x.sources]);
  egal(regles(r.conformite.adequation), regles(c.adequation), `${sc.id} : règles d'adéquation`);
  egal(regles(r.conformite.lcb), regles(c.lcb), `${sc.id} : règles LCB-FT`);
  egal(r.conformite.niveau_lcb, c.niveau_lcb, `${sc.id} : niveau LCB-FT`);
  egal(r.conformite.pieces, c.pieces, `${sc.id} : pièces`);
  egal(r.conformite.pieces_obligatoires, c.pieces_obligatoires, `${sc.id} : pièces obligatoires`);
  egal(r.conformite.recueil_complet, c.recueil_complet, `${sc.id} : recueil complet`);

  egal(r.statut_relance, ref.statut_relance, `${sc.id} : statut de la relance`);
  egal(r.corrections_relance, ref.corrections_relance, `${sc.id} : corrections`);
  egal(r.controles_relance.map((x) => [x.id, x.statut, x.message]), ref.controles_relance.map((x) => [x.id, x.statut, x.message]), `${sc.id} : linter`);

  const p = ref.plan_crm;
  egal(r.plan.diff, p.diff, `${sc.id} : diff CRM`);
  egal(r.plan.cycle, p.cycle, `${sc.id} : cycle de vie`);
  egal(r.plan.transaction, p.transaction, `${sc.id} : transaction`);
  egal(r.plan.taches, p.taches, `${sc.id} : tâches`);
  egal(r.plan.note_html, p.note_html, `${sc.id} : note`);
  egal(r.plan.operations, p.operations, `${sc.id} : requêtes HubSpot`);
}
console.log(`Parité Python / JavaScript : ${verifications} vérifications, toutes identiques.`);
