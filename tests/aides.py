"""Outils communs aux tests : chargement des appels et des sorties enregistrées."""

import json
from pathlib import Path

from debrief.llm import RejeuLLM
from debrief.pipeline import debriefer
from debrief.schemas import AnalyseAppel
from debrief.transcript import lire_appel

RACINE = Path(__file__).resolve().parent.parent
APPELS = ["appel_01_moreau", "appel_02_dubois", "appel_03_marchand"]


def appel(identifiant):
    return lire_appel(RACINE / "samples" / f"{identifiant}.txt")


def analyse_brute(identifiant) -> dict:
    return json.loads((RACINE / "fixtures" / f"{identifiant}.extraction.json").read_text(encoding="utf-8"))


def analyse(identifiant, **modifs) -> AnalyseAppel:
    """Analyse enregistrée, avec des modifications ciblées : analyse(id, **{"lcb.especes": "oui"})."""
    brut = analyse_brute(identifiant)
    for chemin, valeur in modifs.items():
        cible = brut
        *parents, feuille = chemin.split(".")
        for p in parents:
            cible = cible[p]
        cible[feuille] = valeur
    return AnalyseAppel.model_validate(brut)


def crm_avant(contact_id):
    return json.loads((RACINE / "samples" / "crm_avant.json").read_text(encoding="utf-8")).get(contact_id, {})


def debrief(identifiant):
    a = appel(identifiant)
    return debriefer(a, RejeuLLM(RACINE / "fixtures"), crm_avant(a.contact_id))
