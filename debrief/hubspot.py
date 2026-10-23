"""Synchronisation HubSpot (API CRM v3).

Rien n'est écrit par défaut. `construire_plan` calcule la liste exacte des
requêtes (avec le diff avant / après de chaque propriété) ; le conseiller la
valide, puis `HubSpotClient.appliquer` l'exécute. Aucune dépendance : urllib.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .compliance import Conformite
from .config import FUSEAU, POLITIQUE, Politique
from .grounding import RapportVerification
from .schemas import LIBELLES_CRM, AnalyseAppel
from .transcript import Appel

PRODUIT = os.getenv("DEBRIEF_PRODUIT", "Basalt Life")
CHEMIN_CRM = "/crm/v3/objects"
DEAL_ID = "$DEAL_ID"

# Identifiants d'association HubSpot par défaut (developers.hubspot.com, API associations v4).
ASSOCIATIONS = {
    "deal_vers_contact": 3,
    "note_vers_contact": 202,
    "note_vers_deal": 214,
    "tache_vers_contact": 204,
    "tache_vers_deal": 216,
}

ETAPES_TRANSACTION = {
    "appointmentscheduled": "RDV planifié",
    "qualifiedtobuy": "Qualifié",
    "presentationscheduled": "Proposition présentée",
    "decisionmakerboughtin": "Décision en cours",
    "contractsent": "Dossier envoyé",
    "closedwon": "Souscrit",
    "closedlost": "Perdu",
}
LIBELLES_CYCLE = {"subscriber": "Abonné", "lead": "Lead", "marketingqualifiedlead": "Lead qualifié marketing",
                  "salesqualifiedlead": "Lead qualifié ventes", "opportunity": "Opportunité", "customer": "Client"}
LIBELLES_STATUT_LEAD = {"NEW": "Nouveau", "OPEN": "Ouvert", "IN_PROGRESS": "En cours", "OPEN_DEAL": "Transaction ouverte",
                        "CONNECTED": "Connecté", "ATTEMPTED_TO_CONTACT": "Tentative de contact",
                        "UNQUALIFIED": "Non qualifié", "BAD_TIMING": "Mauvais moment"}
ORDRE_CYCLE = ["subscriber", "lead", "marketingqualifiedlead", "salesqualifiedlead", "opportunity", "customer", "evangelist"]
TYPES_TACHE = {"appel": "CALL", "email": "EMAIL", "document": "TODO", "rdv": "TODO", "autre": "TODO"}

# Propriétés personnalisées à créer une fois dans le portail (voir creer_proprietes).
PROPRIETES_PERSONNALISEES = [
    (nom, libelle, "number" if nom == "montant_envisage" else "string",
     "number" if nom == "montant_envisage" else "text")
    for nom, libelle in LIBELLES_CRM.items() if nom != "jobtitle"
]


@dataclass
class LigneDiff:
    propriete: str
    libelle: str
    avant: str
    apres: str
    statut: str            # ecrire | inchange | bloque | retenu
    raison: str = ""
    source_chemin: str = ""


@dataclass
class Tache:
    sujet: str
    corps: str
    echeance: str          # heure locale AAAA-MM-JJTHH:MM
    priorite: str          # HIGH | MEDIUM | LOW
    type: str              # CALL | EMAIL | TODO
    origine: str           # appel | recueil | adequation | lcb
    assignee: str          # conseiller | conformite
    source_chemin: str = ""
    nature: str = ""       # appel | email | document | rdv | autre (étape d'origine)


@dataclass
class Operation:
    methode: str
    chemin: str
    corps: dict
    description: str


@dataclass
class PlanCRM:
    contact_id: str
    diff: list[LigneDiff]
    cycle: list[LigneDiff]
    transaction: dict | None
    taches: list[Tache]
    note_html: str
    operations: list[Operation]

    def to_dict(self) -> dict:
        return asdict(self)


# --- Dates ------------------------------------------------------------------------
def _jour_ouvre_suivant(d: date) -> date:
    d += timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def _local(echeance: str, date_appel: str) -> str:
    """Normalise une échéance en heure locale AAAA-MM-JJTHH:MM (09:00 par défaut)."""
    if not echeance:
        return f"{_jour_ouvre_suivant(date.fromisoformat(date_appel)).isoformat()}T09:00"
    return echeance if "T" in echeance else f"{echeance}T09:00"


def vers_utc(local: str) -> str:
    dt = datetime.fromisoformat(local).replace(tzinfo=ZoneInfo(FUSEAU))
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _assoc(cible: str, type_id: int) -> dict:
    return {"to": {"id": cible}, "types": [{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": type_id}]}


def _html(texte: str) -> str:
    return texte.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# --- Plan -------------------------------------------------------------------------
def construire_plan(appel: Appel, a: AnalyseAppel, verif: RapportVerification, conf: Conformite,
                    crm_avant: dict, pol: Politique = POLITIQUE, proprietaires: dict | None = None) -> PlanCRM:
    proprietaires = proprietaires if proprietaires is not None else {
        "conseiller": os.getenv("HUBSPOT_OWNER_CONSEILLER", ""),
        "conformite": os.getenv("HUBSPOT_OWNER_CONFORMITE", ""),
    }
    escalade = conf.niveau_lcb == "escalade"
    contact_id = appel.contact_id or "CONTACT_ID"

    # 1. Propriétés proposées par le modèle → diff vérifié
    diff: list[LigneDiff] = []
    vues: set[str] = set()
    for i, champ in enumerate(a.crm.champs):
        chemin = f"crm.champs[{i}]"
        avant = str(crm_avant.get(champ.propriete, "") or "")
        ligne = LigneDiff(champ.propriete, LIBELLES_CRM.get(champ.propriete, champ.propriete), avant,
                          champ.valeur.strip(), "ecrire", source_chemin=chemin)
        statut_source = verif.get(chemin).statut
        if champ.propriete in vues:
            ligne.statut, ligne.raison = "bloque", "Propriété proposée deux fois : seule la première est retenue."
        elif statut_source in ("introuvable", "vide"):
            ligne.statut = "bloque"
            ligne.raison = ("Citation introuvable dans l'appel : valeur non écrite." if statut_source == "introuvable"
                            else "Aucune citation fournie : valeur non écrite.")
        elif escalade and champ.propriete in pol.proprietes_retenues_si_escalade:
            ligne.statut, ligne.raison = "retenu", "Dossier en revue LCB-FT : transmis à la conformité uniquement."
        elif ligne.apres == avant.strip():
            ligne.statut = "inchange"
        elif avant:
            ligne.raison = "Remplace la valeur existante."
        vues.add(champ.propriete)
        diff.append(ligne)

    # 2. Cycle de vie et statut du lead : décidés par le code, pas par le modèle
    intention = a.compte_rendu.intention
    etape = a.crm.etape_transaction
    ouvre_transaction = (not escalade and etape not in ("aucune", "closedlost")
                         and intention in ("forte", "moyenne"))
    cycle: list[LigneDiff] = []
    cycle_avant = crm_avant.get("lifecyclestage", "")
    statut_avant = crm_avant.get("hs_lead_status", "")
    if ouvre_transaction:
        rang = ORDRE_CYCLE.index(cycle_avant) if cycle_avant in ORDRE_CYCLE else -1
        if rang < ORDRE_CYCLE.index("opportunity"):
            cycle.append(LigneDiff("lifecyclestage", "Cycle de vie", cycle_avant, "opportunity", "ecrire",
                                   "Une transaction est ouverte."))
        if statut_avant != "OPEN_DEAL":
            cycle.append(LigneDiff("hs_lead_status", "Statut du lead", statut_avant, "OPEN_DEAL", "ecrire"))
    elif not escalade and statut_avant in ("", "NEW", "OPEN", "ATTEMPTED_TO_CONTACT"):
        cycle.append(LigneDiff("hs_lead_status", "Statut du lead", statut_avant, "CONNECTED", "ecrire"))

    # 3. Transaction
    transaction = None
    if ouvre_transaction:
        transaction = {"dealname": f"{PRODUIT} — {appel.client}", "pipeline": "default", "dealstage": etape}
        if a.projet.montant_initial_eur > 0 and verif.est_fiable("projet.montant"):
            transaction["amount"] = f"{a.projet.montant_initial_eur:.0f}"
        if a.crm.date_cloture_souhaitee and verif.est_fiable("crm.date_cloture"):
            transaction["closedate"] = f"{a.crm.date_cloture_souhaitee}T12:00:00Z"

    # 4. Tâches
    taches: list[Tache] = []
    if escalade:
        taches.append(Tache(
            sujet=f"Revue LCB-FT avant toute suite — {appel.client}",
            corps="Dossier signalé par Débrief. Le détail des règles déclenchées est transmis au canal conformité. "
                  "Aucune relance client avant décision.",
            echeance=f"{appel.date_iso}T{appel.heure or '09:00'}", priorite="HIGH", type="TODO",
            origine="lcb", assignee="conformite"))
    else:
        for i, e in enumerate(a.compte_rendu.prochaines_etapes):
            chemin = f"compte_rendu.prochaines_etapes[{i}]"
            if e.porteur != "conseiller" or not verif.est_fiable(chemin):
                continue
            ligne = verif.get(chemin).ligne
            taches.append(Tache(
                sujet=e.action, corps=f"Convenu pendant l'appel du {appel.date_longue} (l. {ligne}).",
                echeance=_local(e.echeance, appel.date_iso),
                priorite="HIGH" if e.type in ("appel", "rdv") else "MEDIUM",
                type=TYPES_TACHE[e.type], origine="appel", assignee="conseiller", source_chemin=chemin,
                nature=e.type))
        prochain_contact = next((t.echeance for t in taches if t.nature in ("appel", "rdv")), None)
        defaut = prochain_contact or _local("", appel.date_iso)
        if conf.questions:
            n = len(conf.questions)
            taches.append(Tache(
                sujet=f"Compléter le recueil DDA ({n} question{'s' if n > 1 else ''})",
                corps="À poser lors du prochain échange :\n" + "\n".join(f"• {q}" for q in conf.questions),
                echeance=defaut, priorite="MEDIUM", type="TODO", origine="recueil", assignee="conseiller"))
        for r in conf.adequation:
            if r.statut == "vigilance":
                taches.append(Tache(sujet=f"{r.id} · {r.titre}", corps=f"{r.detail}\n{r.action}", echeance=defaut,
                                    priorite="HIGH", type="TODO", origine="adequation", assignee="conseiller"))
        for piece in conf.pieces_obligatoires:
            taches.append(Tache(sujet=f"Collecter : {piece.lower()}",
                                corps="Justificatif obligatoire avant tout encaissement (règle LCB-02).",
                                echeance=defaut, priorite="HIGH", type="TODO", origine="lcb", assignee="conseiller"))

    # 5. Note de compte rendu
    entete = f"<p><strong>Appel du {appel.date_longue}</strong> · {_html(appel.conseiller)} · préparé par Débrief, validé par le conseiller</p>"
    if escalade:
        note = entete + ("<p>Échange de découverte. Dossier transmis pour revue interne avant toute suite : "
                         "ne pas relancer le client sans l'accord de la conformité.</p>")
    else:
        points = [p.texte for i, p in enumerate(a.compte_rendu.points_cles)
                  if verif.est_fiable(f"compte_rendu.points_cles[{i}]")]
        etapes = [f"{e.action}" + (f" ({e.echeance.replace('T', ' à ')})" if e.echeance else "")
                  for i, e in enumerate(a.compte_rendu.prochaines_etapes)
                  if verif.est_fiable(f"compte_rendu.prochaines_etapes[{i}]")]
        note = (entete + f"<p>{_html(a.compte_rendu.resume)}</p>"
                + "<p><strong>Points clés</strong></p><ul>" + "".join(f"<li>{_html(p)}</li>" for p in points) + "</ul>"
                + "<p><strong>Prochaines étapes</strong></p><ul>" + "".join(f"<li>{_html(e)}</li>" for e in etapes) + "</ul>")

    # 6. Requêtes
    operations: list[Operation] = []
    proprietes = {l.propriete: l.apres for l in diff if l.statut == "ecrire"}
    proprietes.update({l.propriete: l.apres for l in cycle})
    if proprietes:
        operations.append(Operation("PATCH", f"{CHEMIN_CRM}/contacts/{contact_id}", {"properties": proprietes},
                                    f"Mettre à jour {len(proprietes)} propriétés du contact"))
    if transaction:
        operations.append(Operation("POST", f"{CHEMIN_CRM}/deals",
                                    {"properties": transaction,
                                     "associations": [_assoc(contact_id, ASSOCIATIONS["deal_vers_contact"])]},
                                    "Créer la transaction"))
    assoc_note = [_assoc(contact_id, ASSOCIATIONS["note_vers_contact"])]
    if transaction:
        assoc_note.append(_assoc(DEAL_ID, ASSOCIATIONS["note_vers_deal"]))
    operations.append(Operation("POST", f"{CHEMIN_CRM}/notes",
                                {"properties": {"hs_timestamp": vers_utc(f"{appel.date_iso}T{appel.heure or '09:00'}"),
                                                "hs_note_body": note},
                                 "associations": assoc_note},
                                "Ajouter le compte rendu en note"))
    for t in taches:
        props = {"hs_timestamp": vers_utc(t.echeance), "hs_task_subject": t.sujet, "hs_task_body": t.corps,
                 "hs_task_status": "NOT_STARTED", "hs_task_priority": t.priorite, "hs_task_type": t.type}
        if proprietaires.get(t.assignee):
            props["hubspot_owner_id"] = proprietaires[t.assignee]
        assoc = [_assoc(contact_id, ASSOCIATIONS["tache_vers_contact"])]
        if transaction:
            assoc.append(_assoc(DEAL_ID, ASSOCIATIONS["tache_vers_deal"]))
        operations.append(Operation("POST", f"{CHEMIN_CRM}/tasks", {"properties": props, "associations": assoc},
                                    f"Créer la tâche « {t.sujet} »"))

    return PlanCRM(contact_id, diff, cycle, transaction, taches, note, operations)


# --- Client HTTP ------------------------------------------------------------------
class ErreurHubSpot(RuntimeError):
    def __init__(self, statut: int, message: str):
        super().__init__(f"HubSpot {statut} : {message[:300]}")
        self.statut = statut


def _transport_urllib(methode: str, url: str, corps: dict | None, entetes: dict) -> dict:
    donnees = json.dumps(corps).encode("utf-8") if corps is not None else None
    requete = urllib.request.Request(url, data=donnees, method=methode, headers=entetes)
    try:
        with urllib.request.urlopen(requete, timeout=20) as reponse:
            contenu = reponse.read()
            return json.loads(contenu) if contenu else {}
    except urllib.error.HTTPError as e:
        raise ErreurHubSpot(e.code, e.read().decode("utf-8", "replace")) from e


class HubSpotClient:
    def __init__(self, token: str, base_url: str = "https://api.hubapi.com", transport=_transport_urllib,
                 pause=time.sleep):
        if not token:
            raise ValueError("Jeton d'application privée HubSpot manquant (HUBSPOT_TOKEN).")
        self.token, self.base_url, self._transport, self._pause = token, base_url, transport, pause

    def requete(self, methode: str, chemin: str, corps: dict | None = None, essais: int = 3) -> dict:
        entetes = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
        for essai in range(essais):
            try:
                return self._transport(methode, self.base_url + chemin, corps, entetes)
            except ErreurHubSpot as e:
                if e.statut == 429 and essai < essais - 1:   # limite de débit : on patiente
                    self._pause(2 ** essai)
                    continue
                raise
        return {}

    def lire_contact(self, contact_id: str, proprietes: list[str]) -> dict:
        requete = urllib.parse.urlencode({"properties": ",".join(proprietes)})
        return self.requete("GET", f"{CHEMIN_CRM}/contacts/{contact_id}?{requete}").get("properties", {})

    def appliquer(self, plan: PlanCRM) -> list[dict]:
        resultats, deal_id = [], None
        for op in plan.operations:
            corps = op.corps
            if DEAL_ID in json.dumps(corps):
                if deal_id:
                    corps = json.loads(json.dumps(corps).replace(DEAL_ID, deal_id))
                else:
                    corps = dict(corps, associations=[a for a in corps["associations"] if a["to"]["id"] != DEAL_ID])
            reponse = self.requete(op.methode, op.chemin, corps)
            if op.chemin.endswith("/deals"):
                deal_id = str(reponse.get("id", "")) or None
            resultats.append({"operation": op.description, "id": reponse.get("id")})
        return resultats


def creer_proprietes(client: HubSpotClient, groupe: str = "contactinformation") -> list[str]:
    """Crée les propriétés personnalisées (une seule fois par portail)."""
    creees = []
    for nom, libelle, type_, champ in PROPRIETES_PERSONNALISEES:
        try:
            client.requete("POST", "/crm/v3/properties/contacts",
                           {"name": nom, "label": libelle, "type": type_, "fieldType": champ, "groupName": groupe})
            creees.append(nom)
        except ErreurHubSpot as e:
            if e.statut != 409:   # 409 : la propriété existe déjà
                raise
    return creees
