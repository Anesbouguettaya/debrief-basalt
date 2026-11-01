/* Tests du moteur de prévision.     node --test prevision/test_moteur.js */
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const T = require("./moteur.js");

const CSV = fs.readFileSync(path.join(__dirname, "donnees-fictives.csv"), "utf8");
const proche = (a, b, tol, msg) => assert.ok(Math.abs(a - b) <= tol, `${msg} : ${a} au lieu de ${b} (±${tol})`);

/** Série synthétique : croissance exponentielle exacte. */
function serie(n, depart, croissance, ticket = 10000, versement = 200) {
  const d = { mois: [], nouveaux: [], collecte: [], encours: [] };
  let mois = "2024-01", cumul = 0, encours = 0;
  for (let t = 0; t < n; t++) {
    const nouveaux = Math.round(depart * Math.exp(croissance * t));
    const collecte = ticket * nouveaux + versement * cumul;
    encours += collecte;
    d.mois.push(mois); d.nouveaux.push(nouveaux); d.collecte.push(collecte); d.encours.push(encours);
    cumul += nouveaux; mois = T.moisSuivant(mois);
  }
  return d;
}

test("mois : suivant, passage d'année et libellé", () => {
  assert.equal(T.moisSuivant("2026-10"), "2026-11");
  assert.equal(T.moisSuivant("2026-12"), "2027-01");
  assert.equal(T.moisSuivant("2026-10", 15), "2028-01");
  assert.equal(T.libelleMois("2027-08"), "août 2027");
});

test("lecture : données fictives, en-tête, formats français", () => {
  const d = T.lireCSV(CSV);
  assert.equal(d.mois.length, 22);
  assert.equal(d.mois[0], "2025-01");
  assert.equal(d.nouveaux[21], 262);
  const f = T.lireCSV("Mois;Nouveaux;Collecte;Encours\n" + Array.from({ length: 9 }, (_, i) =>
    `0${i + 1}/2026;${10 + i};1 234,5 €;43 400 000`).join("\n"));
  assert.equal(f.mois[0], "2026-01");
  assert.equal(f.collecte[0], 1234.5);
  assert.equal(f.encours[0], 43400000);
  const virgules = T.lireCSV(Array.from({ length: 9 }, (_, i) => `2026-0${i + 1},5,100,200`).join("\n"));
  assert.equal(virgules.nouveaux.length, 9);
});

