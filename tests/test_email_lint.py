import unittest

from debrief.email_lint import verifier_relance


def statuts(texte):
    return {c.id: c.statut for c in verifier_relance(texte)}


class TestLinterRelance(unittest.TestCase):
    def test_texte_neutre(self):
        self.assertEqual(statuts("Bonjour, voici la liste des pièces à fournir."),
                         {"MKT-01": "ok", "MKT-02": "na", "MKT-03": "na", "MKT-04": "ok"})

    def test_promesses_interdites(self):
        for texte in ("Un placement sans risque.", "Un rendement garanti de 4 %.", "Vous allez gagner gros.",
                      "C'est le meilleur placement du marché.", "Risque zéro."):
            with self.subTest(texte):
                self.assertEqual(statuts(texte)["MKT-01"], "ko")

    def test_placement_sur_un_support_n_est_pas_une_promesse(self):
        self.assertEqual(statuts("Votre placement sur le fonds en euros.")["MKT-01"], "ok")
        self.assertEqual(statuts("Un placement totalement sûr.")["MKT-01"], "ko")

    def test_negation_autorisee(self):
        self.assertEqual(statuts("La performance n'est pas garantie.")["MKT-01"], "ok")
        self.assertEqual(statuts("Une performance non garantie.")["MKT-01"], "ok")

    def test_performance_sans_avertissement(self):
        self.assertEqual(statuts("Le fonds en euros a servi 3,4 % net en 2025.")["MKT-02"], "ko")

    def test_performance_avec_avertissement(self):
        texte = ("Le fonds en euros a servi 3,4 % net en 2025. "
                 "Les performances passées ne préjugent pas des performances futures.")
        self.assertEqual(statuts(texte)["MKT-02"], "ok")

    def test_pourcentage_d_allocation_n_est_pas_une_performance(self):
        self.assertEqual(statuts("40 % sur le fonds en euros et 60 % sur le reste.")["MKT-02"], "na")

    def test_uc_sans_risque_de_perte(self):
        self.assertEqual(statuts("Nous proposons 20 % en SCPI.")["MKT-03"], "ko")
        self.assertEqual(statuts("20 % en SCPI, qui présentent un risque de perte en capital.")["MKT-03"], "ok")

    def test_le_mot_actions_seul_ne_declenche_pas(self):
        self.assertEqual(statuts("Voici les actions à mener cette semaine.")["MKT-03"], "na")

    def test_confidentialite_lcb_ft(self):
        for texte in ("Votre dossier fait l'objet d'une revue de conformité.", "Nous avons informé Tracfin.",
                      "Un soupçon de blanchiment"):
            with self.subTest(texte):
                self.assertEqual(statuts(texte)["MKT-04"], "ko")


if __name__ == "__main__":
    unittest.main()
