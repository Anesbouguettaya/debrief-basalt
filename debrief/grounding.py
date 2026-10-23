"""Vérification des sources : aucune donnée n'atteint le CRM sans citation
retrouvée dans l'appel.

Le modèle doit accompagner chaque fait d'une citation exacte. On normalise
(casse, accents, ponctuation, séparateurs de milliers) puis on cherche la
citation dans la transcription :
- « vérifiée » : trouvée telle quelle ;
- « approchée » : au moins 85 % des mots retrouvés dans l'ordre (petite
  variation de transcription), acceptée mais signalée ;
- « introuvable » : rejetée. Le champ CRM correspondant n'est pas écrit.

La démo web réimplémente exactement le même algorithme (engine.js).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from .schemas import AnalyseAppel, iter_sources
from .transcript import Tour

SEUIL_APPROCHE = 0.85
_DIACRITIQUES = re.compile(r"[̀-ͯ]")
_NON_ALPHANUM = re.compile(r"[^a-z0-9]+")
_MILLIERS = re.compile(r"(\d) (?=\d{3}(?:\D|$))")


def normaliser(texte: str) -> str:
    t = unicodedata.normalize("NFKD", texte)
    t = _DIACRITIQUES.sub("", t).lower()
    t = _NON_ALPHANUM.sub(" ", t).strip()
    return _MILLIERS.sub(r"\1", t)


@dataclass
class Correspondance:
    statut: str          # verifiee | approchee | introuvable | vide
    ligne: int | None    # numéro du tour où la citation a été retrouvée
    score: float


def _lcs(a: list[str], b: list[str]) -> int:
    precedente = [0] * (len(b) + 1)
    for x in a:
        courante = [0]
        for j, y in enumerate(b, start=1):
            courante.append(precedente[j - 1] + 1 if x == y else max(precedente[j], courante[j - 1]))
        precedente = courante
    return precedente[-1]


def localiser(citation: str, tours: list[Tour]) -> Correspondance:
    q = normaliser(citation)
    if not q:
        return Correspondance("vide", None, 0.0)
    mots = q.split()
    normalises = [normaliser(t.texte) for t in tours]

    for tour, texte in zip(tours, normalises):
        if f" {q} " in f" {texte} ":
            return Correspondance("verifiee" if len(mots) >= 2 else "approchee", tour.numero, 1.0)

    meilleur, ligne = 0.0, None
    largeur = len(mots) + max(1, int(0.3 * len(mots) + 0.5))   # arrondi identique en JS
    for tour, texte in zip(tours, normalises):
        t = texte.split()
        if not t:
            continue
        for debut in range(0, max(1, len(t) - largeur + 1)):
            fenetre = t[debut:debut + largeur]
            score = _lcs(mots, fenetre) / len(mots)
            if score > meilleur:
                meilleur, ligne = score, tour.numero
    if meilleur >= SEUIL_APPROCHE and len(mots) >= 3:
        return Correspondance("approchee", ligne, round(meilleur, 2))
    return Correspondance("introuvable", None, round(meilleur, 2))


@dataclass
class RapportVerification:
    resultats: dict[str, Correspondance] = field(default_factory=dict)
    citations: dict[str, str] = field(default_factory=dict)

    def get(self, chemin: str) -> Correspondance:
        return self.resultats.get(chemin, Correspondance("vide", None, 0.0))

    def est_fiable(self, chemin: str) -> bool:
        return self.get(chemin).statut in ("verifiee", "approchee")

    @property
    def total(self) -> int:
        return sum(1 for c in self.resultats.values() if c.statut != "vide")

    @property
    def retrouvees(self) -> int:
        return sum(1 for c in self.resultats.values() if c.statut in ("verifiee", "approchee"))

    @property
    def introuvables(self) -> list[tuple[str, str]]:
        return [(ch, self.citations[ch]) for ch, c in self.resultats.items() if c.statut == "introuvable"]


def verifier(analyse: AnalyseAppel, tours: list[Tour]) -> RapportVerification:
    rapport = RapportVerification()
    for chemin, citation in iter_sources(analyse):
        rapport.resultats[chemin] = localiser(citation, tours)
        rapport.citations[chemin] = citation
    return rapport
