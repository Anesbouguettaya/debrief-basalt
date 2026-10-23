"""Lecture d'une transcription d'appel.

Format attendu (celui que produisent la plupart des outils de transcription
après diarisation) :

    # Date : 2026-10-22 17:42
    # Conseiller : Léa Fontaine
    # Client : Julien Moreau
    [00:00] Léa Fontaine : Bonjour Monsieur Moreau…
    [00:09] Julien Moreau : Bonjour…
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

ENTETE = re.compile(r"^#\s*([^:]+?)\s*:\s*(.*)$")
TOUR = re.compile(r"^\[(\d{1,2}:\d{2}(?::\d{2})?)\]\s*([^:]+?)\s*:\s*(.+)$")
TOUR_SANS_HEURE = re.compile(r"^([^\[#:][^:]{0,60}?)\s*:\s*(.+)$")

JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
        "septembre", "octobre", "novembre", "décembre"]


@dataclass
class Tour:
    numero: int          # numéro de ligne, à partir de 1 (référence « l. 12 »)
    horodatage: str
    locuteur: str
    role: str            # « conseiller » ou « client »
    texte: str


@dataclass
class Appel:
    identifiant: str
    meta: dict[str, str]
    tours: list[Tour]

    @property
    def conseiller(self) -> str:
        return self.meta.get("conseiller") or next((t.locuteur for t in self.tours if t.role == "conseiller"), "Conseiller")

    @property
    def client(self) -> str:
        return self.meta.get("client") or next((t.locuteur for t in self.tours if t.role == "client"), "Client")

    @property
    def date_iso(self) -> str:
        return (self.meta.get("date") or "").split(" ")[0]

    @property
    def heure(self) -> str:
        parties = (self.meta.get("date") or "").split(" ")
        return parties[1] if len(parties) > 1 else ""

    @property
    def date_longue(self) -> str:
        try:
            d = date.fromisoformat(self.date_iso)
        except ValueError:
            return self.date_iso or "date inconnue"
        return f"{JOURS[d.weekday()]} {d.day} {MOIS[d.month - 1]} {d.year}"

    @property
    def contact_id(self) -> str:
        return self.meta.get("contact hubspot", "")

    @property
    def duree(self) -> str:
        if not self.tours or not self.tours[-1].horodatage:
            return ""
        morceaux = [int(x) for x in self.tours[-1].horodatage.split(":")]
        secondes = morceaux[-1] + 60 * morceaux[-2] + (3600 * morceaux[-3] if len(morceaux) == 3 else 0)
        return f"{secondes // 60} min {secondes % 60:02d} s"

    def texte_pour_modele(self) -> str:
        lignes = []
        for t in self.tours:
            heure = f"[{t.horodatage}] " if t.horodatage else ""
            lignes.append(f"{heure}{t.locuteur} ({t.role}) : {t.texte}")
        return "\n".join(lignes)


def parser_appel(texte: str, identifiant: str = "appel") -> Appel:
    meta: dict[str, str] = {}
    brut: list[tuple[str, str, str]] = []
    for ligne in texte.splitlines():
        ligne = ligne.strip()
        if not ligne:
            continue
        m = ENTETE.match(ligne)
        if m:
            meta[m.group(1).strip().lower()] = m.group(2).strip()
            continue
        m = TOUR.match(ligne)
        if m:
            brut.append((m.group(1), m.group(2).strip(), m.group(3).strip()))
            continue
        m = TOUR_SANS_HEURE.match(ligne)
        if m:
            brut.append(("", m.group(1).strip(), m.group(2).strip()))
        elif brut:  # suite d'un tour sur plusieurs lignes
            h, loc, txt = brut[-1]
            brut[-1] = (h, loc, f"{txt} {ligne}")

    conseiller = meta.get("conseiller", "").lower()
    tours = []
    for i, (h, loc, txt) in enumerate(brut, start=1):
        if conseiller:
            role = "conseiller" if loc.lower() == conseiller else "client"
        else:
            role = "conseiller" if re.search(r"conseill|basalt", loc, re.I) else "client"
        tours.append(Tour(numero=i, horodatage=h, locuteur=loc, role=role, texte=txt))
    return Appel(identifiant=meta.get("identifiant", identifiant), meta=meta, tours=tours)


def lire_appel(chemin: str | Path) -> Appel:
    chemin = Path(chemin)
    return parser_appel(chemin.read_text(encoding="utf-8"), identifiant=chemin.stem)
