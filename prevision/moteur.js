/* Trajectoire : prévoir la croissance d'une jeune entreprise avec peu de données.

   1. Filtre de Kalman sur le logarithme des nouveaux clients mensuels : il estime
      le niveau et la croissance malgré le bruit (tendance amortie : la croissance
      d'une jeune entreprise ralentit en grandissant). Les trois variances du
      modèle sont choisies par maximum de vraisemblance sur l'historique.
   2. Calibrage de la collecte par moindres carrés : ticket du premier versement
      et versement mensuel moyen des clients déjà là.
   3. Monte-Carlo : des milliers de futurs possibles (acquisition + marchés) pour
      l'encours, d'où les fourchettes et la probabilité d'atteindre un objectif.
   4. Test sur l'historique : à chaque mois passé, on prévoit 3 mois plus loin
      sans regarder la suite, et on compare à ce qui s'est réellement passé.

   JavaScript sans dépendance : tourne dans le navigateur, dans Node et dans un
   nœud Code de n8n. */
(function (racine, fabrique) {
  if (typeof module === "object" && module.exports) module.exports = fabrique();
  else racine.Trajectoire = fabrique();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const Z80 = 1.2815515655446004; // quantile 90 % de la loi normale : fourchette 80 %
  const Z50 = 0.6744897501960817; // quantile 75 % : fourchette 50 %
  const AMORTISSEMENTS = { aucun: 1, modere: 0.95, fort: 0.9 };
  const GRILLE = {
    bruit: [0.03, 0.05, 0.08, 0.12, 0.18, 0.27],      // écart-type de mesure (log)
    niveau: [0, 0.01, 0.025, 0.05, 0.1],              // à-coups du niveau
    croissance: [0, 0.004, 0.01, 0.02, 0.04],         // dérive de la croissance
  };
  const MIN_MOIS = 9;
  const MAX_MOIS = 120;
  const NOMS_MOIS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."];

  // ── Mois ─────────────────────────────────────────────────────────────────
  function moisSuivant(mois, k = 1) {
    const a = Number(mois.slice(0, 4)), m = Number(mois.slice(5, 7)) - 1 + k;
    const an = a + Math.floor(m / 12), mo = ((m % 12) + 12) % 12;
    return `${an}-${String(mo + 1).padStart(2, "0")}`;
  }
  function libelleMois(mois) {
    return `${NOMS_MOIS[Number(mois.slice(5, 7)) - 1]} ${mois.slice(0, 4)}`;
  }

  // ── Lecture des données ─────────────────────────────────────────────────
  function nombre(brut, ligne, colonne) {
    const propre = String(brut).replace(/[\s  €]/g, "").replace(",", ".");
    const n = Number(propre);
    if (propre === "" || !Number.isFinite(n)) throw new Error(`Ligne ${ligne} : « ${String(brut).trim()} » n'est pas un nombre (colonne ${colonne}).`);
    return n;
  }
  function lireMois(brut, ligne) {
    const s = String(brut).trim();
    let an = null, mo = 0, m;
    if ((m = s.match(/^(\d{4})[-/.](\d{1,2})$/))) { an = m[1]; mo = Number(m[2]); }
    else if ((m = s.match(/^(\d{1,2})[-/.](\d{4})$/))) { an = m[2]; mo = Number(m[1]); }
    if (!an || mo < 1 || mo > 12) throw new Error(`Ligne ${ligne} : mois « ${s} » non reconnu (attendu AAAA-MM, par exemple 2026-01).`);
    return `${an}-${String(mo).padStart(2, "0")}`;
  }
  /** Lit « mois;nouveaux_clients;collecte;encours » (séparateur ; , ou tabulation). */
  function lireCSV(texte) {
    const lignes = String(texte).split(/\r?\n/).map((l, i) => ({ texte: l.trim(), num: i + 1 })).filter((l) => l.texte);
    const donnees = { mois: [], nouveaux: [], collecte: [], encours: [] };
    for (const [i, { texte: l, num }] of lignes.entries()) {
      const sep = l.includes(";") ? ";" : l.includes("\t") ? "\t" : ",";
      const champs = l.split(sep);
      if (i === 0 && /[a-zé]/i.test(champs[0]) && !/^\d/.test(champs[0].trim())) continue; // en-tête
      if (champs.length < 4) throw new Error(`Ligne ${num} : 4 colonnes attendues (mois, nouveaux clients, collecte, encours), ${champs.length} trouvée${champs.length > 1 ? "s" : ""}.`);
      const mois = lireMois(champs[0], num);
      const n = nombre(champs[1], num, "nouveaux clients");
      const c = nombre(champs[2], num, "collecte");
      const e = nombre(champs[3], num, "encours");
      if (n < 1 || !Number.isInteger(n)) throw new Error(`Ligne ${num} : le nombre de nouveaux clients doit être un entier d'au moins 1.`);
      if (c < 0 || e < 0) throw new Error(`Ligne ${num} : la collecte et l'encours ne peuvent pas être négatifs.`);
      if (donnees.mois.length && mois !== moisSuivant(donnees.mois[donnees.mois.length - 1])) {
        throw new Error(`Ligne ${num} : ${libelleMois(mois)} ne suit pas ${libelleMois(donnees.mois[donnees.mois.length - 1])}. Les mois doivent se suivre, sans trou.`);
      }
      donnees.mois.push(mois); donnees.nouveaux.push(n); donnees.collecte.push(c); donnees.encours.push(e);
    }
    if (donnees.mois.length < MIN_MOIS) throw new Error(`Il faut au moins ${MIN_MOIS} mois d'historique (${donnees.mois.length} trouvé${donnees.mois.length > 1 ? "s" : ""}).`);
    if (donnees.mois.length > MAX_MOIS) throw new Error(`Au plus ${MAX_MOIS} mois d'historique.`);
    return donnees;
  }
  function couper(donnees, k) {
    return { mois: donnees.mois.slice(0, k), nouveaux: donnees.nouveaux.slice(0, k), collecte: donnees.collecte.slice(0, k), encours: donnees.encours.slice(0, k) };
  }

  // ── Filtre de Kalman : état (niveau, croissance) du log des nouveaux clients ──
  //   niveau(t+1)     = niveau(t) + croissance(t) + bruit
  //   croissance(t+1) = phi · croissance(t)       + bruit
  //   mesure(t)       = niveau(t)                 + bruit de mesure
  function filtrer(y, p) {
    const R = p.bruit * p.bruit, ql = p.niveau * p.niveau, qb = p.croissance * p.croissance, phi = p.phi;
    let l = y[0], b = 0, P11 = 1, P12 = 0, P22 = 0.04; // a priori : niveau inconnu, croissance ±20 %/mois
    let logv = 0;
    const etats = [];
    for (let t = 0; t < y.length; t++) {
      const v = y[t] - l, S = P11 + R;
      if (t >= 2) logv -= 0.5 * (Math.log(2 * Math.PI * S) + (v * v) / S);
      const K1 = P11 / S, K2 = P12 / S;
      l += K1 * v; b += K2 * v;
      const n11 = P11 - K1 * P11, n12 = P12 - K1 * P12, n22 = P22 - K2 * P12;
      P11 = n11; P12 = n12; P22 = n22;
      etats.push({ niveau: l, croissance: b, P11, P12, P22 });
      // prédiction du mois suivant : P = F P Fᵀ + Q, F = [[1, 1], [0, phi]]
      const a11 = P11 + 2 * P12 + P22 + ql, a12 = phi * (P12 + P22), a22 = phi * phi * P22 + qb;
      l = l + b; b = phi * b; P11 = a11; P12 = a12; P22 = a22;
    }
    return { etats, logv, suivant: { niveau: l, croissance: b, P11, P12, P22 } };
  }

  /** Choisit les variances par maximum de vraisemblance (grille). */
  function ajuster(y, phi) {
    let meilleur = null;
    for (const bruit of GRILLE.bruit) for (const niveau of GRILLE.niveau) for (const croissance of GRILLE.croissance) {
      const p = { phi, bruit, niveau, croissance };
      const f = filtrer(y, p);
      if (!meilleur || f.logv > meilleur.filtre.logv + 1e-9) meilleur = { parametres: p, filtre: f };
    }
    return meilleur;
  }

  /** Prévision analytique (loi log-normale) des nouveaux clients sur H mois. */
  function prevoirClients(ajustement, H) {
    const p = ajustement.parametres, s = ajustement.filtre.suivant;
    const R = p.bruit ** 2, ql = p.niveau ** 2, qb = p.croissance ** 2, phi = p.phi;
    let { niveau: l, croissance: b, P11, P12, P22 } = s;
    const sortie = { med: [], b80: [], h80: [], b50: [], h50: [] };
    for (let h = 1; h <= H; h++) {
      const sd = Math.sqrt(P11 + R);
      sortie.med.push(Math.exp(l));
      sortie.b80.push(Math.exp(l - Z80 * sd)); sortie.h80.push(Math.exp(l + Z80 * sd));
      sortie.b50.push(Math.exp(l - Z50 * sd)); sortie.h50.push(Math.exp(l + Z50 * sd));
      const a11 = P11 + 2 * P12 + P22 + ql, a12 = phi * (P12 + P22), a22 = phi * phi * P22 + qb;
      l = l + b; b = phi * b; P11 = a11; P12 = a12; P22 = a22;
    }
    return sortie;
  }

  /** Croissance mensuelle estimée au dernier mois connu, avec sa fourchette 80 %. */
  function croissanceActuelle(ajustement) {
    const e = ajustement.filtre.etats[ajustement.filtre.etats.length - 1];
    const sd = Math.sqrt(Math.max(e.P22, 0));
    return { taux: Math.exp(e.croissance) - 1, bas: Math.exp(e.croissance - Z80 * sd) - 1, haut: Math.exp(e.croissance + Z80 * sd) - 1 };
  }

  // ── Calibrage de la collecte : collecte(t) = ticket · nouveaux(t) + versement · clients(t-1) ──
  function calibrerCollecte(donnees) {
    let snn = 0, snc = 0, scc = 0, sny = 0, scy = 0, cumul = 0;
    const lignes = [];
    for (let t = 0; t < donnees.mois.length; t++) {
      const n = donnees.nouveaux[t], c = cumul, y = donnees.collecte[t];
      snn += n * n; snc += n * c; scc += c * c; sny += n * y; scy += c * y;
      lignes.push({ n, c, y });
      cumul += n;
    }
    const det = snn * scc - snc * snc;
    let ticket = det > 0 ? (sny * scc - scy * snc) / det : sny / snn;
    let versement = det > 0 ? (snn * scy - snc * sny) / det : 0;
    if (versement < 0) { versement = 0; ticket = sny / snn; }
    if (ticket < 0) { ticket = 0; versement = scc > 0 ? scy / scc : 0; }
    // dispersion relative autour de l'ajustement (utilisée dans les simulations)
    let s2 = 0, k = 0;
    for (const { n, c, y } of lignes) {
      const ajuste = ticket * n + versement * c;
      if (ajuste > 0 && y > 0) { s2 += Math.log(y / ajuste) ** 2; k++; }
    }
    return { ticket, versement, dispersion: k > 1 ? Math.sqrt(s2 / (k - 1)) : 0.1, clients: cumul };
  }

  // ── Hasard reproductible ────────────────────────────────────────────────
  function generateur(graine) {
    let a = graine >>> 0, reserve = null;
    const uniforme = () => {
      a = (a + 0x6d2b79f5) >>> 0;
      let t = a;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
    const normal = () => {
      if (reserve !== null) { const r = reserve; reserve = null; return r; }
      let u = 0;
      while (u <= 1e-12) u = uniforme();
      const v = uniforme(), rayon = Math.sqrt(-2 * Math.log(u));
      reserve = rayon * Math.sin(2 * Math.PI * v);
      return rayon * Math.cos(2 * Math.PI * v);
    };
    return { uniforme, normal };
  }
  function quantile(trie, q) {
    const pos = (trie.length - 1) * q, i = Math.floor(pos), f = pos - i;
    return i + 1 < trie.length ? trie[i] * (1 - f) + trie[i + 1] * f : trie[i];
  }

  const HYPOTHESES = {
    rachats: 0.05,          // part de l'encours retirée par an
    partUC: 0.4,            // part investie en unités de compte
    fondsEuros: 0.03,       // rendement annuel du fonds en euros
    rendementUC: 0.05,      // rendement annuel espéré des UC
    volatiliteUC: 0.15,     // volatilité annuelle des UC
  };

  /** Simule l'encours : acquisition incertaine (filtre) × collecte calibrée × marchés. */
  function simuler(donnees, ajustement, calibrage, hyp, H, objectif, nombreSimulations = 2000, graine = 2026) {
    const h_ = { ...HYPOTHESES, ...hyp };
    const p = ajustement.parametres, s = ajustement.filtre.suivant;
    const rEuros = Math.pow(1 + h_.fondsEuros, 1 / 12) - 1;
    const rachat = 1 - Math.pow(1 - h_.rachats, 1 / 12);
    const muUC = h_.rendementUC / 12, sdUC = h_.volatiliteUC / Math.sqrt(12);
    // Cholesky de la covariance de l'état du mois suivant
    const L11 = Math.sqrt(Math.max(s.P11, 0)), L21 = L11 > 0 ? s.P12 / L11 : 0;
    const L22 = Math.sqrt(Math.max(s.P22 - L21 * L21, 0));
    const encoursDepart = donnees.encours[donnees.encours.length - 1];
    const traj = Array.from({ length: H }, () => new Float64Array(nombreSimulations));
    const franchi = new Float64Array(nombreSimulations);
    const sc = calibrage.dispersion;
    for (let k = 0; k < nombreSimulations; k++) {
      // un générateur par trajectoire : changer l'horizon ne change pas les premiers mois
      const rnd = generateur((graine ^ Math.imul(k + 1, 0x9e3779b1)) >>> 0);
      const z1 = rnd.normal(), z2 = rnd.normal();
      let l = s.niveau + L11 * z1, b = s.croissance + L21 * z1 + L22 * z2;
      let clients = calibrage.clients, encours = encoursDepart;
      franchi[k] = Infinity;
      for (let h = 0; h < H; h++) {
        if (h > 0) { l = l + b + p.niveau * rnd.normal(); b = p.phi * b + p.croissance * rnd.normal(); }
        const nouveaux = Math.exp(l + p.bruit * rnd.normal());
        const collecte = (calibrage.ticket * nouveaux + calibrage.versement * clients) * Math.exp(sc * rnd.normal() - (sc * sc) / 2);
        const r = (1 - h_.partUC) * rEuros + h_.partUC * (muUC + sdUC * rnd.normal());
        encours = encours * (1 + r - rachat) + collecte;
        clients += nouveaux;
        traj[h][k] = encours;
        if (objectif && franchi[k] === Infinity && encours >= objectif) franchi[k] = h;
      }
    }
    const sortie = { med: [], b80: [], h80: [], b50: [], h50: [] };
    for (let h = 0; h < H; h++) {
      const trie = Array.from(traj[h]).sort((x, y) => x - y);
      sortie.med.push(quantile(trie, 0.5));
      sortie.b80.push(quantile(trie, 0.1)); sortie.h80.push(quantile(trie, 0.9));
      sortie.b50.push(quantile(trie, 0.25)); sortie.h50.push(quantile(trie, 0.75));
    }
    let atteint = null;
    if (objectif) {
      const fin = traj[H - 1];
      let n = 0;
      for (let k = 0; k < nombreSimulations; k++) if (fin[k] >= objectif) n++;
      const dates = Array.from(franchi).sort((x, y) => x - y);
      const pos = (q) => { const v = dates[Math.floor(q * (dates.length - 1))]; return Number.isFinite(v) ? v : null; };
      atteint = { probabilite: n / nombreSimulations, mediane: pos(0.5), tot: pos(0.1), tard: pos(0.9) };
    }
    return { encours: sortie, objectif: atteint };
  }

  /** Test sur l'historique : prévision à « pas » mois, sans regarder la suite. */
  function tester(donnees, phi, pas = 3, debut = MIN_MOIS) {
    const y = donnees.nouveaux.map(Math.log), points = [];
    for (let k = debut; k + pas <= y.length; k++) {
      const a = ajuster(y.slice(0, k), phi);
      const p = prevoirClients(a, pas);
      const reel = donnees.nouveaux[k - 1 + pas];
      points.push({
        depuis: donnees.mois[k - 1], vise: donnees.mois[k - 1 + pas], reel,
        prevu: p.med[pas - 1], bas: p.b80[pas - 1], haut: p.h80[pas - 1],
        naif: donnees.nouveaux[k - 1],
      });
    }
    if (!points.length) return { points, n: 0 };
    const erreur = (prevu, reel) => Math.abs(prevu - reel) / reel;
    const moy = (f) => points.reduce((s, x) => s + f(x), 0) / points.length;
    return {
      points, n: points.length, pas,
      erreur: moy((x) => erreur(x.prevu, x.reel)),
      erreurNaive: moy((x) => erreur(x.naif, x.reel)),
      dansFourchette: points.filter((x) => x.reel >= x.bas && x.reel <= x.haut).length,
    };
  }

  /** Choisit le ralentissement qui a le mieux prévu le passé (validation sur l'historique). */
  function choisirAmortissement(donnees) {
    let meilleur = null;
    const essais = {};
    for (const [nom, phi] of Object.entries(AMORTISSEMENTS)) {
      const t = tester(donnees, phi);
      essais[nom] = t.n ? t.erreur : null;
      if (t.n && (!meilleur || t.erreur < meilleur.erreur - 1e-12)) meilleur = { nom, erreur: t.erreur };
    }
    return { nom: meilleur ? meilleur.nom : "modere", essais, automatique: Boolean(meilleur) };
  }

  /** Analyse complète à partir des données connues. */
  function analyser(donnees, reglages = {}) {
    const H = reglages.horizon || 12;
    let choix = null, nomAmortissement = reglages.amortissement || "auto";
    if (nomAmortissement === "auto") { choix = choisirAmortissement(donnees); nomAmortissement = choix.nom; }
    const phi = AMORTISSEMENTS[nomAmortissement] ?? 0.95;
    const y = donnees.nouveaux.map(Math.log);
    const ajustement = ajuster(y, phi);
    const calibrage = calibrerCollecte(donnees);
    const clients = prevoirClients(ajustement, H);
    const sim = simuler(donnees, ajustement, calibrage, reglages.hypotheses, H, reglages.objectif, reglages.simulations || 2000, reglages.graine || 2026);
    const dernier = donnees.mois[donnees.mois.length - 1];
    return {
      dernierMois: dernier,
      moisPrevus: Array.from({ length: H }, (_, h) => moisSuivant(dernier, h + 1)),
      parametres: ajustement.parametres,
      amortissement: { nom: nomAmortissement, choix },
      croissance: croissanceActuelle(ajustement),
      calibrage, clients, encours: sim.encours, objectif: sim.objectif,
    };
  }

  return {
    AMORTISSEMENTS, HYPOTHESES, MIN_MOIS, moisSuivant, libelleMois, lireCSV, couper,
    filtrer, ajuster, prevoirClients, croissanceActuelle, calibrerCollecte, simuler, tester, choisirAmortissement, analyser, generateur,
  };
});