test("lecture : erreurs explicites", () => {
  const neuf = (f) => Array.from({ length: 9 }, (_, i) => f(i)).join("\n");
  assert.throws(() => T.lireCSV("2026-01;5;100;200"), /au moins 9 mois/);
  assert.throws(() => T.lireCSV(neuf((i) => `2026-0${i + 1};5;100`)), /4 colonnes/);
  assert.throws(() => T.lireCSV(neuf((i) => `2026-0${i === 4 ? 7 : i + 1};5;100;200`)), /ne suit pas/);
  assert.throws(() => T.lireCSV(neuf((i) => `${i + 5}/2026;5;100;200`)), /13\/2026.*non reconnu/);
  assert.throws(() => T.lireCSV(neuf((i) => `2026-0${i + 1};${i === 2 ? 0 : 5};100;200`)), /au moins 1/);
  assert.throws(() => T.lireCSV(neuf((i) => `2026-0${i + 1};5;abc;200`)), /n'est pas un nombre/);
  assert.throws(() => T.lireCSV(neuf((i) => `janvier;5;100;200`)), /4 colonnes|non reconnu/);
});

test("filtre : retrouve une croissance exponentielle exacte", () => {
  const y = Array.from({ length: 24 }, (_, t) => Math.log(100) + 0.05 * t);
  const f = T.filtrer(y, { phi: 1, bruit: 0.001, niveau: 0, croissance: 0 });
  const dernier = f.etats[f.etats.length - 1];
  proche(dernier.croissance, 0.05, 1e-3, "croissance estimée");
  proche(dernier.niveau, y[23], 1e-3, "niveau estimé");
  const p = T.prevoirClients({ parametres: { phi: 1, bruit: 0.001, niveau: 0, croissance: 0 }, filtre: f }, 3);
  proche(p.med[2], 100 * Math.exp(0.05 * 26), 0.5, "prévision à 3 mois");
});

test("filtre : covariance symétrique et positive tout au long", () => {
  const y = T.lireCSV(CSV).nouveaux.map(Math.log);
  for (const phi of [1, 0.95, 0.9]) {
    const f = T.filtrer(y, { phi, bruit: 0.12, niveau: 0.025, croissance: 0.01 });
    for (const e of f.etats) {
      assert.ok(e.P11 > 0 && e.P22 >= -1e-15, "variances positives");
      assert.ok(e.P11 * e.P22 - e.P12 * e.P12 >= -1e-12, "covariance positive");
    }
  }
});

test("ajustement : un bruit de mesure plausible sur une série bruitée connue", () => {
  const rnd = T.generateur(7);
  const y = Array.from({ length: 80 }, (_, t) => Math.log(50) + 0.03 * t + 0.1 * rnd.normal());
  const a = T.ajuster(y, 1);
  assert.ok([0.08, 0.12].includes(a.parametres.bruit), `bruit choisi ${a.parametres.bruit}`);
  proche(T.croissanceActuelle(a).taux, Math.exp(0.03) - 1, 0.01, "croissance mensuelle");
});

test("calibrage : retrouve le ticket et le versement exacts", () => {
  const c = T.calibrerCollecte(serie(20, 40, 0.06, 12000, 150));
  proche(c.ticket, 12000, 1e-6, "ticket");
  proche(c.versement, 150, 1e-6, "versement");
  assert.ok(c.dispersion < 1e-9);
});

test("simulation : sans aléa, l'encours suit exactement la récurrence", () => {
  const d = serie(12, 100, 0);
  const ajustement = {
    parametres: { phi: 1, bruit: 0, niveau: 0, croissance: 0 },
    filtre: { suivant: { niveau: Math.log(100), croissance: 0, P11: 0, P12: 0, P22: 0 } },
  };
  const calibrage = { ticket: 10000, versement: 200, dispersion: 0, clients: 1200 };
  const hyp = { rachats: 0.05, partUC: 0.4, fondsEuros: 0.03, rendementUC: 0.06, volatiliteUC: 0 };
  const s = T.simuler(d, ajustement, calibrage, hyp, 3, null, 50, 1);
  let e = d.encours[11], clients = 1200;
  const r = 0.6 * (Math.pow(1.03, 1 / 12) - 1) + 0.4 * 0.005, rachat = 1 - Math.pow(0.95, 1 / 12);
  for (let h = 0; h < 3; h++) {
    e = e * (1 + r - rachat) + 10000 * 100 + 200 * clients;
    clients += 100;
    proche(s.encours.med[h], e, 1e-6 * e, `encours au mois ${h + 1}`);
    proche(s.encours.b80[h], e, 1e-6 * e, `pas de dispersion au mois ${h + 1}`);
  }
});

test("simulation : reproductible, fourchettes ordonnées, horizon cohérent", () => {
  const d = T.lireCSV(CSV);
  const a = T.analyser(d, { horizon: 18, objectif: 100e6 });
  const b = T.analyser(d, { horizon: 18, objectif: 100e6 });
  assert.deepEqual(a.encours, b.encours);
  for (const s of [a.encours, a.clients]) {
    for (let h = 0; h < 18; h++) {
      assert.ok(s.b80[h] <= s.b50[h] && s.b50[h] <= s.med[h] && s.med[h] <= s.h50[h] && s.h50[h] <= s.h80[h], `ordre des quantiles au mois ${h + 1}`);
    }
  }
  const long = T.analyser(d, { horizon: 24, objectif: 100e6 });
  assert.deepEqual(long.encours.med.slice(0, 18), a.encours.med, "les 18 premiers mois ne dépendent pas de l'horizon");
  assert.equal(long.objectif.mediane, a.objectif.mediane);
  assert.equal(a.moisPrevus[0], "2026-11");
  assert.equal(a.moisPrevus.length, 18);
});

test("test sur l'historique : aucune donnée future n'est utilisée", () => {
  const d = T.lireCSV(CSV);
  const t1 = T.tester(d, 0.95);
  const modifie = { ...d, nouveaux: d.nouveaux.slice() };
  modifie.nouveaux[21] = 999;
  const t2 = T.tester(modifie, 0.95);
  assert.equal(t1.n, 11);
  for (let i = 0; i < t1.n; i++) {
    assert.equal(t2.points[i].prevu, t1.points[i].prevu, `prévision depuis ${t1.points[i].depuis}`);
  }
  assert.equal(t2.points[t2.n - 1].reel, 999);
});

test("analyse : choix automatique du ralentissement par l'historique", () => {
  const d = T.lireCSV(CSV);
  const a = T.analyser(d, { horizon: 12 });
  const essais = a.amortissement.choix.essais;
  const meilleur = Object.keys(essais).reduce((x, y) => (essais[x] <= essais[y] ? x : y));
  assert.equal(a.amortissement.nom, meilleur);
  const court = T.analyser(T.couper(d, 9), { horizon: 12 });
  assert.equal(court.amortissement.nom, "modere", "trop peu de mois pour tester : valeur par défaut");
  assert.equal(court.amortissement.choix.automatique, false);
});

test("page : les données fictives intégrées sont celles du fichier CSV", () => {
  const page = fs.readFileSync(path.join(__dirname, "index.html"), "utf8");
  const integre = page.match(/<script type="text\/plain" id="donnees-fictives">([\s\S]*?)<\/script>/)[1].trim();
  assert.equal(integre, CSV.trim());
});
