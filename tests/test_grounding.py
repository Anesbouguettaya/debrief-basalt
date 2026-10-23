import unittest

from debrief.grounding import localiser, normaliser, verifier
from debrief.transcript import parser_appel

from .aides import APPELS, analyse, appel

TRANSCRIPTION = """# Conseiller : Léa
[00:00] Léa : Vous gardez une épargne de précaution ?
[00:05] Julien : Oui, on garde 15 000 euros sur les livrets, on n'y touche pas.
[00:12] Julien : J’ai un PEA depuis 2021, uniquement des ETF, en gros un ETF monde.
"""


class TestNormalisation(unittest.TestCase):
    def test_accents_casse_ponctuation(self):
        self.assertEqual(normaliser("Épargne  de PRÉCAUTION ?"), "epargne de precaution")

    def test_apostrophes_typographiques(self):
        self.assertEqual(normaliser("J’ai un PEA"), normaliser("J'ai un PEA"))

    def test_separateurs_de_milliers(self):
        self.assertEqual(normaliser("15 000 euros"), "15000 euros")
        self.assertEqual(normaliser("1 250 000 €"), "1250000")
        self.assertEqual(normaliser("15 000 euros"), "15000 euros")


class TestLocalisation(unittest.TestCase):
    def setUp(self):
        self.tours = parser_appel(TRANSCRIPTION).tours

    def test_citation_exacte(self):
        c = localiser("on garde 15 000 euros sur les livrets", self.tours)
        self.assertEqual((c.statut, c.ligne), ("verifiee", 2))

    def test_citation_avec_typographie_differente(self):
        c = localiser("j'ai un PEA depuis 2021, uniquement des ETF", self.tours)
        self.assertEqual((c.statut, c.ligne), ("verifiee", 3))

    def test_citation_legerement_differente_est_approchee(self):
        c = localiser("on garde 15 000 euros sur nos livrets on n'y touche pas", self.tours)
        self.assertEqual(c.statut, "approchee")
        self.assertEqual(c.ligne, 2)

    def test_citation_inventee_est_rejetee(self):
        c = localiser("notre appartement vaut environ 450 000 euros", self.tours)
        self.assertEqual(c.statut, "introuvable")
        self.assertIsNone(c.ligne)

    def test_citation_vide(self):
        self.assertEqual(localiser("", self.tours).statut, "vide")

    def test_mot_isole_jamais_pleinement_verifie(self):
        self.assertEqual(localiser("livrets", self.tours).statut, "approchee")


class TestVerificationDesAppels(unittest.TestCase):
    def test_toutes_les_citations_enregistrees_sont_retrouvees_sauf_l_invention(self):
        for identifiant in APPELS:
            with self.subTest(identifiant):
                rapport = verifier(analyse(identifiant), appel(identifiant).tours)
                introuvables = [chemin for chemin, _ in rapport.introuvables]
                attendu = ["crm.champs[4]"] if identifiant == "appel_01_moreau" else []
                self.assertEqual(introuvables, attendu)


if __name__ == "__main__":
    unittest.main()
