"""Évaluation sur un jeu d'appels annotés à la main (evals/attendus.json).

On mesure ce qui compte pour l'équipe, pas un score abstrait :
- exactitude des champs extraits (montants, profil, origine des fonds…) ;
- taux de citations retrouvées (ancrage) ;
- niveau LCB-FT et règles déclenchées : un dossier à escalader manqué est une
  erreur critique, comptée à part ;
- relance suspendue quand il le faut ;
- coût par appel.

    python -m debrief evals            # modèle réel (ANTHROPIC_API_KEY)
    python -m debrief evals --rejouer  # sorties enregistrées : vérifie la mécanique

Comparer deux modèles : DEBRIEF_MODELE_EXTRACTION=claude-haiku-5-5 python -m debrief evals
"""

from __future__ import annotations

import json
from pathlib import Path

from .pipeline import debriefer
from .transcript import lire_appel

RACINE = Path(__file__).resolve().parent.parent


def _usd(montant: float) -> str:
    return f"{montant:.4f}".replace(".", ",") + " $"


def _egal(attendu, obtenu) -> bool:
    if isinstance(attendu, (int, float)) and isinstance(obtenu, (int, float)):
        return abs(attendu - obtenu) < 0.5
    return attendu == obtenu


def executer(llm, dossier_samples: Path = RACINE / "samples", fichier_attendus: Path = RACINE / "evals" / "attendus.json") -> int:
    attendus = {k: v for k, v in json.loads(fichier_attendus.read_text(encoding="utf-8")).items() if not k.startswith("_")}
    crm = json.loads((dossier_samples / "crm_avant.json").read_text(encoding="utf-8"))
    total_champs = justes = citations = retrouvees = critiques = 0
    cout = 0.0
    lignes = []
    for identifiant, att in attendus.items():
        appel = lire_appel(dossier_samples / f"{identifiant}.txt")
        d = debriefer(appel, llm, crm.get(appel.contact_id, {}))
        erreurs = []

        for bloc, objet in (("projet", d.analyse.projet), ("lcb", d.analyse.lcb)):
            for champ, valeur in att.get(bloc, {}).items():
                total_champs += 1
                obtenu = getattr(objet, champ)
                if _egal(valeur, obtenu):
                    justes += 1
                else:
                    erreurs.append(f"{bloc}.{champ} : attendu {valeur}, obtenu {obtenu}")

        non_couverts = sorted(l.cle for l in d.conformite.recueil if l.requis and l.statut != "couvert")
        total_champs += 1
        if non_couverts == sorted(att["recueil_non_couverts"]):
            justes += 1
        else:
            erreurs.append(f"rubriques non couvertes : attendu {att['recueil_non_couverts']}, obtenu {non_couverts}")

        regles = {r.id: r.statut for r in d.conformite.adequation + d.conformite.lcb}
        for rid, statut in att["regles"].items():
            total_champs += 1
            if regles.get(rid) == statut:
                justes += 1
            else:
                erreurs.append(f"{rid} : attendu {statut}, obtenu {regles.get(rid)}")

        if att["niveau_lcb"] == "escalade" and d.conformite.niveau_lcb != "escalade":
            critiques += 1
            erreurs.append("CRITIQUE : escalade LCB-FT manquée")
        if att["relance_suspendue"] != (d.statut_relance == "suspendue"):
            critiques += 1
            erreurs.append("CRITIQUE : relance suspendue à tort ou envoyée à tort")

        echeances = {e.echeance for e in d.analyse.compte_rendu.prochaines_etapes}
        for ech in att["echeances"]:
            total_champs += 1
            if ech in echeances:
                justes += 1
            else:
                erreurs.append(f"échéance {ech} absente")

        citations += d.verification.total
        retrouvees += d.verification.retrouvees
        cout += d.cout_usd
        lignes.append((identifiant, d.conformite.niveau_lcb, d.verification.retrouvees, d.verification.total, d.cout_usd, erreurs))

    print("\nÉVALUATION")
    for identifiant, niveau, r, t, c, erreurs in lignes:
        print(f"  {identifiant:22} LCB {niveau:10} citations {r}/{t}   {_usd(c)}   {'✓' if not erreurs else f'{len(erreurs)} écart(s)'}")
        for e in erreurs:
            print(f"      - {e}")
    print(f"\nChamps et règles justes : {justes}/{total_champs} ({100 * justes / max(1, total_champs):.0f} %)")
    print(f"Citations retrouvées    : {retrouvees}/{citations} ({100 * retrouvees / max(1, citations):.0f} %)")
    print(f"Erreurs critiques       : {critiques}")
    print(f"Coût moyen par appel    : {_usd(cout / max(1, len(lignes)))}")
    return 1 if critiques else 0
