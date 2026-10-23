"""Accès au modèle.

`ClaudeLLM` appelle l'API Claude avec des sorties structurées : le schéma
Pydantic est imposé au modèle (`messages.parse`), la réponse est validée et
renvoyée sous forme d'objet. Les prompts système sont mis en cache.

`RejeuLLM` rejoue des sorties enregistrées (dossier fixtures/) : tests, démo
et évaluations sans clé API ni coût.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol

from .config import CARACTERES_PAR_TOKEN, MODELE_EXTRACTION, MODELE_RELANCE, TARIFS_USD_PAR_MTOK
from .prompts import (
    CORRECTION_RELANCE, SYSTEME_EXTRACTION, SYSTEME_RELANCE, UTILISATEUR_EXTRACTION, UTILISATEUR_RELANCE,
)
from .schemas import AnalyseAppel, Relance
from .transcript import Appel


class ErreurLLM(RuntimeError):
    pass


@dataclass
class Usage:
    modele: str
    etape: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    estime: bool = False

    @property
    def cout_usd(self) -> float:
        t = TARIFS_USD_PAR_MTOK.get(self.modele)
        if not t:
            return 0.0
        return (self.input_tokens * t["input"] + self.output_tokens * t["output"]
                + self.cache_creation_input_tokens * t["cache_write"]
                + self.cache_read_input_tokens * t["cache_read"]) / 1_000_000

    def to_dict(self) -> dict:
        return asdict(self) | {"cout_usd": round(self.cout_usd, 5)}


Historique = list[tuple[Relance, list[str]]]


class LLM(Protocol):
    def extraire(self, appel: Appel) -> tuple[AnalyseAppel, Usage]: ...
    def rediger_relance(self, appel: Appel, faits: dict, historique: Historique) -> tuple[Relance, Usage]: ...


def message_extraction(appel: Appel) -> str:
    return UTILISATEUR_EXTRACTION.format(
        date_longue=appel.date_longue, date_iso=appel.date_iso, heure=appel.heure or "heure inconnue",
        conseiller=appel.conseiller, client=appel.client, transcription=appel.texte_pour_modele(),
    )


def messages_relance(faits: dict, historique: Historique) -> list[dict]:
    messages = [{"role": "user", "content": UTILISATEUR_RELANCE.format(faits=json.dumps(faits, ensure_ascii=False, indent=2))}]
    for brouillon, violations in historique:
        messages.append({"role": "assistant", "content": brouillon.model_dump_json()})
        messages.append({"role": "user", "content": CORRECTION_RELANCE.format(violations="\n".join(f"- {v}" for v in violations))})
    return messages


class ClaudeLLM:
    def __init__(self, client=None, modele_extraction: str = MODELE_EXTRACTION, modele_relance: str = MODELE_RELANCE,
                 max_tokens_extraction: int = 16_000, max_tokens_relance: int = 4_000):
        if client is None:
            try:
                import anthropic
            except ImportError as e:  # pragma: no cover
                raise ErreurLLM("Le SDK Anthropic est requis : pip install anthropic") from e
            client = anthropic.Anthropic()  # lit ANTHROPIC_API_KEY
        self.client = client
        self.modele_extraction = modele_extraction
        self.modele_relance = modele_relance
        self.max_tokens_extraction = max_tokens_extraction
        self.max_tokens_relance = max_tokens_relance

    def _structure(self, etape: str, modele: str, systeme: str, messages: list[dict], schema, max_tokens: int):
        if not hasattr(self.client.messages, "parse"):
            raise ErreurLLM("SDK trop ancien pour les sorties structurées : pip install -U anthropic")
        reponse = self.client.messages.parse(
            model=modele,
            max_tokens=max_tokens,
            system=[{"type": "text", "text": systeme, "cache_control": {"type": "ephemeral"}}],
            messages=messages,
            output_format=schema,
        )
        if reponse.stop_reason == "max_tokens":
            raise ErreurLLM(f"{etape} : réponse tronquée, augmentez max_tokens.")
        if reponse.stop_reason == "refusal" or reponse.parsed_output is None:
            raise ErreurLLM(f"{etape} : le modèle n'a pas produit de sortie exploitable ({reponse.stop_reason}).")
        u = reponse.usage
        usage = Usage(
            modele=modele, etape=etape, input_tokens=u.input_tokens, output_tokens=u.output_tokens,
            cache_creation_input_tokens=getattr(u, "cache_creation_input_tokens", 0) or 0,
            cache_read_input_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
        )
        return reponse.parsed_output, usage

    def extraire(self, appel: Appel) -> tuple[AnalyseAppel, Usage]:
        return self._structure("extraction", self.modele_extraction, SYSTEME_EXTRACTION,
                               [{"role": "user", "content": message_extraction(appel)}],
                               AnalyseAppel, self.max_tokens_extraction)

    def rediger_relance(self, appel: Appel, faits: dict, historique: Historique) -> tuple[Relance, Usage]:
        return self._structure("relance", self.modele_relance, SYSTEME_RELANCE, messages_relance(faits, historique),
                               Relance, self.max_tokens_relance)


def _estimer(modele: str, etape: str, entree: str, sortie: str) -> Usage:
    return Usage(modele=modele, etape=etape, input_tokens=round(len(entree) / CARACTERES_PAR_TOKEN),
                 output_tokens=round(len(sortie) / CARACTERES_PAR_TOKEN), estime=True)


class RejeuLLM:
    """Rejoue fixtures/<identifiant>.extraction.json et .relance.json (une liste
    de versions successives : la 2e sert si le linter a refusé la 1re)."""

    def __init__(self, dossier: str | Path):
        self.dossier = Path(dossier)

    def _lire(self, nom: str):
        chemin = self.dossier / nom
        if not chemin.exists():
            raise ErreurLLM(f"Aucune sortie enregistrée : {chemin}")
        return json.loads(chemin.read_text(encoding="utf-8"))

    def extraire(self, appel: Appel) -> tuple[AnalyseAppel, Usage]:
        brut = self._lire(f"{appel.identifiant}.extraction.json")
        analyse = AnalyseAppel.model_validate(brut)
        entree = SYSTEME_EXTRACTION + json.dumps(AnalyseAppel.model_json_schema()) + message_extraction(appel)
        return analyse, _estimer(MODELE_EXTRACTION, "extraction", entree, json.dumps(brut, ensure_ascii=False))

    def rediger_relance(self, appel: Appel, faits: dict, historique: Historique) -> tuple[Relance, Usage]:
        versions = self._lire(f"{appel.identifiant}.relance.json")
        version = versions[min(len(historique), len(versions) - 1)]
        relance = Relance.model_validate(version)
        entree = SYSTEME_RELANCE + json.dumps(messages_relance(faits, historique), ensure_ascii=False)
        return relance, _estimer(MODELE_RELANCE, "relance", entree, relance.model_dump_json())
