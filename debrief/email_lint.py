"""Relecture de conformité des e-mails de relance, avant tout envoi.

Quatre contrôles déterministes. Un contrôle « ko » renvoie le brouillon au
modèle avec le motif ; au-delà d'une correction, l'e-mail part en revue
humaine au lieu d'être proposé tel quel.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_I = re.IGNORECASE

INTERDITS = [
    (re.compile(r"sans\s+risques?", _I), "« sans risque »"),
    (re.compile(r"risque\s+z[ée]ro|z[ée]ro\s+risque", _I), "« risque zéro »"),
    (re.compile(r"(rendement|performance|gain|plus-value)s?\s+(?:\S+\s+){0,2}garanti", _I), "rendement présenté comme garanti"),
    (re.compile(r"vous\s+allez\s+gagner", _I), "« vous allez gagner »"),
    (re.compile(r"meilleur\s+placement", _I), "« meilleur placement »"),
    (re.compile(r"placement\s+(?:100\s*%\s*|totalement\s+|parfaitement\s+)?sûr", _I), "« placement sûr »"),
]
NEGATION = re.compile(r"\b(non|pas|ni|jamais)\b", _I)

PERFORMANCE_CHIFFREE = re.compile(
    r"\d+(?:[.,]\d+)?\s?%[^.\n]{0,40}\b(net|brut|rendement|performance|servi)"
    r"|\b(rendement|performance|servi|rapport[ée])[^.\n]{0,40}\d+(?:[.,]\d+)?\s?%", _I)
MENTION_PERFORMANCES = re.compile(r"performances?\s+pass[ée]es?\s+ne\s+pr[ée]jugen?t?\s+pas", _I)

SUPPORTS_UC = re.compile(
    r"unit[ée]s?\s+de\s+compte|\bUC\b|\bETF\b|\bSCPI\b|\bSCI\b|\bOPCVM\b|fonds\s+indiciels?|en\s+actions|march[ée]s?\s+actions", _I)
MENTION_PERTE = re.compile(r"risque\s+de\s+perte\s+en\s+capital", _I)

DIVULGATION = re.compile(
    r"tracfin|soup[çc]on|blanchiment|lcb[\s-]?ft|(analyse|revue|contr[ôo]le)\s+(de\s+)?conformit", _I)


@dataclass
class ControleLint:
    id: str
    titre: str
    statut: str      # ok | ko | na
    message: str


def verifier_relance(texte: str) -> list[ControleLint]:
    controles: list[ControleLint] = []

    trouves = []
    for motif, libelle in INTERDITS:
        for m in motif.finditer(texte):
            if not NEGATION.search(m.group(0)):
                trouves.append(libelle)
    controles.append(ControleLint(
        "MKT-01", "Aucune promesse de rendement ni d'absence de risque",
        "ko" if trouves else "ok",
        "Formulation interdite : " + ", ".join(sorted(set(trouves))) + "." if trouves else "Aucune formulation interdite."))

    if PERFORMANCE_CHIFFREE.search(texte):
        ok = bool(MENTION_PERFORMANCES.search(texte))
        controles.append(ControleLint(
            "MKT-02", "Performance chiffrée accompagnée de l'avertissement", "ok" if ok else "ko",
            "Mention « les performances passées ne préjugent pas des performances futures » présente." if ok
            else "Une performance est citée sans la mention « les performances passées ne préjugent pas des performances futures »."))
    else:
        controles.append(ControleLint("MKT-02", "Performance chiffrée accompagnée de l'avertissement", "na",
                                      "Aucune performance chiffrée."))

    if SUPPORTS_UC.search(texte):
        ok = bool(MENTION_PERTE.search(texte))
        controles.append(ControleLint(
            "MKT-03", "Unités de compte : risque de perte en capital mentionné", "ok" if ok else "ko",
            "Mention du risque de perte en capital présente." if ok
            else "Des unités de compte sont évoquées sans mentionner le risque de perte en capital."))
    else:
        controles.append(ControleLint("MKT-03", "Unités de compte : risque de perte en capital mentionné", "na",
                                      "Aucun support en unités de compte évoqué."))

    divulgation = DIVULGATION.search(texte)
    controles.append(ControleLint(
        "MKT-04", "Aucune mention d'une analyse interne (confidentialité LCB-FT)",
        "ko" if divulgation else "ok",
        f"Le texte évoque une analyse interne (« {divulgation.group(0)} »)." if divulgation
        else "Aucune mention d'analyse interne."))
    return controles
