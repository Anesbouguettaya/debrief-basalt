import unittest

from debrief.compliance import evaluer
from debrief.config import Politique
from debrief.grounding import verifier

from .aides import analyse, appel


def conformite(identifiant, politique=Politique(), **modifs):
    a = analyse(identifiant, **modifs)
    return evaluer(a, verifier(a, appel(identifiant).tours), politique)


def statut(conf, rid):
    return {r.id: r.statut for r in conf.adequation + conf.lcb}[rid]


class TestRecueilDDA(unittest.TestCase):
    def test_durabilite_non_abordee_genere_la_question(self):
        c = conformite("appel_01_moreau")
        self.assertFalse(c.recueil_complet)
        self.assertEqual(c.nb_requis_couverts, 9)
        self.assertEqual(len(c.questions), 1)
        self.assertIn("durabilité", c.questions[0])
        self.assertEqual(statut(c, "ADQ-01"), "action")

    def test_recueil_complet(self):
        c = conformite("appel_02_dubois")
        self.assertTrue(c.recueil_complet)
        self.assertEqual(statut(c, "ADQ-01"), "ok")

    def test_recueil_tres_incomplet_bloque_le_conseil(self):
        self.assertEqual(statut(conformite("appel_03_marchand"), "ADQ-01"), "vigilance")

    def test_item_dont_la_citation_est_introuvable_est_a_verifier(self):
        c = conformite("appel_01_moreau", **{"recueil.horizon": {"statut": "couvert", "valeur": "20 ans",
                                                                  "source": "au moins vingt ans de placement"}})
        horizon = next(l for l in c.recueil if l.cle == "horizon")
        self.assertEqual(horizon.statut, "a_verifier")
        self.assertTrue(any("horizon" in q for q in c.questions))


class TestAdequation(unittest.TestCase):
    def test_allocation_client_au_dela_du_plafond_du_profil(self):
        c = conformite("appel_02_dubois")
        self.assertEqual(statut(c, "ADQ-03"), "vigilance")
        regle = next(r for r in c.adequation if r.id == "ADQ-03")
        self.assertIn("mise en garde orale", regle.detail)
        self.assertEqual(statut(c, "ADQ-04"), "ok")

    def test_allocation_dans_le_plafond(self):
        self.assertEqual(statut(conformite("appel_01_moreau"), "ADQ-03"), "ok")

    def test_le_plafond_vient_de_la_politique(self):
        souple = Politique(uc_max_par_profil={"prudent": 45.0, "equilibre": 70.0, "dynamique": 100.0})
        self.assertEqual(statut(conformite("appel_02_dubois", souple), "ADQ-03"), "ok")

    def test_recommandation_non_adequate_du_conseiller(self):
        c = conformite("appel_01_moreau", **{"projet.uc_recommandee_conseiller_pct": 85})
        self.assertEqual(statut(c, "ADQ-04"), "vigilance")

    def test_horizon_court(self):
        c = conformite("appel_01_moreau", **{"projet.horizon_annees": 3})
        self.assertEqual(statut(c, "ADQ-05"), "vigilance")


class TestLCBFT(unittest.TestCase):
    def test_dossier_standard(self):
        c = conformite("appel_01_moreau")
        self.assertEqual(c.niveau_lcb, "standard")
        self.assertEqual(c.pieces_obligatoires, [])
        self.assertIn("Attestation du notaire (succession)", c.pieces)

    def test_seuil_justificatif(self):
        c = conformite("appel_02_dubois")
        self.assertEqual(statut(c, "LCB-02"), "action")
        self.assertEqual(c.pieces_obligatoires, ["Acte de vente notarié"])
        self.assertEqual(c.niveau_lcb, "standard")

    def test_seuil_inclusif(self):
        c = conformite("appel_01_moreau", **{"projet.montant_initial_eur": 150000})
        self.assertEqual(c.pieces_obligatoires, ["Attestation du notaire (succession)"])

    def test_montant_eleve_explique_par_une_cession(self):
        self.assertEqual(statut(conformite("appel_02_dubois"), "LCB-03"), "ok")

    def test_montant_eleve_sans_evenement_patrimonial(self):
        c = conformite("appel_02_dubois", **{"lcb.origine_fonds": "epargne"})
        self.assertEqual(statut(c, "LCB-03"), "vigilance")
        self.assertEqual(c.niveau_lcb, "renforcee")

    def test_especes_seules_suffisent_a_escalader(self):
        c = conformite("appel_01_moreau", **{"lcb.especes": "oui",
                                              "lcb.especes_source": "je pensais ajouter 300 euros par mois"})
        self.assertEqual(statut(c, "LCB-05"), "escalade")
        self.assertEqual(c.niveau_lcb, "escalade")

    def test_tiers_payeur_garde_meme_si_la_citation_est_douteuse(self):
        c = conformite("appel_01_moreau", **{"lcb.tiers_payeur": "oui",
                                              "lcb.tiers_payeur_source": "mon beau-frère fera le virement"})
        self.assertEqual(statut(c, "LCB-04"), "escalade")
        regle = next(r for r in c.lcb if r.id == "LCB-04")
        self.assertIn("citation à vérifier", regle.detail)

    def test_ppe(self):
        c = conformite("appel_01_moreau", **{"lcb.ppe": "oui", "lcb.ppe_source": "Marié, sans contrat de mariage"})
        self.assertEqual(statut(c, "LCB-06"), "vigilance")
        self.assertEqual(c.niveau_lcb, "renforcee")

    def test_escalade_du_dossier_marchand(self):
        c = conformite("appel_03_marchand")
        self.assertEqual(c.niveau_lcb, "escalade")
        for rid in ("LCB-01", "LCB-04", "LCB-05"):
            self.assertEqual(statut(c, rid), "escalade")
        self.assertEqual(statut(c, "LCB-07"), "vigilance")

    def test_cumul_de_vigilances_escalade(self):
        c = conformite("appel_01_moreau", **{
            "lcb.ppe": "oui", "lcb.ppe_source": "Marié, sans contrat de mariage",
            "lcb.origine_fonds": "epargne", "projet.montant_initial_eur": 200000, "lcb.revenus_annuels_eur": 50000,
            "lcb.signaux": [{"type": "urgence", "detail": "pressé", "source": "pas avant une douzaine d'années"}],
        })
        self.assertEqual(c.niveau_lcb, "escalade")


if __name__ == "__main__":
    unittest.main()
