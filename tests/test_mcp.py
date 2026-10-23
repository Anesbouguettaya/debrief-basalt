import asyncio
import importlib.util
import os
import unittest

from .aides import RACINE


@unittest.skipUnless(importlib.util.find_spec("mcp"), "SDK MCP non installé (pip install -e '.[mcp]')")
class TestServeurMCP(unittest.TestCase):
    def setUp(self):
        os.environ["DEBRIEF_REJOUER"] = "1"
        from debrief import mcp_server
        self.module = mcp_server

    def tearDown(self):
        os.environ.pop("DEBRIEF_REJOUER", None)

    def test_outils_exposes(self):
        outils = asyncio.run(self.module.serveur.list_tools())
        self.assertEqual({o.name for o in outils}, {"debriefer_appel", "questions_a_poser"})

    def test_debriefer_appel(self):
        texte = (RACINE / "samples" / "appel_03_marchand.txt").read_text(encoding="utf-8")
        resultat = self.module.debriefer_appel(texte)
        self.assertEqual(resultat["niveau_lcb"], "escalade")
        self.assertIsNone(resultat["relance"])

    def test_questions_a_poser(self):
        texte = (RACINE / "samples" / "appel_01_moreau.txt").read_text(encoding="utf-8")
        questions = self.module.questions_a_poser(texte)
        self.assertEqual(len(questions), 1)


if __name__ == "__main__":
    unittest.main()
