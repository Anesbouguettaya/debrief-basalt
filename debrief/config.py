"""Configuration : modèles, tarifs et politique de conformité.

Tout ce qui relève d'une décision métier (seuils LCB-FT, plafonds d'unités de
compte par profil…) vit ici, versionné, et non dans un prompt.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

# --- Modèles -----------------------------------------------------------------
# Extraction : le meilleur rapport qualité / vitesse. Relance : texte court,
# modèle rapide et ~20x moins cher. Les deux sont surchargeables par variable
# d'environnement pour comparer les modèles avec `python -m debrief evals`.
MODELE_EXTRACTION = os.getenv("DEBRIEF_MODELE_EXTRACTION", "claude-sonnet-5-5")
MODELE_RELANCE = os.getenv("DEBRIEF_MODELE_RELANCE", "claude-haiku-5-5")

# Tarifs publics en USD par million de tokens
# (platform.claude.com/docs/en/about-claude/pricing, consulté en octobre 2026).
# Haiku 5.5 : tarif des prompts de moins de 100 000 tokens, notre cas.
TARIFS_USD_PAR_MTOK: dict[str, dict[str, float]] = {
    "claude-sonnet-5-5": {"input": 2.00, "output": 10.00, "cache_write": 2.50, "cache_read": 0.10},
    "claude-haiku-5-5": {"input": 0.10, "output": 0.50, "cache_write": 0.125, "cache_read": 0.01},
    "claude-opus-5-5": {"input": 4.00, "output": 20.00, "cache_write": 5.00, "cache_read": 0.20},
}

# Estimation grossière utilisée seulement en mode rejeu (sans appel API).
CARACTERES_PAR_TOKEN = 2.5

FUSEAU = "Europe/Paris"


# --- Politique de conformité -------------------------------------------------
@dataclass(frozen=True)
class Politique:
    """Paramètres de la politique interne. Valeurs d'exemple, à valider avec la
    conformité et à aligner sur les exigences de l'assureur partenaire."""

    version: str = "0.3"

    # Montant à partir duquel un justificatif d'origine des fonds est exigé.
    # 150 000 € est une pratique de marché courante ; certains assureurs
    # demandent moins.
    seuil_justificatif_eur: float = 150_000

    # Montant supérieur à N fois les revenus annuels, sans événement
    # patrimonial qui l'explique (succession, cession…) : vigilance renforcée.
    ratio_revenus_vigilance: float = 2.0

    # Part maximale d'unités de compte (%) cohérente avec chaque profil.
    uc_max_par_profil: dict[str, float] = field(
        default_factory=lambda: {"prudent": 30.0, "equilibre": 70.0, "dynamique": 100.0}
    )

    # Horizon court : au-delà de cette part d'UC, l'allocation est signalée.
    horizon_court_annees: float = 5
    uc_max_horizon_court: float = 50

    # Nombre de règles en vigilance à partir duquel le dossier est escaladé.
    nb_vigilances_escalade: int = 3

    # Propriétés CRM qui ne sont jamais écrites quand le dossier est escaladé :
    # elles partent au canal conformité (besoin d'en connaître).
    proprietes_retenues_si_escalade: tuple[str, ...] = ("origine_des_fonds",)


POLITIQUE = Politique()

# Origines qui expliquent un montant élevé au regard des revenus.
EVENEMENTS_PATRIMONIAUX = {"succession", "donation", "cession_immobiliere", "cession_entreprise"}

PIECES_SOCLE = [
    "Pièce d'identité en cours de validité",
    "Justificatif de domicile de moins de 3 mois",
    "RIB d'un compte au nom du souscripteur",
]

PIECE_PAR_ORIGINE = {
    "succession": "Attestation du notaire (succession)",
    "donation": "Acte de donation ou déclaration de don manuel",
    "cession_immobiliere": "Acte de vente notarié",
    "cession_entreprise": "Acte de cession des titres",
    "epargne": "Relevés des comptes d'où proviennent les fonds",
    "revenus_professionnels": "Derniers avis d'imposition",
    "autre": "Justificatif adapté à l'origine déclarée",
}

LIBELLES_ORIGINE = {
    "epargne": "épargne",
    "succession": "succession",
    "donation": "donation",
    "cession_immobiliere": "cession immobilière",
    "cession_entreprise": "cession d'entreprise",
    "revenus_professionnels": "revenus professionnels",
    "autre": "autre",
    "floue": "non précisée",
    "non_abordee": "non abordée",
}
