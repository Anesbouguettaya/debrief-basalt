"""Ligne de commande.

    python -m debrief analyser samples/appel_01_moreau.txt            # appel réel à l'API Claude
    python -m debrief analyser samples/appel_01_moreau.txt --rejouer  # sorties enregistrées, sans clé API
    python -m debrief synchroniser samples/appel_01_moreau.txt        # plan HubSpot, rien n'est écrit
    python -m debrief synchroniser samples/appel_01_moreau.txt --valider
    python -m debrief evals --rejouer
    python -m debrief proprietes                                       # crée les propriétés HubSpot
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import textwrap
from pathlib import Path

from .llm import ClaudeLLM, RejeuLLM
from .pipeline import Debrief, debriefer
from .transcript import lire_appel

RACINE = Path(__file__).resolve().parent.parent
SYMBOLES = {"ok": "✓", "action": "→", "vigilance": "!", "escalade": "✕", "ko": "✕", "na": "·"}
NIVEAUX = {"standard": "STANDARD", "renforcee": "VIGILANCE RENFORCÉE", "escalade": "ESCALADE — revue LCB-FT"}


def _llm(rejouer: bool):
    return RejeuLLM(RACINE / "fixtures") if rejouer else ClaudeLLM()


def _crm_avant(contact_id: str) -> dict:
    chemin = RACINE / "samples" / "crm_avant.json"
    if chemin.exists():
        return json.loads(chemin.read_text(encoding="utf-8")).get(contact_id, {})
    return {}


def _bloc(titre: str) -> None:
    print(f"\n{titre}\n{'─' * len(titre)}")


def afficher(d: Debrief) -> None:
    a, c, v = d.analyse, d.conformite, d.verification
    print(f"\nDÉBRIEF · {d.appel.client} · avec {d.appel.conseiller} · {d.appel.date_longue} · {d.appel.duree}")

    _bloc("Compte rendu")
    print(textwrap.fill(a.compte_rendu.resume, 96))
    for i, e in enumerate(a.compte_rendu.prochaines_etapes):
        print(f"  • {e.action}" + (f" — {e.echeance.replace('T', ' ')}" if e.echeance else ""))

    _bloc("Sources")
    print(f"{v.retrouvees}/{v.total} citations retrouvées dans l'appel")
    for chemin, citation in v.introuvables:
        print(f"  ✕ {chemin} : « {citation} » introuvable → non utilisé")

    _bloc(f"Devoir de conseil · {c.nb_requis_couverts}/{c.nb_requis} rubriques")
    for r in c.adequation:
        print(f"  {SYMBOLES[r.statut]} {r.id} {r.titre} : {r.detail}")
    for q in c.questions:
        print(f"    ? {q}")

    _bloc(f"LCB-FT · {NIVEAUX[c.niveau_lcb]}")
    for r in c.lcb:
        print(f"  {SYMBOLES[r.statut]} {r.id} {r.titre} : {r.detail}")

    p = d.plan
    ecrits = sum(1 for l in p.diff if l.statut == "ecrire")
    bloques = [l for l in p.diff if l.statut in ("bloque", "retenu")]
    _bloc("HubSpot (rien n'est écrit sans validation)")
    print(f"{ecrits} propriétés à écrire · {len(p.taches)} tâche(s) · 1 note"
          + (f" · transaction « {p.transaction['dealname']} »" if p.transaction else ""))
    for l in bloques:
        print(f"  ✕ {l.libelle} : {l.raison}")

    _bloc("Relance")
    if d.statut_relance == "suspendue":
        print("Suspendue : dossier en revue LCB-FT. Aucun message automatique au client.")
    else:
        print(f"Objet : {d.relance.objet}")
        for ctrl in d.controles_relance:
            print(f"  {SYMBOLES[ctrl.statut]} {ctrl.id} {ctrl.titre}")
        if d.corrections_relance:
            print(f"  ({d.corrections_relance} correction(s) automatique(s) après relecture)")

    estime = any(u.estime for u in d.usages)
    print(f"\nCoût {'estimé ' if estime else ''}: {d.cout_usd:.4f} $ · ".replace(".", ",", 1)
          + " · ".join(f"{u.etape} {u.modele} {u.input_tokens}→{u.output_tokens} tokens" for u in d.usages))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="debrief", description="Copilote post-appel pour conseillers en assurance-vie")
    sous = parser.add_subparsers(dest="commande", required=True)

    p = sous.add_parser("analyser", help="analyser une transcription")
    p.add_argument("transcription")
    p.add_argument("--rejouer", action="store_true", help="utiliser les sorties enregistrées (sans API)")
    p.add_argument("--json", help="écrire le résultat complet dans ce fichier")

    s = sous.add_parser("synchroniser", help="préparer puis, avec --valider, écrire dans HubSpot")
    s.add_argument("transcription")
    s.add_argument("--rejouer", action="store_true")
    s.add_argument("--valider", action="store_true", help="exécuter réellement les requêtes HubSpot")

    e = sous.add_parser("evals", help="mesurer la qualité sur le jeu d'évaluation")
    e.add_argument("--rejouer", action="store_true")

    sous.add_parser("proprietes", help="créer les propriétés personnalisées dans HubSpot (une fois)")

    args = parser.parse_args(argv)

    if args.commande == "proprietes":
        from .hubspot import HubSpotClient, creer_proprietes
        creees = creer_proprietes(HubSpotClient(os.environ.get("HUBSPOT_TOKEN", "")))
        print(f"{len(creees)} propriété(s) créée(s) : {', '.join(creees) or 'aucune, elles existent déjà'}")
        return 0

    if args.commande == "evals":
        from .evals import executer
        return executer(_llm(args.rejouer))

    appel = lire_appel(args.transcription)
    debrief = debriefer(appel, _llm(args.rejouer), _crm_avant(appel.contact_id))

    if args.commande == "analyser":
        afficher(debrief)
        if args.json:
            Path(args.json).write_text(json.dumps(debrief.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"\nRésultat complet : {args.json}")
        return 0

    afficher(debrief)
    print("\nRequêtes préparées :")
    for op in debrief.plan.operations:
        print(f"  {op.methode:5} {op.chemin}  — {op.description}")
    if not args.valider:
        print("\nSimulation uniquement. Relancez avec --valider après relecture pour écrire dans HubSpot.")
        return 0
    from .hubspot import HubSpotClient
    client = HubSpotClient(os.environ.get("HUBSPOT_TOKEN", ""))
    for r in client.appliquer(debrief.plan):
        print(f"  ✓ {r['operation']} (id {r['id']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
