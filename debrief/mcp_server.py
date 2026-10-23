"""Serveur MCP : Débrief comme outil dans Claude (desktop, Claude Code) ou tout
client MCP. Le conseiller colle une transcription et obtient le débrief.

    pip install -e ".[mcp]"
    python -m debrief.mcp_server          # transport stdio

DEBRIEF_REJOUER=1 rejoue les sorties enregistrées (démo sans clé API).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

try:                                         # SDK MCP 2.x
    from mcp.server.mcpserver import MCPServer
except ImportError:                          # SDK MCP 1.x
    from mcp.server.fastmcp import FastMCP as MCPServer

from .llm import ClaudeLLM, RejeuLLM
from .pipeline import debriefer
from .transcript import parser_appel

RACINE = Path(__file__).resolve().parent.parent

serveur = MCPServer(
    name="debrief",
    instructions="Analyse un appel conseiller-client en assurance-vie : compte rendu, recueil DDA, "
                 "contrôles LCB-FT, proposition de mise à jour HubSpot et e-mail de relance.",
)


def _llm():
    return RejeuLLM(RACINE / "fixtures") if os.getenv("DEBRIEF_REJOUER") else ClaudeLLM()


def _crm_avant(contact_id: str) -> dict:
    chemin = RACINE / "samples" / "crm_avant.json"
    return json.loads(chemin.read_text(encoding="utf-8")).get(contact_id, {}) if chemin.exists() else {}


@serveur.tool()
def debriefer_appel(transcription: str) -> dict:
    """Analyse la transcription d'un appel (lignes « [mm:ss] Nom : texte », en-têtes « # Clé : valeur »
    facultatifs). Renvoie le compte rendu, les contrôles DDA et LCB-FT, le plan de mise à jour HubSpot
    (non exécuté) et le brouillon de relance."""
    appel = parser_appel(transcription)
    d = debriefer(appel, _llm(), _crm_avant(appel.contact_id))
    return {
        "compte_rendu": d.analyse.compte_rendu.model_dump(),
        "citations_retrouvees": f"{d.verification.retrouvees}/{d.verification.total}",
        "niveau_lcb": d.conformite.niveau_lcb,
        "regles": [r.__dict__ for r in d.conformite.adequation + d.conformite.lcb],
        "questions_a_poser": d.conformite.questions,
        "hubspot": [{"methode": o.methode, "chemin": o.chemin, "description": o.description} for o in d.plan.operations],
        "relance": d.relance.model_dump() if d.relance else None,
        "statut_relance": d.statut_relance,
    }


@serveur.tool()
def questions_a_poser(transcription: str) -> list[str]:
    """Liste les questions du recueil des besoins (DDA) qui n'ont pas été posées pendant l'appel."""
    appel = parser_appel(transcription)
    return debriefer(appel, _llm(), _crm_avant(appel.contact_id)).conformite.questions


def main() -> None:
    serveur.run()


if __name__ == "__main__":
    main()
