import io
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace

from debrief.evals import executer
from debrief.llm import ClaudeLLM, ErreurLLM, RejeuLLM, Usage
from debrief.pipeline import debriefer, faits_verifies
from debrief.schemas import Relance

from .aides import RACINE, analyse, appel, debrief


class TestPipeline(unittest.TestCase):
    def test_relance_prete_du_premier_coup(self):
        d = debrief("appel_01_moreau")
        self.assertEqual((d.statut_relance, d.corrections_relance), ("prete", 0))
        self.assertEqual(len(d.usages), 2)

    def test_relance_corrigee_apres_le_linter(self):
        d = debrief("appel_02_dubois")
        self.assertEqual((d.statut_relance, d.corrections_relance), ("prete", 1))
        self.assertIn("risque de perte en capital", d.relance.corps)
        self.assertEqual(len(d.usages), 3)

    def test_escalade_aucune_relance_generee(self):
        d = debrief("appel_03_marchand")
        self.assertEqual(d.statut_relance, "suspendue")
        self.assertIsNone(d.relance)
        self.assertEqual([u.etape for u in d.usages], ["extraction"])

    def test_relance_redigee_a_partir_des_seuls_faits_verifies(self):
        a, d = appel("appel_01_moreau"), debrief("appel_01_moreau")
        faits = faits_verifies(a, d.analyse, d.verification, d.conformite)
        self.assertNotIn("450 000", str(faits))
        self.assertEqual(faits["projet"]["versement_initial_eur"], 80000)

    def test_export_complet(self):
        donnees = debrief("appel_02_dubois").to_dict()
        for cle in ("analyse", "verification", "conformite", "plan_crm", "relance", "usages"):
            self.assertIn(cle, donnees)
        self.assertGreater(donnees["cout_usd"], 0)

    def test_evals_en_rejeu(self):
        with redirect_stdout(io.StringIO()) as sortie:
            code = executer(RejeuLLM(RACINE / "fixtures"))
        self.assertEqual(code, 0)
        self.assertIn("Erreurs critiques       : 0", sortie.getvalue())


class ClientFactice:
    """Imite client.messages.parse du SDK Anthropic."""

    def __init__(self, sorties, stop_reason="end_turn"):
        self.sorties, self.appels, self.stop_reason = list(sorties), [], stop_reason
        self.messages = self

    def parse(self, **kwargs):
        self.appels.append(kwargs)
        usage = SimpleNamespace(input_tokens=1000, output_tokens=500, cache_creation_input_tokens=0,
                                cache_read_input_tokens=2000)
        return SimpleNamespace(parsed_output=self.sorties.pop(0), usage=usage, stop_reason=self.stop_reason)


class TestClaudeLLM(unittest.TestCase):
    def test_sortie_structuree_et_cache_du_prompt(self):
        client = ClientFactice([analyse("appel_01_moreau")])
        sortie, usage = ClaudeLLM(client=client).extraire(appel("appel_01_moreau"))
        kwargs = client.appels[0]
        self.assertEqual(kwargs["model"], "claude-sonnet-5-5")
        self.assertEqual(kwargs["output_format"].__name__, "AnalyseAppel")
        self.assertEqual(kwargs["system"][0]["cache_control"], {"type": "ephemeral"})
        self.assertIn("Julien Moreau (client)", kwargs["messages"][0]["content"])
        self.assertEqual(sortie.projet.montant_initial_eur, 80000)
        self.assertAlmostEqual(usage.cout_usd, (1000 * 2 + 500 * 10 + 2000 * 0.10) / 1e6)

    def test_correction_renvoie_le_brouillon_et_les_motifs(self):
        brouillon = Relance(objet="o", corps="c")
        client = ClientFactice([Relance(objet="o2", corps="c2")])
        ClaudeLLM(client=client).rediger_relance(appel("appel_01_moreau"), {"client": "x"}, [(brouillon, ["motif A"])])
        roles = [m["role"] for m in client.appels[0]["messages"]]
        self.assertEqual(roles, ["user", "assistant", "user"])
        self.assertIn("motif A", client.appels[0]["messages"][2]["content"])
        self.assertEqual(client.appels[0]["model"], "claude-haiku-5-5")

    def test_reponse_tronquee(self):
        client = ClientFactice([None], stop_reason="max_tokens")
        with self.assertRaises(ErreurLLM):
            ClaudeLLM(client=client).extraire(appel("appel_01_moreau"))

    def test_pipeline_complet_avec_le_client_factice(self):
        client = ClientFactice([analyse("appel_01_moreau"), Relance(objet="Récapitulatif", corps="Bonjour, voici les pièces.")])
        d = debriefer(appel("appel_01_moreau"), ClaudeLLM(client=client))
        self.assertEqual(d.statut_relance, "prete")
        self.assertFalse(any(u.estime for u in d.usages))


class TestUsage(unittest.TestCase):
    def test_modele_inconnu_cout_nul(self):
        self.assertEqual(Usage(modele="inconnu", etape="x", input_tokens=10).cout_usd, 0.0)


if __name__ == "__main__":
    unittest.main()
