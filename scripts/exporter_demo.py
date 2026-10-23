"""Exporte les données de la démo web : transcriptions, sorties enregistrées du
modèle et fiches CRM « avant ». Écrit aussi les résultats Python de référence,
qui servent à vérifier que le moteur JavaScript de la démo donne exactement
les mêmes décisions que ce paquet.

    python scripts/exporter_demo.py demo/donnees.json demo/reference.json
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

from debrief.config import POLITIQUE  # noqa: E402
from debrief.llm import RejeuLLM  # noqa: E402
from debrief.pipeline import debriefer  # noqa: E402
from debrief.transcript import lire_appel  # noqa: E402

SCENARIOS = [
    {"id": "appel_01_moreau", "titre": "Héritage, 80 000 €",
     "accroche": "Une question DDA oubliée, une valeur inventée bloquée"},
    {"id": "appel_02_dubois", "titre": "Vente immobilière, 250 000 €",
     "accroche": "Allocation hors profil, justificatif obligatoire, relance corrigée"},
    {"id": "appel_03_marchand", "titre": "Origine des fonds floue",
     "accroche": "Escalade LCB-FT : aucune relance, données retenues"},
]


def construire() -> tuple[dict, dict]:
    """Renvoie (données de la démo, résultats Python de référence)."""
    crm = json.loads((RACINE / "samples" / "crm_avant.json").read_text(encoding="utf-8"))
    donnees = {"politique": asdict(POLITIQUE), "scenarios": []}
    ref = {}
    for sc in SCENARIOS:
        texte = (RACINE / "samples" / f"{sc['id']}.txt").read_text(encoding="utf-8")
        relance = RACINE / "fixtures" / f"{sc['id']}.relance.json"
        appel = lire_appel(RACINE / "samples" / f"{sc['id']}.txt")
        resultat = debriefer(appel, RejeuLLM(RACINE / "fixtures"), crm.get(appel.contact_id, {})).to_dict()
        donnees["scenarios"].append({
            **sc,
            "transcription": texte,
            "extraction": json.loads((RACINE / "fixtures" / f"{sc['id']}.extraction.json").read_text(encoding="utf-8")),
            "relances": json.loads(relance.read_text(encoding="utf-8")) if relance.exists() else [],
            "crm_avant": crm.get(appel.contact_id, {}),
            "usages": resultat["usages"],   # estimations (mode rejeu), affichées dans la démo
        })
        ref[sc["id"]] = resultat
    return donnees, ref


def main(sortie: str, reference: str | None = None) -> None:
    donnees, ref = construire()
    Path(sortie).write_text(json.dumps(donnees, ensure_ascii=False), encoding="utf-8")
    if reference:
        Path(reference).write_text(json.dumps(ref, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main(*sys.argv[1:])
