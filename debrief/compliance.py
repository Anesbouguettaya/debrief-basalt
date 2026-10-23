"""Règles de conformité déterministes : devoir de conseil (DDA) et LCB-FT.

Le modèle relève des faits ; ces règles décident. Chaque règle a un
identifiant stable (audit), une référence et un statut :
  ok · action (à faire) · vigilance · escalade.
Les seuils viennent de `config.Politique`, jamais du prompt.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from .config import (
    EVENEMENTS_PATRIMONIAUX, LIBELLES_ORIGINE, PIECE_PAR_ORIGINE, PIECES_SOCLE, POLITIQUE, Politique,
)
from .grounding import RapportVerification
from .schemas import AnalyseAppel

REF_DDA = "Art. L522-5 C. assur. ; Règl. délégué (UE) 2017/2359"
REF_DURABILITE = "Règl. délégué (UE) 2021/1257"
REF_CONNAISSANCE = "Art. L561-6 CMF"
REF_PPE = "Art. L561-10 CMF"
REF_DECLARATION = "Art. L561-15 et L561-18 CMF"

ITEMS_RECUEIL: list[tuple[str, str, str, bool]] = [
    ("objectifs", "Objectifs du placement",
     "Quel est l'objectif principal de ce placement : transmission, retraite, projet, revenus complémentaires ?", True),
    ("horizon", "Horizon de placement",
     "À quel horizon pensez-vous avoir besoin de tout ou partie de ces sommes ?", True),
    ("situation_familiale", "Situation familiale",
     "Quelle est votre situation familiale : régime matrimonial, enfants à charge ?", True),
    ("situation_professionnelle", "Situation professionnelle",
     "Quelle est votre profession et votre statut ?", True),
    ("revenus", "Revenus",
     "Quel est le montant approximatif de vos revenus annuels ?", True),
    ("patrimoine", "Patrimoine et épargne de précaution",
     "Comment se répartit votre patrimoine, et quelle épargne de précaution conservez-vous ?", True),
    ("connaissances_experience", "Connaissances et expérience",
     "Avez-vous déjà investi en unités de compte, actions, ETF ou SCPI ? Depuis quand ?", True),
    ("tolerance_risque", "Tolérance au risque",
     "Comment réagiriez-vous si votre placement baissait temporairement de 10 à 20 % ?", True),
    ("capacite_pertes", "Capacité à subir des pertes",
     "Quelle perte pourriez-vous supporter sans que votre niveau de vie en soit affecté ?", True),
    ("durabilite", "Préférences de durabilité",
     "Souhaitez-vous qu'une partie de votre épargne soit investie selon des critères de durabilité "
     "(environnement, social, exclusions sectorielles) ?", True),
    ("besoin_liquidite", "Besoin de disponibilité",
     "Pourriez-vous avoir besoin de récupérer une partie de cette somme dans les deux prochaines années ?", False),
]

LIBELLES_PROFIL = {"prudent": "prudent", "equilibre": "équilibré", "dynamique": "dynamique", "indetermine": "indéterminé"}


@dataclass
class Regle:
    id: str
    titre: str
    statut: str                      # ok | action | vigilance | escalade
    detail: str
    action: str = ""
    reference: str = ""
    sources: list[str] = field(default_factory=list)


@dataclass
class LigneRecueil:
    cle: str
    libelle: str
    requis: bool
    statut: str                      # couvert | partiel | manquant | a_verifier
    valeur: str
    question: str


@dataclass
class Conformite:
    politique: str
    recueil: list[LigneRecueil]
    questions: list[str]
    adequation: list[Regle]
    lcb: list[Regle]
    niveau_lcb: str                  # standard | renforcee | escalade
    pieces: list[str]
    pieces_obligatoires: list[str]

    @property
    def recueil_complet(self) -> bool:
        return all(l.statut == "couvert" for l in self.recueil if l.requis)

    @property
    def nb_requis_couverts(self) -> int:
        return sum(1 for l in self.recueil if l.requis and l.statut == "couvert")

    @property
    def nb_requis(self) -> int:
        return sum(1 for l in self.recueil if l.requis)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["recueil_complet"] = self.recueil_complet
        return d


def _eur(montant: float) -> str:
    return f"{montant:,.0f} €".replace(",", " ")


def _fois(ratio: float) -> str:
    return f"{ratio:.1f}".replace(".", ",") + " fois"


# --- Devoir de conseil -------------------------------------------------------------
def evaluer_recueil(a: AnalyseAppel, verif: RapportVerification) -> list[LigneRecueil]:
    lignes = []
    for cle, libelle, question, requis in ITEMS_RECUEIL:
        item = getattr(a.recueil, cle)
        statut = item.statut
        if statut != "manquant" and not verif.est_fiable(f"recueil.{cle}"):
            statut = "a_verifier"
        lignes.append(LigneRecueil(
            cle=cle, libelle=libelle, requis=requis, statut=statut,
            valeur=item.valeur if statut != "manquant" else "",
            question="" if statut == "couvert" else question,
        ))
    return lignes


def evaluer_adequation(a: AnalyseAppel, verif: RapportVerification, recueil: list[LigneRecueil],
                       pol: Politique = POLITIQUE) -> list[Regle]:
    regles: list[Regle] = []
    p = a.projet

    manquants = [l.libelle.lower() for l in recueil if l.requis and l.statut != "couvert"]
    if not manquants:
        regles.append(Regle("ADQ-01", "Recueil des exigences et besoins", "ok",
                            "Les rubriques requises sont renseignées et sourcées.", reference=REF_DDA))
    elif len(manquants) >= 4:
        regles.append(Regle("ADQ-01", "Recueil des exigences et besoins", "vigilance",
                            f"{len(manquants)} rubriques non recueillies : aucune recommandation ne peut être formalisée.",
                            action="Compléter le recueil avant toute proposition.", reference=REF_DDA))
    else:
        regles.append(Regle("ADQ-01", "Recueil des exigences et besoins", "action",
                            "À compléter : " + ", ".join(manquants) + ".",
                            action="Poser les questions listées au prochain échange.",
                            reference=REF_DURABILITE if manquants == ["préférences de durabilité"] else REF_DDA))

    profil = p.profil_pressenti if (p.profil_pressenti == "indetermine" or verif.est_fiable("projet.profil")) else "indetermine"
    plafond = pol.uc_max_par_profil.get(profil)
    if profil == "indetermine":
        regles.append(Regle("ADQ-02", "Profil de risque", "action", "Profil de risque non établi pendant l'appel.",
                            action="Faire compléter le questionnaire de profil de risque.", reference=REF_DDA))
    else:
        regles.append(Regle("ADQ-02", "Profil de risque", "ok",
                            f"Profil pressenti : {LIBELLES_PROFIL[profil]}, à confirmer par le questionnaire.",
                            reference=REF_DDA, sources=["projet.profil"]))

    mise_en_garde = p.mise_en_garde_orale == "oui" and verif.est_fiable("projet.mise_en_garde")
    if plafond is not None and p.uc_souhaitee_client_pct >= 0 and verif.est_fiable("projet.uc_souhaitee"):
        uc = p.uc_souhaitee_client_pct
        if uc > plafond:
            detail = (f"Le client souhaite {uc:.0f} % d'unités de compte ; le plafond retenu pour un profil "
                      f"{LIBELLES_PROFIL[profil]} est de {plafond:.0f} %.")
            if mise_en_garde:
                detail += " Une mise en garde orale a été donnée pendant l'appel."
            regles.append(Regle("ADQ-03", "Allocation souhaitée par le client", "vigilance", detail,
                                action="Formaliser la mise en garde par écrit dans la déclaration d'adéquation, ou ajuster l'allocation.",
                                reference=REF_DDA,
                                sources=["projet.uc_souhaitee"] + (["projet.mise_en_garde"] if mise_en_garde else [])))
        else:
            regles.append(Regle("ADQ-03", "Allocation souhaitée par le client", "ok",
                                f"{uc:.0f} % d'unités de compte, cohérent avec un profil {LIBELLES_PROFIL[profil]} "
                                f"(plafond {plafond:.0f} %).", reference=REF_DDA, sources=["projet.uc_souhaitee"]))

    if plafond is not None and p.uc_recommandee_conseiller_pct >= 0 and verif.est_fiable("projet.uc_recommandee"):
        uc = p.uc_recommandee_conseiller_pct
        if uc > plafond:
            regles.append(Regle("ADQ-04", "Recommandation du conseiller", "vigilance",
                                f"Recommandation à {uc:.0f} % d'UC, au-delà du plafond de {plafond:.0f} % pour ce profil.",
                                action="Revoir la recommandation avant tout envoi au client.", reference=REF_DDA,
                                sources=["projet.uc_recommandee"]))
        else:
            regles.append(Regle("ADQ-04", "Recommandation du conseiller", "ok",
                                f"Recommandation à {uc:.0f} % d'UC, dans le plafond du profil.",
                                reference=REF_DDA, sources=["projet.uc_recommandee"]))

    if 0 < p.horizon_annees < pol.horizon_court_annees:
        uc = max(p.uc_souhaitee_client_pct, p.uc_recommandee_conseiller_pct)
        if uc > pol.uc_max_horizon_court:
            regles.append(Regle("ADQ-05", "Horizon court", "vigilance",
                                f"Horizon de {p.horizon_annees:.0f} ans avec {uc:.0f} % d'UC envisagés.",
                                action="Réduire la part d'UC ou documenter l'adéquation.", reference=REF_DDA))
    return regles


# --- LCB-FT ------------------------------------------------------------------------
def evaluer_lcb(a: AnalyseAppel, verif: RapportVerification, pol: Politique = POLITIQUE
                ) -> tuple[list[Regle], str, list[str], list[str]]:
    l, p = a.lcb, a.projet
    montant = p.montant_initial_eur if verif.est_fiable("projet.montant") else 0.0
    origine = l.origine_fonds
    if origine != "non_abordee" and not verif.est_fiable("lcb.origine"):
        origine = "non_abordee"
    libelle_origine = LIBELLES_ORIGINE.get(origine, origine)
    piece_origine = PIECE_PAR_ORIGINE.get(origine, "")
    regles: list[Regle] = []

    # LCB-01 — origine des fonds
    if origine == "floue":
        statut = "escalade" if montant >= pol.seuil_justificatif_eur else "vigilance"
        regles.append(Regle("LCB-01", "Origine des fonds", statut,
                            f"Origine non précisée par le client ({l.origine_detail}).",
                            action="Obtenir une origine précise et justifiée avant toute souscription.",
                            reference=REF_CONNAISSANCE, sources=["lcb.origine"]))
    elif origine == "non_abordee":
        regles.append(Regle("LCB-01", "Origine des fonds", "action", "Origine des fonds non abordée pendant l'appel.",
                            action="La recueillir et la justifier avant la souscription.", reference=REF_CONNAISSANCE))
    else:
        regles.append(Regle("LCB-01", "Origine des fonds", "ok",
                            f"Origine déclarée : {libelle_origine} ({l.origine_detail}).",
                            reference=REF_CONNAISSANCE, sources=["lcb.origine"]))

    # LCB-02 — justificatif
    pieces = list(PIECES_SOCLE)
    obligatoires: list[str] = []
    if montant >= pol.seuil_justificatif_eur:
        if piece_origine and origine not in ("floue", "non_abordee"):
            obligatoires.append(piece_origine)
            detail = f"Versement de {_eur(montant)} ≥ {_eur(pol.seuil_justificatif_eur)} : justificatif obligatoire ({piece_origine.lower()})."
        else:
            detail = f"Versement de {_eur(montant)} ≥ {_eur(pol.seuil_justificatif_eur)} : justificatif obligatoire, origine à préciser."
        regles.append(Regle("LCB-02", "Justificatif d'origine des fonds", "action", detail,
                            action="Exiger le justificatif avant d'encaisser.",
                            reference=f"Politique interne v{pol.version}", sources=["projet.montant"]))
    elif montant > 0:
        detail = f"Versement de {_eur(montant)}, sous le seuil de {_eur(pol.seuil_justificatif_eur)}."
        if piece_origine and origine not in ("floue", "non_abordee"):
            detail += f" Pièce recommandée : {piece_origine.lower()}."
        regles.append(Regle("LCB-02", "Justificatif d'origine des fonds", "ok", detail,
                            reference=f"Politique interne v{pol.version}", sources=["projet.montant"]))
    else:
        regles.append(Regle("LCB-02", "Justificatif d'origine des fonds", "action", "Montant non communiqué.",
                            action="Préciser le montant envisagé.", reference=f"Politique interne v{pol.version}"))
    if piece_origine and origine not in ("floue", "non_abordee"):
        pieces.append(piece_origine)

    # LCB-03 — cohérence montant / revenus
    revenus = l.revenus_annuels_eur if verif.est_fiable("lcb.revenus") else 0.0
    if montant > 0 and revenus > 0 and montant > pol.ratio_revenus_vigilance * revenus:
        ratio = montant / revenus
        if origine in EVENEMENTS_PATRIMONIAUX:
            regles.append(Regle("LCB-03", "Cohérence montant / revenus", "ok",
                                f"Montant égal à {_fois(ratio)} les revenus annuels, expliqué par une {libelle_origine}.",
                                reference=REF_CONNAISSANCE, sources=["projet.montant", "lcb.revenus", "lcb.origine"]))
        else:
            regles.append(Regle("LCB-03", "Cohérence montant / revenus", "vigilance",
                                f"Montant égal à {_fois(ratio)} les revenus annuels, sans événement patrimonial identifié.",
                                action="Documenter la constitution de ce patrimoine.",
                                reference=REF_CONNAISSANCE, sources=["projet.montant", "lcb.revenus"]))
    elif montant > 0 and revenus == 0:
        regles.append(Regle("LCB-03", "Cohérence montant / revenus", "action",
                            "Revenus non recueillis : cohérence non vérifiable.",
                            action="Recueillir les revenus annuels.", reference=REF_CONNAISSANCE))
    elif montant > 0:
        regles.append(Regle("LCB-03", "Cohérence montant / revenus", "ok",
                            "Montant cohérent avec les revenus déclarés.", reference=REF_CONNAISSANCE,
                            sources=["projet.montant", "lcb.revenus"]))

    # LCB-04 — tiers payeur (on garde le signal même si la citation est à revoir :
    # un faux positif coûte une vérification, un faux négatif bien plus).
    if l.tiers_payeur == "oui":
        note = "" if verif.est_fiable("lcb.tiers_payeur") else " (citation à vérifier)"
        regles.append(Regle("LCB-04", "Tiers payeur", "escalade",
                            "Une partie des fonds viendrait d'un compte qui n'est pas au nom du client" + note + ".",
                            action="Aucun versement d'un tiers ; transmettre au responsable LCB-FT.",
                            reference=REF_CONNAISSANCE, sources=["lcb.tiers_payeur"]))
    else:
        regles.append(Regle("LCB-04", "Tiers payeur", "ok",
                            "Aucun tiers payeur évoqué. Le RIB au nom du souscripteur sera exigé.",
                            reference=REF_CONNAISSANCE))

    # LCB-05 — espèces
    if l.especes == "oui":
        note = "" if verif.est_fiable("lcb.especes") else " (citation à vérifier)"
        regles.append(Regle("LCB-05", "Espèces", "escalade", "Versement en espèces évoqué par le client" + note + ".",
                            action="Aucun versement en espèces ; transmettre au responsable LCB-FT.",
                            reference=REF_CONNAISSANCE, sources=["lcb.especes"]))
    else:
        regles.append(Regle("LCB-05", "Espèces", "ok", "Aucun versement en espèces évoqué.", reference=REF_CONNAISSANCE))

    # LCB-06 — personne politiquement exposée
    if l.ppe == "oui":
        regles.append(Regle("LCB-06", "Personne politiquement exposée", "vigilance",
                            "Le client ou un proche exerce une fonction politique ou publique importante.",
                            action="Vigilance complémentaire : décision d'entrée en relation par un dirigeant habilité, "
                                   "origine du patrimoine et des fonds.",
                            reference=REF_PPE, sources=["lcb.ppe"]))
    elif l.ppe == "non":
        regles.append(Regle("LCB-06", "Personne politiquement exposée", "ok", "Le client a indiqué ne pas être concerné.",
                            reference=REF_PPE, sources=["lcb.ppe"]))
    else:
        regles.append(Regle("LCB-06", "Personne politiquement exposée", "action", "Statut PPE non abordé pendant l'appel.",
                            action="Le recueillir dans le questionnaire de souscription.", reference=REF_PPE))

    # LCB-07 — signaux comportementaux
    if l.signaux:
        regles.append(Regle("LCB-07", "Signaux comportementaux", "vigilance",
                            f"{len(l.signaux)} {'signal' if len(l.signaux) == 1 else 'signaux'} : " + " ; ".join(s.detail for s in l.signaux) + ".",
                            action="Les porter à la connaissance du responsable LCB-FT.",
                            reference=REF_CONNAISSANCE, sources=[f"lcb.signaux[{i}]" for i in range(len(l.signaux))]))
    else:
        regles.append(Regle("LCB-07", "Signaux comportementaux", "ok", "Aucun signal relevé.", reference=REF_CONNAISSANCE))

    statuts = [r.statut for r in regles]
    if "escalade" in statuts or statuts.count("vigilance") >= pol.nb_vigilances_escalade:
        niveau = "escalade"
    elif "vigilance" in statuts:
        niveau = "renforcee"
    else:
        niveau = "standard"
    return regles, niveau, pieces, obligatoires


def evaluer(a: AnalyseAppel, verif: RapportVerification, pol: Politique = POLITIQUE) -> Conformite:
    recueil = evaluer_recueil(a, verif)
    adequation = evaluer_adequation(a, verif, recueil, pol)
    lcb, niveau, pieces, obligatoires = evaluer_lcb(a, verif, pol)
    questions = [l.question for l in recueil if l.question and (l.requis or l.statut == "manquant")]
    return Conformite(politique=pol.version, recueil=recueil, questions=questions, adequation=adequation,
                      lcb=lcb, niveau_lcb=niveau, pieces=pieces, pieces_obligatoires=obligatoires)
