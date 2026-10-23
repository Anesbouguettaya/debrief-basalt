/* Débrief : moteur de la démo web.
   Port fidèle de debrief/transcript.py, grounding.py, compliance.py,
   email_lint.py et hubspot.py : mêmes chemins de citations, mêmes règles,
   mêmes seuils. Un test de parité compare ses décisions à celles du paquet
   Python sur les appels de démo. */
(function (racine, fabrique) {
  if (typeof module === "object" && module.exports) module.exports = fabrique();
  else racine.DebriefMoteur = fabrique();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  /* ---------- Configuration (config.py) ---------- */
  const POLITIQUE = {
    version: "0.3",
    seuil_justificatif_eur: 150000,
    ratio_revenus_vigilance: 2.0,
    uc_max_par_profil: { prudent: 30, equilibre: 70, dynamique: 100 },
    horizon_court_annees: 5,
    uc_max_horizon_court: 50,
    nb_vigilances_escalade: 3,
    proprietes_retenues_si_escalade: ["origine_des_fonds"],
  };
  const PRODUIT = "Basalt Life";
  const TARIFS = {
    "claude-sonnet-5-5": { input: 2.0, output: 10.0 },
    "claude-haiku-5-5": { input: 0.1, output: 0.5 },
  };
  const CARACTERES_PAR_TOKEN = 2.5;
  const EVENEMENTS_PATRIMONIAUX = new Set(["succession", "donation", "cession_immobiliere", "cession_entreprise"]);
  const PIECES_SOCLE = [
    "Pièce d'identité en cours de validité",
    "Justificatif de domicile de moins de 3 mois",
    "RIB d'un compte au nom du souscripteur",
  ];
  const PIECE_PAR_ORIGINE = {
    succession: "Attestation du notaire (succession)",
    donation: "Acte de donation ou déclaration de don manuel",
    cession_immobiliere: "Acte de vente notarié",
    cession_entreprise: "Acte de cession des titres",
    epargne: "Relevés des comptes d'où proviennent les fonds",
    revenus_professionnels: "Derniers avis d'imposition",
    autre: "Justificatif adapté à l'origine déclarée",
  };
  const LIBELLES_ORIGINE = {
    epargne: "épargne", succession: "succession", donation: "donation",
    cession_immobiliere: "cession immobilière", cession_entreprise: "cession d'entreprise",
    revenus_professionnels: "revenus professionnels", autre: "autre", floue: "non précisée", non_abordee: "non abordée",
  };
  const LIBELLES_CRM = {
    jobtitle: "Profession", situation_familiale: "Situation familiale", revenus_annuels: "Revenus annuels",
    patrimoine_financier: "Patrimoine financier", patrimoine_immobilier: "Patrimoine immobilier",
    objectif_principal: "Objectif principal", horizon_placement: "Horizon de placement",
    profil_risque_pressenti: "Profil de risque (pressenti)", experience_financiere: "Expérience financière",
    preference_durabilite: "Préférences de durabilité", origine_des_fonds: "Origine des fonds",
    montant_envisage: "Montant envisagé (€)", versement_programme: "Versements programmés",
    contrats_existants: "Contrats existants", clause_beneficiaire: "Clause bénéficiaire envisagée",
    date_prochain_contact: "Prochain contact",
  };
  const LIBELLES_PROFIL = { prudent: "prudent", equilibre: "équilibré", dynamique: "dynamique", indetermine: "indéterminé" };
  const REF_DDA = "Art. L522-5 C. assur. ; Règl. délégué (UE) 2017/2359";
  const REF_DURABILITE = "Règl. délégué (UE) 2021/1257";
  const REF_CONNAISSANCE = "Art. L561-6 CMF";
  const REF_PPE = "Art. L561-10 CMF";
  const ITEMS_RECUEIL = [
    ["objectifs", "Objectifs du placement", "Quel est l'objectif principal de ce placement : transmission, retraite, projet, revenus complémentaires ?", true],
    ["horizon", "Horizon de placement", "À quel horizon pensez-vous avoir besoin de tout ou partie de ces sommes ?", true],
    ["situation_familiale", "Situation familiale", "Quelle est votre situation familiale : régime matrimonial, enfants à charge ?", true],
    ["situation_professionnelle", "Situation professionnelle", "Quelle est votre profession et votre statut ?", true],
    ["revenus", "Revenus", "Quel est le montant approximatif de vos revenus annuels ?", true],
    ["patrimoine", "Patrimoine et épargne de précaution", "Comment se répartit votre patrimoine, et quelle épargne de précaution conservez-vous ?", true],
    ["connaissances_experience", "Connaissances et expérience", "Avez-vous déjà investi en unités de compte, actions, ETF ou SCPI ? Depuis quand ?", true],
    ["tolerance_risque", "Tolérance au risque", "Comment réagiriez-vous si votre placement baissait temporairement de 10 à 20 % ?", true],
    ["capacite_pertes", "Capacité à subir des pertes", "Quelle perte pourriez-vous supporter sans que votre niveau de vie en soit affecté ?", true],
    ["durabilite", "Préférences de durabilité", "Souhaitez-vous qu'une partie de votre épargne soit investie selon des critères de durabilité (environnement, social, exclusions sectorielles) ?", true],
    ["besoin_liquidite", "Besoin de disponibilité", "Pourriez-vous avoir besoin de récupérer une partie de cette somme dans les deux prochaines années ?", false],
  ];
  const CLES_RECUEIL = ITEMS_RECUEIL.map((i) => i[0]);

  /* ---------- Transcription (transcript.py) ---------- */
  const JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"];
  const MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"];

  function dateLongue(iso) {
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso || "");
    if (!m) return iso || "date inconnue";
    const d = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3]));
    return `${JOURS[(d.getUTCDay() + 6) % 7]} ${+m[3]} ${MOIS[+m[2] - 1]} ${m[1]}`;
  }

  function parserAppel(texte, identifiant) {
    const meta = {};
    const brut = [];
    for (let ligne of String(texte).split(/\r\n|\r|\n/)) {
      ligne = ligne.trim();
      if (!ligne) continue;
      let m = /^#\s*([^:]+?)\s*:\s*(.*)$/.exec(ligne);
      if (m) { meta[m[1].trim().toLowerCase()] = m[2].trim(); continue; }
      m = /^\[(\d{1,2}:\d{2}(?::\d{2})?)\]\s*([^:]+?)\s*:\s*(.+)$/.exec(ligne);
      if (m) { brut.push([m[1], m[2].trim(), m[3].trim()]); continue; }
      m = /^([^\[#:][^:]{0,60}?)\s*:\s*(.+)$/.exec(ligne);
      if (m) brut.push(["", m[1].trim(), m[2].trim()]);
      else if (brut.length) brut[brut.length - 1][2] += " " + ligne;
    }
    const conseiller = (meta["conseiller"] || "").toLowerCase();
    const tours = brut.map(([h, loc, txt], i) => ({
      numero: i + 1, horodatage: h, locuteur: loc, texte: txt,
      role: conseiller ? (loc.toLowerCase() === conseiller ? "conseiller" : "client")
                       : (/conseill|basalt/i.test(loc) ? "conseiller" : "client"),
    }));
    const dateBrute = (meta["date"] || "").split(" ");
    const dateIso = dateBrute[0] || "";
    const heure = dateBrute.length > 1 ? dateBrute[1] : "";
    let duree = "";
    const dernier = tours[tours.length - 1];
    if (dernier && dernier.horodatage) {
      const p = dernier.horodatage.split(":").map(Number);
      const s = p[p.length - 1] + 60 * p[p.length - 2] + (p.length === 3 ? 3600 * p[0] : 0);
      duree = `${Math.floor(s / 60)} min ${String(s % 60).padStart(2, "0")} s`;
    }
    return {
      identifiant: meta["identifiant"] || identifiant || "appel", meta, tours,
      conseiller: meta["conseiller"] || (tours.find((t) => t.role === "conseiller") || {}).locuteur || "Conseiller",
      client: meta["client"] || (tours.find((t) => t.role === "client") || {}).locuteur || "Client",
      date_iso: dateIso, heure, date_longue: dateLongue(dateIso), contact_id: meta["contact hubspot"] || "", duree,
    };
  }

  function texteParModele(appel) {
    return appel.tours.map((t) => `${t.horodatage ? `[${t.horodatage}] ` : ""}${t.locuteur} (${t.role}) : ${t.texte}`).join("\n");
  }

  /* ---------- Vérification des sources (grounding.py) ---------- */
  const SEUIL_APPROCHE = 0.85;

  function normaliser(texte) {
    return String(texte).normalize("NFKD").replace(/[̀-ͯ]/g, "").toLowerCase()
      .replace(/[^a-z0-9]+/g, " ").trim().replace(/(\d) (?=\d{3}(?:\D|$))/g, "$1");
  }

  function lcs(a, b) {
    let prec = new Array(b.length + 1).fill(0);
    for (const x of a) {
      const cour = [0];
      for (let j = 1; j <= b.length; j++) cour.push(x === b[j - 1] ? prec[j - 1] + 1 : Math.max(prec[j], cour[j - 1]));
      prec = cour;
    }
    return prec[prec.length - 1];
  }

  function localiser(citation, tours, cache) {
    const q = normaliser(citation || "");
    if (!q) return { statut: "vide", ligne: null, score: 0 };
    const mots = q.split(" ");
    const normalises = cache || tours.map((t) => normaliser(t.texte));
    for (let i = 0; i < tours.length; i++) {
      if ((" " + normalises[i] + " ").includes(" " + q + " ")) {
        return { statut: mots.length >= 2 ? "verifiee" : "approchee", ligne: tours[i].numero, score: 1 };
      }
    }
    let meilleur = 0, ligne = null;
    const largeur = mots.length + Math.max(1, Math.floor(0.3 * mots.length + 0.5));
    for (let i = 0; i < tours.length; i++) {
      const t = normalises[i] ? normalises[i].split(" ") : [];
      if (!t.length) continue;
      const fin = Math.max(1, t.length - largeur + 1);
      for (let debut = 0; debut < fin; debut++) {
        const score = lcs(mots, t.slice(debut, debut + largeur)) / mots.length;
        if (score > meilleur) { meilleur = score; ligne = tours[i].numero; }
      }
    }
    if (meilleur >= SEUIL_APPROCHE && mots.length >= 3) return { statut: "approchee", ligne, score: Math.round(meilleur * 100) / 100 };
    return { statut: "introuvable", ligne: null, score: Math.round(meilleur * 100) / 100 };
  }

  function sources(a) {
    const s = [];
    const cr = a.compte_rendu;
    cr.points_cles.forEach((p, i) => s.push([`compte_rendu.points_cles[${i}]`, p.source]));
    cr.questions_client.forEach((q, i) => s.push([`compte_rendu.questions_client[${i}]`, q.source]));
    cr.objections.forEach((o, i) => s.push([`compte_rendu.objections[${i}]`, o.source]));
    cr.prochaines_etapes.forEach((e, i) => s.push([`compte_rendu.prochaines_etapes[${i}]`, e.source]));
    s.push(["compte_rendu.intention", cr.intention_source]);
    CLES_RECUEIL.forEach((c) => s.push([`recueil.${c}`, a.recueil[c].source]));
    const p = a.projet;
    s.push(["projet.montant", p.montant_source], ["projet.versement", p.versement_source], ["projet.profil", p.profil_source],
      ["projet.uc_souhaitee", p.uc_souhaitee_source], ["projet.uc_recommandee", p.uc_recommandee_source],
      ["projet.mise_en_garde", p.mise_en_garde_source]);
    const l = a.lcb;
    s.push(["lcb.origine", l.origine_source], ["lcb.revenus", l.revenus_source], ["lcb.tiers_payeur", l.tiers_payeur_source],
      ["lcb.especes", l.especes_source], ["lcb.ppe", l.ppe_source]);
    l.signaux.forEach((x, i) => s.push([`lcb.signaux[${i}]`, x.source]));
    a.crm.champs.forEach((c, i) => s.push([`crm.champs[${i}]`, c.source]));
    s.push(["crm.date_cloture", a.crm.date_cloture_source]);
    return s;
  }

  function verifier(a, tours) {
    const cache = tours.map((t) => normaliser(t.texte));
    const resultats = {}, citations = {};
    for (const [chemin, citation] of sources(a)) {
      resultats[chemin] = localiser(citation, tours, cache);
      citations[chemin] = citation;
    }
    const valeurs = Object.values(resultats);
    return {
      resultats, citations,
      get: (ch) => resultats[ch] || { statut: "vide", ligne: null, score: 0 },
      fiable: (ch) => ["verifiee", "approchee"].includes((resultats[ch] || {}).statut),
      total: valeurs.filter((c) => c.statut !== "vide").length,
      retrouvees: valeurs.filter((c) => c.statut === "verifiee" || c.statut === "approchee").length,
      introuvables: Object.keys(resultats).filter((ch) => resultats[ch].statut === "introuvable"),
    };
  }

  /* ---------- Règles DDA et LCB-FT (compliance.py) ---------- */
  const eur = (m) => String(Math.round(m)).replace(/\B(?=(\d{3})+(?!\d))/g, " ") + " €";
  const fois = (r) => r.toFixed(1).replace(".", ",") + " fois";
  const regle = (id, titre, statut, detail, action = "", reference = "", sources = []) => ({ id, titre, statut, detail, action, reference, sources });

  function evaluerRecueil(a, v) {
    return ITEMS_RECUEIL.map(([cle, libelle, question, requis]) => {
      const item = a.recueil[cle];
      let statut = item.statut;
      if (statut !== "manquant" && !v.fiable(`recueil.${cle}`)) statut = "a_verifier";
      return { cle, libelle, requis, statut, valeur: statut !== "manquant" ? item.valeur : "", question: statut === "couvert" ? "" : question };
    });
  }

  function evaluerAdequation(a, v, recueil, pol) {
    const regles = [];
    const p = a.projet;
    const manquants = recueil.filter((l) => l.requis && l.statut !== "couvert").map((l) => l.libelle.toLowerCase());
    if (!manquants.length) {
      regles.push(regle("ADQ-01", "Recueil des exigences et besoins", "ok", "Les rubriques requises sont renseignées et sourcées.", "", REF_DDA));
    } else if (manquants.length >= 4) {
      regles.push(regle("ADQ-01", "Recueil des exigences et besoins", "vigilance",
        `${manquants.length} rubriques non recueillies : aucune recommandation ne peut être formalisée.`,
        "Compléter le recueil avant toute proposition.", REF_DDA));
    } else {
      regles.push(regle("ADQ-01", "Recueil des exigences et besoins", "action", "À compléter : " + manquants.join(", ") + ".",
        "Poser les questions listées au prochain échange.",
        manquants.length === 1 && manquants[0] === "préférences de durabilité" ? REF_DURABILITE : REF_DDA));
    }
    const profil = (p.profil_pressenti === "indetermine" || v.fiable("projet.profil")) ? p.profil_pressenti : "indetermine";
    const plafond = pol.uc_max_par_profil[profil];
    if (profil === "indetermine") {
      regles.push(regle("ADQ-02", "Profil de risque", "action", "Profil de risque non établi pendant l'appel.",
        "Faire compléter le questionnaire de profil de risque.", REF_DDA));
    } else {
      regles.push(regle("ADQ-02", "Profil de risque", "ok", `Profil pressenti : ${LIBELLES_PROFIL[profil]}, à confirmer par le questionnaire.`,
        "", REF_DDA, ["projet.profil"]));
    }
    const miseEnGarde = p.mise_en_garde_orale === "oui" && v.fiable("projet.mise_en_garde");
    if (plafond !== undefined && p.uc_souhaitee_client_pct >= 0 && v.fiable("projet.uc_souhaitee")) {
      const uc = p.uc_souhaitee_client_pct;
      if (uc > plafond) {
        let detail = `Le client souhaite ${uc.toFixed(0)} % d'unités de compte ; le plafond retenu pour un profil ${LIBELLES_PROFIL[profil]} est de ${plafond.toFixed(0)} %.`;
        if (miseEnGarde) detail += " Une mise en garde orale a été donnée pendant l'appel.";
        regles.push(regle("ADQ-03", "Allocation souhaitée par le client", "vigilance", detail,
          "Formaliser la mise en garde par écrit dans la déclaration d'adéquation, ou ajuster l'allocation.", REF_DDA,
          ["projet.uc_souhaitee"].concat(miseEnGarde ? ["projet.mise_en_garde"] : [])));
      } else {
        regles.push(regle("ADQ-03", "Allocation souhaitée par le client", "ok",
          `${uc.toFixed(0)} % d'unités de compte, cohérent avec un profil ${LIBELLES_PROFIL[profil]} (plafond ${plafond.toFixed(0)} %).`,
          "", REF_DDA, ["projet.uc_souhaitee"]));
      }
    }
    if (plafond !== undefined && p.uc_recommandee_conseiller_pct >= 0 && v.fiable("projet.uc_recommandee")) {
      const uc = p.uc_recommandee_conseiller_pct;
      if (uc > plafond) {
        regles.push(regle("ADQ-04", "Recommandation du conseiller", "vigilance",
          `Recommandation à ${uc.toFixed(0)} % d'UC, au-delà du plafond de ${plafond.toFixed(0)} % pour ce profil.`,
          "Revoir la recommandation avant tout envoi au client.", REF_DDA, ["projet.uc_recommandee"]));
      } else {
        regles.push(regle("ADQ-04", "Recommandation du conseiller", "ok", `Recommandation à ${uc.toFixed(0)} % d'UC, dans le plafond du profil.`,
          "", REF_DDA, ["projet.uc_recommandee"]));
      }
    }
    if (p.horizon_annees > 0 && p.horizon_annees < pol.horizon_court_annees) {
      const uc = Math.max(p.uc_souhaitee_client_pct, p.uc_recommandee_conseiller_pct);
      if (uc > pol.uc_max_horizon_court) {
        regles.push(regle("ADQ-05", "Horizon court", "vigilance", `Horizon de ${p.horizon_annees.toFixed(0)} ans avec ${uc.toFixed(0)} % d'UC envisagés.`,
          "Réduire la part d'UC ou documenter l'adéquation.", REF_DDA));
      }
    }
    return regles;
  }

  function evaluerLcb(a, v, pol) {
    const l = a.lcb, p = a.projet;
    const montant = v.fiable("projet.montant") ? p.montant_initial_eur : 0;
    let origine = l.origine_fonds;
    if (origine !== "non_abordee" && !v.fiable("lcb.origine")) origine = "non_abordee";
    const libelleOrigine = LIBELLES_ORIGINE[origine] || origine;
    const pieceOrigine = PIECE_PAR_ORIGINE[origine] || "";
    const origineConnue = pieceOrigine && origine !== "floue" && origine !== "non_abordee";
    const regles = [];
    const ref = `Politique interne v${pol.version}`;

    if (origine === "floue") {
      regles.push(regle("LCB-01", "Origine des fonds", montant >= pol.seuil_justificatif_eur ? "escalade" : "vigilance",
        `Origine non précisée par le client (${l.origine_detail}).`, "Obtenir une origine précise et justifiée avant toute souscription.",
        REF_CONNAISSANCE, ["lcb.origine"]));
    } else if (origine === "non_abordee") {
      regles.push(regle("LCB-01", "Origine des fonds", "action", "Origine des fonds non abordée pendant l'appel.",
        "La recueillir et la justifier avant la souscription.", REF_CONNAISSANCE));
    } else {
      regles.push(regle("LCB-01", "Origine des fonds", "ok", `Origine déclarée : ${libelleOrigine} (${l.origine_detail}).`, "", REF_CONNAISSANCE, ["lcb.origine"]));
    }

    const pieces = PIECES_SOCLE.slice();
    const obligatoires = [];
    if (montant >= pol.seuil_justificatif_eur) {
      let detail;
      if (origineConnue) {
        obligatoires.push(pieceOrigine);
        detail = `Versement de ${eur(montant)} ≥ ${eur(pol.seuil_justificatif_eur)} : justificatif obligatoire (${pieceOrigine.toLowerCase()}).`;
      } else {
        detail = `Versement de ${eur(montant)} ≥ ${eur(pol.seuil_justificatif_eur)} : justificatif obligatoire, origine à préciser.`;
      }
      regles.push(regle("LCB-02", "Justificatif d'origine des fonds", "action", detail, "Exiger le justificatif avant d'encaisser.", ref, ["projet.montant"]));
    } else if (montant > 0) {
      let detail = `Versement de ${eur(montant)}, sous le seuil de ${eur(pol.seuil_justificatif_eur)}.`;
      if (origineConnue) detail += ` Pièce recommandée : ${pieceOrigine.toLowerCase()}.`;
      regles.push(regle("LCB-02", "Justificatif d'origine des fonds", "ok", detail, "", ref, ["projet.montant"]));
    } else {
      regles.push(regle("LCB-02", "Justificatif d'origine des fonds", "action", "Montant non communiqué.", "Préciser le montant envisagé.", ref));
    }
    if (origineConnue) pieces.push(pieceOrigine);

    const revenus = v.fiable("lcb.revenus") ? l.revenus_annuels_eur : 0;
    if (montant > 0 && revenus > 0 && montant > pol.ratio_revenus_vigilance * revenus) {
      const ratio = montant / revenus;
      if (EVENEMENTS_PATRIMONIAUX.has(origine)) {
        regles.push(regle("LCB-03", "Cohérence montant / revenus", "ok",
          `Montant égal à ${fois(ratio)} les revenus annuels, expliqué par une ${libelleOrigine}.`, "", REF_CONNAISSANCE,
          ["projet.montant", "lcb.revenus", "lcb.origine"]));
      } else {
        regles.push(regle("LCB-03", "Cohérence montant / revenus", "vigilance",
          `Montant égal à ${fois(ratio)} les revenus annuels, sans événement patrimonial identifié.`,
          "Documenter la constitution de ce patrimoine.", REF_CONNAISSANCE, ["projet.montant", "lcb.revenus"]));
      }
    } else if (montant > 0 && revenus === 0) {
      regles.push(regle("LCB-03", "Cohérence montant / revenus", "action", "Revenus non recueillis : cohérence non vérifiable.",
        "Recueillir les revenus annuels.", REF_CONNAISSANCE));
    } else if (montant > 0) {
      regles.push(regle("LCB-03", "Cohérence montant / revenus", "ok", "Montant cohérent avec les revenus déclarés.", "", REF_CONNAISSANCE,
        ["projet.montant", "lcb.revenus"]));
    }

    if (l.tiers_payeur === "oui") {
      regles.push(regle("LCB-04", "Tiers payeur", "escalade",
        "Une partie des fonds viendrait d'un compte qui n'est pas au nom du client" + (v.fiable("lcb.tiers_payeur") ? "" : " (citation à vérifier)") + ".",
        "Aucun versement d'un tiers ; transmettre au responsable LCB-FT.", REF_CONNAISSANCE, ["lcb.tiers_payeur"]));
    } else {
      regles.push(regle("LCB-04", "Tiers payeur", "ok", "Aucun tiers payeur évoqué. Le RIB au nom du souscripteur sera exigé.", "", REF_CONNAISSANCE));
    }
    if (l.especes === "oui") {
      regles.push(regle("LCB-05", "Espèces", "escalade",
        "Versement en espèces évoqué par le client" + (v.fiable("lcb.especes") ? "" : " (citation à vérifier)") + ".",
        "Aucun versement en espèces ; transmettre au responsable LCB-FT.", REF_CONNAISSANCE, ["lcb.especes"]));
    } else {
      regles.push(regle("LCB-05", "Espèces", "ok", "Aucun versement en espèces évoqué.", "", REF_CONNAISSANCE));
    }
    if (l.ppe === "oui") {
      regles.push(regle("LCB-06", "Personne politiquement exposée", "vigilance", "Le client ou un proche exerce une fonction politique ou publique importante.",
        "Vigilance complémentaire : décision d'entrée en relation par un dirigeant habilité, origine du patrimoine et des fonds.", REF_PPE, ["lcb.ppe"]));
    } else if (l.ppe === "non") {
      regles.push(regle("LCB-06", "Personne politiquement exposée", "ok", "Le client a indiqué ne pas être concerné.", "", REF_PPE, ["lcb.ppe"]));
    } else {
      regles.push(regle("LCB-06", "Personne politiquement exposée", "action", "Statut PPE non abordé pendant l'appel.",
        "Le recueillir dans le questionnaire de souscription.", REF_PPE));
    }
    if (l.signaux.length) {
      const n = l.signaux.length;
      regles.push(regle("LCB-07", "Signaux comportementaux", "vigilance",
        `${n} ${n === 1 ? "signal" : "signaux"} : ` + l.signaux.map((s) => s.detail).join(" ; ") + ".",
        "Les porter à la connaissance du responsable LCB-FT.", REF_CONNAISSANCE, l.signaux.map((_, i) => `lcb.signaux[${i}]`)));
    } else {
      regles.push(regle("LCB-07", "Signaux comportementaux", "ok", "Aucun signal relevé.", "", REF_CONNAISSANCE));
    }

    const statuts = regles.map((r) => r.statut);
    const nbVig = statuts.filter((s) => s === "vigilance").length;
    const niveau = statuts.includes("escalade") || nbVig >= pol.nb_vigilances_escalade ? "escalade" : nbVig ? "renforcee" : "standard";
    return { regles, niveau, pieces, obligatoires };
  }

  function evaluer(a, v, pol = POLITIQUE) {
    const recueil = evaluerRecueil(a, v);
    const adequation = evaluerAdequation(a, v, recueil, pol);
    const lcb = evaluerLcb(a, v, pol);
    const requis = recueil.filter((l) => l.requis);
    return {
      politique: pol.version, recueil,
      questions: recueil.filter((l) => l.question && (l.requis || l.statut === "manquant")).map((l) => l.question),
      adequation, lcb: lcb.regles, niveau_lcb: lcb.niveau, pieces: lcb.pieces, pieces_obligatoires: lcb.obligatoires,
      recueil_complet: requis.every((l) => l.statut === "couvert"),
      nb_requis: requis.length, nb_requis_couverts: requis.filter((l) => l.statut === "couvert").length,
    };
  }

  /* ---------- Relecture des relances (email_lint.py) ---------- */
  const INTERDITS = [
    [/sans\s+risques?/gi, "« sans risque »"],
    [/risque\s+z[ée]ro|z[ée]ro\s+risque/gi, "« risque zéro »"],
    [/(rendement|performance|gain|plus-value)s?\s+(?:\S+\s+){0,2}garanti/gi, "rendement présenté comme garanti"],
    [/vous\s+allez\s+gagner/gi, "« vous allez gagner »"],
    [/meilleur\s+placement/gi, "« meilleur placement »"],
    [/placement\s+(?:100\s*%\s*|totalement\s+|parfaitement\s+)?sûr/gi, "« placement sûr »"],
  ];
  const NEGATION = /\b(non|pas|ni|jamais)\b/i;
  const PERFORMANCE_CHIFFREE = /\d+(?:[.,]\d+)?\s?%[^.\n]{0,40}\b(net|brut|rendement|performance|servi)|\b(rendement|performance|servi|rapport[ée])[^.\n]{0,40}\d+(?:[.,]\d+)?\s?%/i;
  const MENTION_PERFORMANCES = /performances?\s+pass[ée]es?\s+ne\s+pr[ée]jugen?t?\s+pas/i;
  const SUPPORTS_UC = /unit[ée]s?\s+de\s+compte|\bUC\b|\bETF\b|\bSCPI\b|\bSCI\b|\bOPCVM\b|fonds\s+indiciels?|en\s+actions|march[ée]s?\s+actions/i;
  const MENTION_PERTE = /risque\s+de\s+perte\s+en\s+capital/i;
  const DIVULGATION = /tracfin|soup[çc]on|blanchiment|lcb[\s-]?ft|(analyse|revue|contr[ôo]le)\s+(de\s+)?conformit/i;

  function verifierRelance(texte) {
    const c = [];
    const trouves = [];
    for (const [motif, libelle] of INTERDITS) {
      for (const m of texte.matchAll(motif)) if (!NEGATION.test(m[0])) trouves.push(libelle);
    }
    const uniques = [...new Set(trouves)].sort();
    c.push({ id: "MKT-01", titre: "Aucune promesse de rendement ni d'absence de risque", statut: uniques.length ? "ko" : "ok",
      message: uniques.length ? "Formulation interdite : " + uniques.join(", ") + "." : "Aucune formulation interdite." });
    if (PERFORMANCE_CHIFFREE.test(texte)) {
      const ok = MENTION_PERFORMANCES.test(texte);
      c.push({ id: "MKT-02", titre: "Performance chiffrée accompagnée de l'avertissement", statut: ok ? "ok" : "ko",
        message: ok ? "Mention « les performances passées ne préjugent pas des performances futures » présente."
                    : "Une performance est citée sans la mention « les performances passées ne préjugent pas des performances futures »." });
    } else {
      c.push({ id: "MKT-02", titre: "Performance chiffrée accompagnée de l'avertissement", statut: "na", message: "Aucune performance chiffrée." });
    }
    if (SUPPORTS_UC.test(texte)) {
      const ok = MENTION_PERTE.test(texte);
      c.push({ id: "MKT-03", titre: "Unités de compte : risque de perte en capital mentionné", statut: ok ? "ok" : "ko",
        message: ok ? "Mention du risque de perte en capital présente."
                    : "Des unités de compte sont évoquées sans mentionner le risque de perte en capital." });
    } else {
      c.push({ id: "MKT-03", titre: "Unités de compte : risque de perte en capital mentionné", statut: "na", message: "Aucun support en unités de compte évoqué." });
    }
    const div = DIVULGATION.exec(texte);
    c.push({ id: "MKT-04", titre: "Aucune mention d'une analyse interne (confidentialité LCB-FT)", statut: div ? "ko" : "ok",
      message: div ? `Le texte évoque une analyse interne (« ${div[0]} »).` : "Aucune mention d'analyse interne." });
    return c;
  }

  /* ---------- Plan HubSpot (hubspot.py) ---------- */
  const CHEMIN_CRM = "/crm/v3/objects";
  const DEAL_ID = "$DEAL_ID";
  const ASSOCIATIONS = { deal_vers_contact: 3, note_vers_contact: 202, note_vers_deal: 214, tache_vers_contact: 204, tache_vers_deal: 216 };
  const ETAPES_TRANSACTION = {
    appointmentscheduled: "RDV planifié", qualifiedtobuy: "Qualifié", presentationscheduled: "Proposition présentée",
    decisionmakerboughtin: "Décision en cours", contractsent: "Dossier envoyé", closedwon: "Souscrit", closedlost: "Perdu",
  };
  const LIBELLES_CYCLE = { subscriber: "Abonné", lead: "Lead", marketingqualifiedlead: "Lead qualifié marketing",
    salesqualifiedlead: "Lead qualifié ventes", opportunity: "Opportunité", customer: "Client" };
  const LIBELLES_STATUT_LEAD = { NEW: "Nouveau", OPEN: "Ouvert", IN_PROGRESS: "En cours", OPEN_DEAL: "Transaction ouverte",
    CONNECTED: "Connecté", ATTEMPTED_TO_CONTACT: "Tentative de contact", UNQUALIFIED: "Non qualifié", BAD_TIMING: "Mauvais moment" };
  const ORDRE_CYCLE = ["subscriber", "lead", "marketingqualifiedlead", "salesqualifiedlead", "opportunity", "customer", "evangelist"];
  const TYPES_TACHE = { appel: "CALL", email: "EMAIL", document: "TODO", rdv: "TODO", autre: "TODO" };

  function jourOuvreSuivant(iso) {
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
    const d = m ? new Date(Date.UTC(+m[1], +m[2] - 1, +m[3])) : new Date();
    do { d.setUTCDate(d.getUTCDate() + 1); } while (d.getUTCDay() === 0 || d.getUTCDay() === 6);
    return d.toISOString().slice(0, 10);
  }
  const local = (echeance, dateAppel) => !echeance ? `${jourOuvreSuivant(dateAppel)}T09:00` : (echeance.includes("T") ? echeance : `${echeance}T09:00`);

  function decalageParis(ms) {
    const f = new Intl.DateTimeFormat("en-GB", { timeZone: "Europe/Paris", hourCycle: "h23", year: "numeric", month: "2-digit",
      day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" });
    const p = {};
    for (const x of f.formatToParts(new Date(ms))) p[x.type] = x.value;
    return Date.UTC(+p.year, +p.month - 1, +p.day, +p.hour, +p.minute, +p.second) - ms;
  }
  function versUtc(loc) {
    const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(loc);
    if (!m) return loc;
    const naif = Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]);
    let utc = naif - decalageParis(naif);
    utc = naif - decalageParis(utc);
    return new Date(utc).toISOString().replace(/\.\d{3}Z$/, "Z");
  }
  const assoc = (cible, type) => ({ to: { id: cible }, types: [{ associationCategory: "HUBSPOT_DEFINED", associationTypeId: type }] });
  const html = (t) => String(t).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

  function construirePlan(appel, a, v, conf, crmAvant, pol = POLITIQUE) {
    crmAvant = crmAvant || {};
    const escalade = conf.niveau_lcb === "escalade";
    const contactId = appel.contact_id || "CONTACT_ID";

    const diff = [];
    const vues = new Set();
    a.crm.champs.forEach((champ, i) => {
      const chemin = `crm.champs[${i}]`;
      const avant = String(crmAvant[champ.propriete] || "");
      const ligne = { propriete: champ.propriete, libelle: LIBELLES_CRM[champ.propriete] || champ.propriete, avant,
        apres: champ.valeur.trim(), statut: "ecrire", raison: "", source_chemin: chemin };
      const st = v.get(chemin).statut;
      if (vues.has(champ.propriete)) { ligne.statut = "bloque"; ligne.raison = "Propriété proposée deux fois : seule la première est retenue."; }
      else if (st === "introuvable" || st === "vide") {
        ligne.statut = "bloque";
        ligne.raison = st === "introuvable" ? "Citation introuvable dans l'appel : valeur non écrite." : "Aucune citation fournie : valeur non écrite.";
      } else if (escalade && pol.proprietes_retenues_si_escalade.includes(champ.propriete)) {
        ligne.statut = "retenu"; ligne.raison = "Dossier en revue LCB-FT : transmis à la conformité uniquement.";
      } else if (ligne.apres === avant.trim()) { ligne.statut = "inchange"; }
      else if (avant) { ligne.raison = "Remplace la valeur existante."; }
      vues.add(champ.propriete);
      diff.push(ligne);
    });

    const intention = a.compte_rendu.intention;
    const etape = a.crm.etape_transaction;
    const ouvre = !escalade && etape !== "aucune" && etape !== "closedlost" && (intention === "forte" || intention === "moyenne");
    const cycle = [];
    const cycleAvant = crmAvant.lifecyclestage || "";
    const statutAvant = crmAvant.hs_lead_status || "";
    if (ouvre) {
      if (ORDRE_CYCLE.indexOf(cycleAvant) < ORDRE_CYCLE.indexOf("opportunity")) {
        cycle.push({ propriete: "lifecyclestage", libelle: "Cycle de vie", avant: cycleAvant, apres: "opportunity", statut: "ecrire", raison: "Une transaction est ouverte.", source_chemin: "" });
      }
      if (statutAvant !== "OPEN_DEAL") cycle.push({ propriete: "hs_lead_status", libelle: "Statut du lead", avant: statutAvant, apres: "OPEN_DEAL", statut: "ecrire", raison: "", source_chemin: "" });
    } else if (!escalade && ["", "NEW", "OPEN", "ATTEMPTED_TO_CONTACT"].includes(statutAvant)) {
      cycle.push({ propriete: "hs_lead_status", libelle: "Statut du lead", avant: statutAvant, apres: "CONNECTED", statut: "ecrire", raison: "", source_chemin: "" });
    }

    let transaction = null;
    if (ouvre) {
      transaction = { dealname: `${PRODUIT} — ${appel.client}`, pipeline: "default", dealstage: etape };
      if (a.projet.montant_initial_eur > 0 && v.fiable("projet.montant")) transaction.amount = a.projet.montant_initial_eur.toFixed(0);
      if (a.crm.date_cloture_souhaitee && v.fiable("crm.date_cloture")) transaction.closedate = `${a.crm.date_cloture_souhaitee}T12:00:00Z`;
    }

    const taches = [];
    if (escalade) {
      taches.push({ sujet: `Revue LCB-FT avant toute suite — ${appel.client}`,
        corps: "Dossier signalé par Débrief. Le détail des règles déclenchées est transmis au canal conformité. Aucune relance client avant décision.",
        echeance: `${appel.date_iso}T${appel.heure || "09:00"}`, priorite: "HIGH", type: "TODO", origine: "lcb", assignee: "conformite", source_chemin: "", nature: "" });
    } else {
      a.compte_rendu.prochaines_etapes.forEach((e, i) => {
        const chemin = `compte_rendu.prochaines_etapes[${i}]`;
        if (e.porteur !== "conseiller" || !v.fiable(chemin)) return;
        taches.push({ sujet: e.action, corps: `Convenu pendant l'appel du ${appel.date_longue} (l. ${v.get(chemin).ligne}).`,
          echeance: local(e.echeance, appel.date_iso), priorite: e.type === "appel" || e.type === "rdv" ? "HIGH" : "MEDIUM",
          type: TYPES_TACHE[e.type] || "TODO", origine: "appel", assignee: "conseiller", source_chemin: chemin, nature: e.type });
      });
      const prochain = (taches.find((t) => t.nature === "appel" || t.nature === "rdv") || {}).echeance;
      const defaut = prochain || local("", appel.date_iso);
      if (conf.questions.length) {
        const n = conf.questions.length;
        taches.push({ sujet: `Compléter le recueil DDA (${n} question${n > 1 ? "s" : ""})`,
          corps: "À poser lors du prochain échange :\n" + conf.questions.map((q) => `• ${q}`).join("\n"),
          echeance: defaut, priorite: "MEDIUM", type: "TODO", origine: "recueil", assignee: "conseiller", source_chemin: "", nature: "" });
      }
      conf.adequation.filter((r) => r.statut === "vigilance").forEach((r) => {
        taches.push({ sujet: `${r.id} · ${r.titre}`, corps: `${r.detail}\n${r.action}`, echeance: defaut, priorite: "HIGH", type: "TODO",
          origine: "adequation", assignee: "conseiller", source_chemin: "", nature: "" });
      });
      conf.pieces_obligatoires.forEach((piece) => {
        taches.push({ sujet: `Collecter : ${piece.toLowerCase()}`, corps: "Justificatif obligatoire avant tout encaissement (règle LCB-02).",
          echeance: defaut, priorite: "HIGH", type: "TODO", origine: "lcb", assignee: "conseiller", source_chemin: "", nature: "" });
      });
    }

    const entete = `<p><strong>Appel du ${appel.date_longue}</strong> · ${html(appel.conseiller)} · préparé par Débrief, validé par le conseiller</p>`;
    let note;
    if (escalade) {
      note = entete + "<p>Échange de découverte. Dossier transmis pour revue interne avant toute suite : ne pas relancer le client sans l'accord de la conformité.</p>";
    } else {
      const points = a.compte_rendu.points_cles.filter((_, i) => v.fiable(`compte_rendu.points_cles[${i}]`)).map((p) => p.texte);
      const etapes = a.compte_rendu.prochaines_etapes.filter((_, i) => v.fiable(`compte_rendu.prochaines_etapes[${i}]`))
        .map((e) => e.action + (e.echeance ? ` (${e.echeance.replace("T", " à ")})` : ""));
      note = entete + `<p>${html(a.compte_rendu.resume)}</p><p><strong>Points clés</strong></p><ul>` + points.map((p) => `<li>${html(p)}</li>`).join("")
        + "</ul><p><strong>Prochaines étapes</strong></p><ul>" + etapes.map((e) => `<li>${html(e)}</li>`).join("") + "</ul>";
    }

    const operations = [];
    const proprietes = {};
    diff.filter((l) => l.statut === "ecrire").forEach((l) => { proprietes[l.propriete] = l.apres; });
    cycle.forEach((l) => { proprietes[l.propriete] = l.apres; });
    const n = Object.keys(proprietes).length;
    if (n) operations.push({ methode: "PATCH", chemin: `${CHEMIN_CRM}/contacts/${contactId}`, corps: { properties: proprietes }, description: `Mettre à jour ${n} propriétés du contact` });
    if (transaction) operations.push({ methode: "POST", chemin: `${CHEMIN_CRM}/deals`, corps: { properties: transaction, associations: [assoc(contactId, ASSOCIATIONS.deal_vers_contact)] }, description: "Créer la transaction" });
    const assocNote = [assoc(contactId, ASSOCIATIONS.note_vers_contact)].concat(transaction ? [assoc(DEAL_ID, ASSOCIATIONS.note_vers_deal)] : []);
    operations.push({ methode: "POST", chemin: `${CHEMIN_CRM}/notes`, corps: { properties: { hs_timestamp: versUtc(`${appel.date_iso}T${appel.heure || "09:00"}`), hs_note_body: note }, associations: assocNote }, description: "Ajouter le compte rendu en note" });
    taches.forEach((t) => {
      const props = { hs_timestamp: versUtc(t.echeance), hs_task_subject: t.sujet, hs_task_body: t.corps, hs_task_status: "NOT_STARTED", hs_task_priority: t.priorite, hs_task_type: t.type };
      const as = [assoc(contactId, ASSOCIATIONS.tache_vers_contact)].concat(transaction ? [assoc(DEAL_ID, ASSOCIATIONS.tache_vers_deal)] : []);
      operations.push({ methode: "POST", chemin: `${CHEMIN_CRM}/tasks`, corps: { properties: props, associations: as }, description: `Créer la tâche « ${t.sujet} »` });
    });
    return { contact_id: contactId, diff, cycle, transaction, taches, note_html: note, operations };
  }

  /* ---------- Pipeline (pipeline.py) ---------- */
  function faitsVerifies(appel, a, v, conf) {
    const p = a.projet;
    const projet = {};
    if (p.montant_initial_eur > 0 && v.fiable("projet.montant")) projet.versement_initial_eur = p.montant_initial_eur;
    if (p.versement_mensuel_eur > 0 && v.fiable("projet.versement")) projet.versement_mensuel_eur = p.versement_mensuel_eur;
    if (p.uc_souhaitee_client_pct >= 0 && v.fiable("projet.uc_souhaitee")) projet.part_uc_souhaitee_par_le_client_pct = p.uc_souhaitee_client_pct;
    if (p.uc_recommandee_conseiller_pct >= 0 && v.fiable("projet.uc_recommandee")) projet.part_uc_recommandee_par_le_conseiller_pct = p.uc_recommandee_conseiller_pct;
    const recueil = {};
    conf.recueil.filter((l) => l.statut === "couvert" || l.statut === "partiel").forEach((l) => { recueil[l.cle] = l.valeur; });
    const cr = a.compte_rendu;
    return {
      client: appel.client, conseiller: appel.conseiller, date_appel: appel.date_longue, projet, situation_et_preferences: recueil,
      points_cles: cr.points_cles.filter((_, i) => v.fiable(`compte_rendu.points_cles[${i}]`)).map((x) => x.texte),
      questions_et_reponses: cr.questions_client.filter((_, i) => v.fiable(`compte_rendu.questions_client[${i}]`)).map((q) => ({ question: q.question, reponse: q.reponse })),
      prochaines_etapes: cr.prochaines_etapes.filter((_, i) => v.fiable(`compte_rendu.prochaines_etapes[${i}]`)).map((e) => ({ action: e.action, porteur: e.porteur, echeance: e.echeance })),
      pieces_a_fournir: conf.pieces,
    };
  }

  /* Rejoue le pipeline à partir de sorties enregistrées : une extraction et
     les versions successives de la relance. */
  function rejouer(appel, extraction, versionsRelance, crmAvant, maxCorrections = 1) {
    const analyse = conformerAnalyse(extraction);
    const verification = verifier(analyse, appel.tours);
    const conformite = evaluer(analyse, verification);
    let relance = null, statut = "suspendue", controles = [], corrections = 0;
    const brouillons = [];
    if (conformite.niveau_lcb !== "escalade" && versionsRelance && versionsRelance.length) {
      statut = "a_revoir";
      for (let t = 0; t <= maxCorrections; t++) {
        relance = versionsRelance[Math.min(t, versionsRelance.length - 1)];
        corrections = t;
        controles = verifierRelance(`${relance.objet}\n${relance.corps}`);
        brouillons.push({ relance, controles });
        if (!controles.some((c) => c.statut === "ko")) { statut = "prete"; break; }
      }
    }
    const plan = construirePlan(appel, analyse, verification, conformite, crmAvant);
    return { appel, analyse, verification, conformite, relance, statut_relance: statut, controles_relance: controles, corrections_relance: corrections, brouillons, plan };
  }

  /* ---------- Conformation d'une sortie libre (mode live) ---------- */
  const TRI = ["oui", "non", "non_aborde"];
  const ORIGINES = ["epargne", "succession", "donation", "cession_immobiliere", "cession_entreprise", "revenus_professionnels", "autre", "floue", "non_abordee"];
  const ETAPES = ["appointmentscheduled", "qualifiedtobuy", "presentationscheduled", "decisionmakerboughtin", "contractsent", "closedwon", "closedlost", "aucune"];
  const SCHEMA = {
    compte_rendu: {
      resume: "s", points_cles: [{ texte: "s", source: "s" }],
      questions_client: [{ question: "s", reponse: "s", source: "s" }], objections: [{ texte: "s", source: "s" }],
      prochaines_etapes: [{ action: "s", porteur: ["conseiller", "client"], echeance: "s", type: ["appel", "email", "document", "rdv", "autre"], source: "s" }],
      intention: ["forte", "moyenne", "faible", "indeterminee"], intention_source: "s",
    },
    recueil: Object.fromEntries(CLES_RECUEIL.map((c) => [c, { statut: ["couvert", "partiel", "manquant"], valeur: "s", source: "s" }])),
    projet: {
      montant_initial_eur: "n", montant_source: "s", versement_mensuel_eur: "n", versement_source: "s", horizon_annees: "n",
      profil_pressenti: ["prudent", "equilibre", "dynamique", "indetermine"], profil_source: "s",
      uc_souhaitee_client_pct: "n-1", uc_souhaitee_source: "s", uc_recommandee_conseiller_pct: "n-1", uc_recommandee_source: "s",
      mise_en_garde_orale: TRI, mise_en_garde_source: "s",
    },
    lcb: {
      origine_fonds: ORIGINES, origine_detail: "s", origine_source: "s", revenus_annuels_eur: "n", revenus_source: "s",
      tiers_payeur: TRI, tiers_payeur_source: "s", especes: TRI, especes_source: "s", ppe: TRI, ppe_source: "s",
      signaux: [{ type: ["urgence", "reticence", "pays_a_risque", "montage_complexe", "autre"], detail: "s", source: "s" }],
    },
    crm: {
      champs: [{ propriete: Object.keys(LIBELLES_CRM), valeur: "s", source: "s" }],
      etape_transaction: ETAPES, date_cloture_souhaitee: "s", date_cloture_source: "s",
    },
  };

  function conformer(valeur, schema) {
    if (schema === "s") return typeof valeur === "string" ? valeur : valeur == null ? "" : String(valeur);
    if (schema === "n" || schema === "n-1") {
      const x = typeof valeur === "string" ? Number(valeur.replace(/[\s  €%]/g, "").replace(",", ".")) : Number(valeur);
      return Number.isFinite(x) && valeur !== "" && valeur != null ? x : schema === "n" ? 0 : -1;
    }
    if (Array.isArray(schema) && typeof schema[0] === "string") return schema.includes(valeur) ? valeur : schema[schema.length - 1];
    if (Array.isArray(schema)) return Array.isArray(valeur) ? valeur.map((x) => conformer(x, schema[0])) : [];
    const o = valeur && typeof valeur === "object" ? valeur : {};
    const sortie = {};
    for (const [k, s] of Object.entries(schema)) sortie[k] = conformer(o[k], s);
    return sortie;
  }

  function conformerAnalyse(brut) {
    const champsValides = ((brut && brut.crm && Array.isArray(brut.crm.champs)) ? brut.crm.champs : [])
      .filter((c) => c && Object.prototype.hasOwnProperty.call(LIBELLES_CRM, c.propriete));
    const copie = Object.assign({}, brut, { crm: Object.assign({}, (brut || {}).crm, { champs: champsValides }) });
    return conformer(copie, SCHEMA);
  }

  /* ---------- Coût estimé ---------- */
  function estimerCout(modele, caracteresEntree, caracteresSortie) {
    const t = TARIFS[modele];
    const entree = Math.round(caracteresEntree / CARACTERES_PAR_TOKEN);
    const sortie = Math.round(caracteresSortie / CARACTERES_PAR_TOKEN);
    return { modele, entree, sortie, usd: t ? (entree * t.input + sortie * t.output) / 1e6 : 0 };
  }

  return {
    POLITIQUE, LIBELLES_CRM, LIBELLES_PROFIL, LIBELLES_ORIGINE, ETAPES_TRANSACTION, LIBELLES_CYCLE, LIBELLES_STATUT_LEAD,
    ITEMS_RECUEIL, CLES_RECUEIL, SCHEMA, DEAL_ID,
    parserAppel, texteParModele, normaliser, localiser, verifier, evaluer, verifierRelance, construirePlan,
    faitsVerifies, rejouer, conformerAnalyse, versUtc, estimerCout, dateLongue,
  };
});
