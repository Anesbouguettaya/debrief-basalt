"""Orchestration : un appel en entrée, un débrief vérifié en sortie.

    transcription ─▶ extraction (LLM, schéma imposé)
                 ─▶ vérification des citations (code)
                 ─▶ règles DDA + LCB-FT (code)
                 ─▶ relance (LLM, à partir des seuls faits vérifiés) ─▶ linter (code)
                 ─▶ plan HubSpot (code) ─▶ validation du conseiller ─▶ écriture
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from time import perf_counter

from .compliance import Conformite, evaluer
from .config import POLITIQUE, Politique
from .email_lint import ControleLint, verifier_relance
from .grounding import RapportVerification, verifier
from .hubspot import PlanCRM, construire_plan
from .llm import LLM, Usage
from .schemas import AnalyseAppel, Relance
from .transcript import Appel


@dataclass
class Debrief:
    appel: Appel
    analyse: AnalyseAppel
    verification: RapportVerification
    conformite: Conformite
    relance: Relance | None
    statut_relance: str                 # prete | a_revoir | suspendue
    controles_relance: list[ControleLint]
    corrections_relance: int
    plan: PlanCRM
    usages: list[Usage] = field(default_factory=list)
    durees_s: dict[str, float] = field(default_factory=dict)

    @property
    def cout_usd(self) -> float:
        return sum(u.cout_usd for u in self.usages)

    def to_dict(self) -> dict:
        return {
            "appel": {"identifiant": self.appel.identifiant, "client": self.appel.client,
                      "conseiller": self.appel.conseiller, "date": self.appel.date_longue,
                      "duree": self.appel.duree, "tours": len(self.appel.tours)},
            "analyse": self.analyse.model_dump(),
            "verification": {ch: asdict(c) for ch, c in self.verification.resultats.items()},
            "conformite": self.conformite.to_dict(),
            "relance": self.relance.model_dump() if self.relance else None,
            "statut_relance": self.statut_relance,
            "controles_relance": [asdict(c) for c in self.controles_relance],
            "corrections_relance": self.corrections_relance,
            "plan_crm": self.plan.to_dict(),
            "usages": [u.to_dict() for u in self.usages],
            "cout_usd": round(self.cout_usd, 5),
            "durees_s": self.durees_s,
        }


def faits_verifies(appel: Appel, a: AnalyseAppel, v: RapportVerification, conf: Conformite) -> dict:
    """Le seul matériau que reçoit le rédacteur de la relance : des faits dont
    la citation a été retrouvée dans l'appel."""
    p = a.projet
    projet = {}
    if p.montant_initial_eur > 0 and v.est_fiable("projet.montant"):
        projet["versement_initial_eur"] = p.montant_initial_eur
    if p.versement_mensuel_eur > 0 and v.est_fiable("projet.versement"):
        projet["versement_mensuel_eur"] = p.versement_mensuel_eur
    if p.uc_souhaitee_client_pct >= 0 and v.est_fiable("projet.uc_souhaitee"):
        projet["part_uc_souhaitee_par_le_client_pct"] = p.uc_souhaitee_client_pct
    if p.uc_recommandee_conseiller_pct >= 0 and v.est_fiable("projet.uc_recommandee"):
        projet["part_uc_recommandee_par_le_conseiller_pct"] = p.uc_recommandee_conseiller_pct
    recueil = {l.cle: l.valeur for l in conf.recueil if l.statut in ("couvert", "partiel")}
    cr = a.compte_rendu
    return {
        "client": appel.client,
        "conseiller": appel.conseiller,
        "date_appel": appel.date_longue,
        "projet": projet,
        "situation_et_preferences": recueil,
        "points_cles": [x.texte for i, x in enumerate(cr.points_cles) if v.est_fiable(f"compte_rendu.points_cles[{i}]")],
        "questions_et_reponses": [{"question": q.question, "reponse": q.reponse} for i, q in enumerate(cr.questions_client)
                                  if v.est_fiable(f"compte_rendu.questions_client[{i}]")],
        "prochaines_etapes": [{"action": e.action, "porteur": e.porteur, "echeance": e.echeance}
                              for i, e in enumerate(cr.prochaines_etapes)
                              if v.est_fiable(f"compte_rendu.prochaines_etapes[{i}]")],
        "pieces_a_fournir": conf.pieces,
    }


def debriefer(appel: Appel, llm: LLM, crm_avant: dict | None = None, politique: Politique = POLITIQUE,
              max_corrections: int = 1) -> Debrief:
    usages: list[Usage] = []
    durees: dict[str, float] = {}

    t = perf_counter()
    analyse, usage = llm.extraire(appel)
    usages.append(usage)
    durees["extraction"] = round(perf_counter() - t, 3)

    t = perf_counter()
    verification = verifier(analyse, appel.tours)
    conformite = evaluer(analyse, verification, politique)
    durees["controles"] = round(perf_counter() - t, 3)

    relance, statut, controles, corrections = None, "suspendue", [], 0
    if conformite.niveau_lcb != "escalade":
        # Escalade LCB-FT : aucune relance automatique (rien ne doit laisser
        # deviner au client qu'une analyse est en cours, art. L561-18 CMF).
        t = perf_counter()
        faits = faits_verifies(appel, analyse, verification, conformite)
        historique: list[tuple[Relance, list[str]]] = []
        statut = "a_revoir"   # si aucune version ne passe le linter : revue humaine
        for tentative in range(max_corrections + 1):
            relance, usage = llm.rediger_relance(appel, faits, historique)
            usages.append(usage)
            corrections = tentative
            controles = verifier_relance(f"{relance.objet}\n{relance.corps}")
            echecs = [c.message for c in controles if c.statut == "ko"]
            if not echecs:
                statut = "prete"
                break
            historique.append((relance, echecs))
        durees["relance"] = round(perf_counter() - t, 3)

    plan = construire_plan(appel, analyse, verification, conformite, crm_avant or {}, politique)
    return Debrief(appel, analyse, verification, conformite, relance, statut, controles, corrections, plan,
                   usages, durees)
