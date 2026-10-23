"""Schéma de sortie du modèle.

Ce schéma est envoyé tel quel à l'API (sorties structurées) : le modèle ne peut
pas produire autre chose. Choix de conception :
- aucun champ optionnel ni type union : une information absente est vide
  ("", 0, -1 ou "non_aborde"), ce qui garde le schéma simple à compiler ;
- chaque fait porte une `source`, citation exacte vérifiée ensuite par du code ;
- les propriétés CRM sont une liste fermée (enum) : le modèle ne peut pas
  inventer une propriété HubSpot.
"""

from __future__ import annotations

from typing import Iterator, Literal

from pydantic import BaseModel, ConfigDict, Field

Statut = Literal["couvert", "partiel", "manquant"]
TriEtat = Literal["oui", "non", "non_aborde"]

SOURCE = "Citation EXACTE de la transcription, copiée mot pour mot (3 à 25 mots), sans horodatage ni nom. Chaîne vide si l'information est absente."


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- Compte rendu --------------------------------------------------------------
class PointCle(Strict):
    texte: str = Field(description="Fait important, en une phrase.")
    source: str = Field(description=SOURCE)


class QuestionClient(Strict):
    question: str = Field(description="Question posée par le client, reformulée.")
    reponse: str = Field(description="Réponse donnée par le conseiller pendant l'appel.")
    source: str = Field(description=SOURCE)


class Etape(Strict):
    action: str
    porteur: Literal["conseiller", "client"]
    echeance: str = Field(description="AAAA-MM-JJ ou AAAA-MM-JJTHH:MM ; chaîne vide si aucune date n'est convenue.")
    type: Literal["appel", "email", "document", "rdv", "autre"]
    source: str = Field(description=SOURCE)


class CompteRendu(Strict):
    resume: str = Field(description="3 à 5 phrases factuelles et neutres.")
    points_cles: list[PointCle]
    questions_client: list[QuestionClient]
    objections: list[PointCle]
    prochaines_etapes: list[Etape]
    intention: Literal["forte", "moyenne", "faible", "indeterminee"] = Field(
        description="Intention de souscrire exprimée par le client."
    )
    intention_source: str = Field(description=SOURCE)


# --- Recueil des exigences et besoins (DDA) ------------------------------------
class ItemRecueil(Strict):
    statut: Statut
    valeur: str = Field(description="Ce que le client a dit, résumé en quelques mots. Vide si manquant.")
    source: str = Field(description=SOURCE)


class Recueil(Strict):
    objectifs: ItemRecueil
    horizon: ItemRecueil
    situation_familiale: ItemRecueil
    situation_professionnelle: ItemRecueil
    revenus: ItemRecueil
    patrimoine: ItemRecueil
    connaissances_experience: ItemRecueil
    tolerance_risque: ItemRecueil
    capacite_pertes: ItemRecueil
    durabilite: ItemRecueil = Field(description="Préférences en matière de durabilité (critères ESG, exclusions).")
    besoin_liquidite: ItemRecueil


# --- Projet de souscription ----------------------------------------------------
class Projet(Strict):
    montant_initial_eur: float = Field(description="Versement initial envisagé, 0 si non mentionné.")
    montant_source: str = Field(description=SOURCE)
    versement_mensuel_eur: float = Field(description="Versements programmés mensuels, 0 si non mentionné.")
    versement_source: str = Field(description=SOURCE)
    horizon_annees: float = Field(description="Horizon en années, 0 si non mentionné.")
    profil_pressenti: Literal["prudent", "equilibre", "dynamique", "indetermine"]
    profil_source: str = Field(description=SOURCE)
    uc_souhaitee_client_pct: float = Field(description="Part d'UC souhaitée par le CLIENT, -1 si non abordé.")
    uc_souhaitee_source: str = Field(description=SOURCE)
    uc_recommandee_conseiller_pct: float = Field(description="Part d'UC recommandée par le CONSEILLER, -1 si non abordé.")
    uc_recommandee_source: str = Field(description=SOURCE)
    mise_en_garde_orale: TriEtat = Field(description="Le conseiller a-t-il mis en garde sur les risques des UC ?")
    mise_en_garde_source: str = Field(description=SOURCE)


# --- Éléments LCB-FT -------------------------------------------------------------
class SignalLCB(Strict):
    type: Literal["urgence", "reticence", "pays_a_risque", "montage_complexe", "autre"]
    detail: str
    source: str = Field(description=SOURCE)


