"""Assemble la page de démo autonome : gabarit + moteur JS + données + code source.

    python scripts/construire_demo.py

Produit demo/debrief.html (fragment publié tel quel) et demo/index.html
(document complet, servable par GitHub Pages ou ouvrable en local).
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
DEMO = RACINE / "demo"

FICHIERS_CODE = [
    "README.md", "pyproject.toml",
    "debrief/pipeline.py", "debrief/schemas.py", "debrief/llm.py", "debrief/prompts.py", "debrief/grounding.py",
    "debrief/compliance.py", "debrief/email_lint.py", "debrief/hubspot.py", "debrief/transcript.py",
    "debrief/config.py", "debrief/evals.py", "debrief/mcp_server.py", "debrief/__main__.py",
    "tests/test_compliance.py", "tests/test_grounding.py", "tests/test_email_lint.py", "tests/test_hubspot.py",
    "tests/test_pipeline.py", "tests/test_mcp.py",
    "evals/attendus.json", "fixtures/appel_01_moreau.extraction.json", "samples/appel_03_marchand.txt",
]
ENTREES = [
    ("Escalade LCB-FT", "debrief/compliance.py", "# LCB-04"),
    ("Aucun champ sans source", "debrief/grounding.py", "def localiser"),
    ("Sortie structurée Claude", "debrief/llm.py", "reponse = self.client.messages.parse("),
    ("Relance suspendue", "debrief/pipeline.py", "if conformite.niveau_lcb != \"escalade\":"),
    ("Plan HubSpot", "debrief/hubspot.py", "def construire_plan"),
    ("Tests de conformité", "tests/test_compliance.py", "class TestLCBFT"),
]


def _json_sur(objet) -> str:
    return json.dumps(objet, ensure_ascii=False).replace("</", "<\\/")


def main() -> None:
    spec = importlib.util.spec_from_file_location("exporter_demo", RACINE / "scripts" / "exporter_demo.py")
    exporter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(exporter)
    donnees, _ = exporter.construire()

    fichiers = []
    for chemin in FICHIERS_CODE:
        contenu = (RACINE / chemin).read_text(encoding="utf-8")
        contenu = contenu.replace("{{LIEN_DEMO}}", "la page que vous consultez")
        fichiers.append({"chemin": chemin, "contenu": contenu, "lignes": contenu.count("\n") + (0 if contenu.endswith("\n") else 1)})
    entrees = []
    for libelle, chemin, ancre in ENTREES:
        lignes = (RACINE / chemin).read_text(encoding="utf-8").splitlines()
        numero = next(i for i, l in enumerate(lignes, start=1) if ancre in l)
        entrees.append({"libelle": libelle, "chemin": chemin, "ligne": numero})

    nb_tests = sum(len(re.findall(r"^\s+def test_", p.read_text(encoding="utf-8"), re.M)) for p in (RACINE / "tests").glob("test_*.py"))
    nb_regles = len(set(re.findall(r'Regle\("((?:ADQ|LCB)-\d+)"', (RACINE / "debrief" / "compliance.py").read_text(encoding="utf-8"))))

    moteur = (DEMO / "engine.js").read_text(encoding="utf-8")
    assert "</script" not in moteur.lower()
    page = (DEMO / "page.html").read_text(encoding="utf-8")
    page = (page.replace("{{NB_TESTS}}", str(nb_tests)).replace("{{NB_REGLES}}", str(nb_regles))
            .replace("<!--MOTEUR-->", f"<script>\n{moteur}\n</script>")
            .replace("<!--DONNEES-->", f'<script type="application/json" id="donnees">{_json_sur(donnees)}</script>')
            .replace("<!--CODE-->", f'<script type="application/json" id="code">{_json_sur({"fichiers": fichiers, "entrees": entrees})}</script>'))
    (DEMO / "debrief.html").write_text(page, encoding="utf-8")
    complet = ('<!doctype html>\n<html lang="fr">\n<head>\n<meta charset="utf-8">\n'
               '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
               '</head>\n<body>\n' + page + '\n</body>\n</html>\n')
    (DEMO / "index.html").write_text(complet, encoding="utf-8")
    print(f"demo/debrief.html : {len(page) // 1024} Ko · {nb_tests} tests · {nb_regles} règles · {len(fichiers)} fichiers de code")


if __name__ == "__main__":
    main()