class ElementsLCB(Strict):
    origine_fonds: Literal[
        "epargne", "succession", "donation", "cession_immobiliere", "cession_entreprise",
        "revenus_professionnels", "autre", "floue", "non_abordee",
    ] = Field(description="« floue » si le client reste vague ou refuse de préciser.")
    origine_detail: str
    origine_source: str = Field(description=SOURCE)
    revenus_annuels_eur: float = Field(description="Revenus annuels du client ou du foyer, 0 si non mentionnés.")
    revenus_source: str = Field(description=SOURCE)
    tiers_payeur: TriEtat = Field(description="Des fonds viendraient-ils d'un compte qui n'est pas au nom du client ?")
    tiers_payeur_source: str = Field(description=SOURCE)
    especes: TriEtat = Field(description="Le client a-t-il évoqué un versement en espèces ?")
    especes_source: str = Field(description=SOURCE)
    ppe: TriEtat = Field(description="Le client ou un proche exerce-t-il une fonction politique ou publique importante ?")
    ppe_source: str = Field(description=SOURCE)
    signaux: list[SignalLCB] = Field(description="Signaux comportementaux : urgence inhabituelle, réticence à répondre…")


# --- Proposition de mise à jour CRM ------------------------------------------------
ProprieteCRM = Literal[
    "jobtitle", "situation_familiale", "revenus_annuels", "patrimoine_financier",
    "patrimoine_immobilier", "objectif_principal", "horizon_placement",
    "profil_risque_pressenti", "experience_financiere", "preference_durabilite",
    "origine_des_fonds", "montant_envisage", "versement_programme",
    "contrats_existants", "clause_beneficiaire", "date_prochain_contact",
]

LIBELLES_CRM: dict[str, str] = {
    "jobtitle": "Profession",
    "situation_familiale": "Situation familiale",
    "revenus_annuels": "Revenus annuels",
    "patrimoine_financier": "Patrimoine financier",
    "patrimoine_immobilier": "Patrimoine immobilier",
    "objectif_principal": "Objectif principal",
    "horizon_placement": "Horizon de placement",
    "profil_risque_pressenti": "Profil de risque (pressenti)",
    "experience_financiere": "Expérience financière",
    "preference_durabilite": "Préférences de durabilité",
    "origine_des_fonds": "Origine des fonds",
    "montant_envisage": "Montant envisagé (€)",
    "versement_programme": "Versements programmés",
    "contrats_existants": "Contrats existants",
    "clause_beneficiaire": "Clause bénéficiaire envisagée",
    "date_prochain_contact": "Prochain contact",
}


class ChampCRM(Strict):
    propriete: ProprieteCRM
    valeur: str = Field(description="Valeur courte, prête à afficher. Pour montant_envisage : un nombre sans unité.")
    source: str = Field(description=SOURCE)


class PropositionCRM(Strict):
    champs: list[ChampCRM]
    etape_transaction: Literal[
        "appointmentscheduled", "qualifiedtobuy", "presentationscheduled",
        "decisionmakerboughtin", "contractsent", "closedwon", "closedlost", "aucune",
    ] = Field(description="Étape de la transaction après l'appel (pipeline HubSpot par défaut).")
    date_cloture_souhaitee: str = Field(description="AAAA-MM-JJ si le client a donné une échéance, sinon vide.")
    date_cloture_source: str = Field(description=SOURCE)


class AnalyseAppel(Strict):
    compte_rendu: CompteRendu
    recueil: Recueil
    projet: Projet
    lcb: ElementsLCB
    crm: PropositionCRM


class Relance(Strict):
    objet: str
    corps: str = Field(description="Texte brut, paragraphes séparés par une ligne vide, puces « • ».")


# --- Parcours des sources ----------------------------------------------------------
def iter_sources(a: AnalyseAppel) -> Iterator[tuple[str, str]]:
    """Toutes les citations de l'analyse, avec un chemin stable (utilisé aussi
    par la démo web, qui reprend exactement les mêmes chemins)."""
    cr = a.compte_rendu
    for i, p in enumerate(cr.points_cles):
        yield f"compte_rendu.points_cles[{i}]", p.source
    for i, q in enumerate(cr.questions_client):
        yield f"compte_rendu.questions_client[{i}]", q.source
    for i, o in enumerate(cr.objections):
        yield f"compte_rendu.objections[{i}]", o.source
    for i, e in enumerate(cr.prochaines_etapes):
        yield f"compte_rendu.prochaines_etapes[{i}]", e.source
    yield "compte_rendu.intention", cr.intention_source
    for cle in Recueil.model_fields:
        yield f"recueil.{cle}", getattr(a.recueil, cle).source
    p = a.projet
    yield "projet.montant", p.montant_source
    yield "projet.versement", p.versement_source
    yield "projet.profil", p.profil_source
    yield "projet.uc_souhaitee", p.uc_souhaitee_source
    yield "projet.uc_recommandee", p.uc_recommandee_source
    yield "projet.mise_en_garde", p.mise_en_garde_source
    lcb = a.lcb
    yield "lcb.origine", lcb.origine_source
    yield "lcb.revenus", lcb.revenus_source
    yield "lcb.tiers_payeur", lcb.tiers_payeur_source
    yield "lcb.especes", lcb.especes_source
    yield "lcb.ppe", lcb.ppe_source
    for i, s in enumerate(lcb.signaux):
        yield f"lcb.signaux[{i}]", s.source
    for i, c in enumerate(a.crm.champs):
        yield f"crm.champs[{i}]", c.source
    yield "crm.date_cloture", a.crm.date_cloture_source
