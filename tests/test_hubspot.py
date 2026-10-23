import json
import unittest

from debrief.hubspot import ASSOCIATIONS, DEAL_ID, ErreurHubSpot, HubSpotClient, vers_utc

from .aides import debrief


class TestPlan(unittest.TestCase):
    def test_champ_sans_source_jamais_ecrit(self):
        plan = debrief("appel_01_moreau").plan
        immo = next(l for l in plan.diff if l.propriete == "patrimoine_immobilier")
        self.assertEqual(immo.statut, "bloque")
        patch = plan.operations[0]
        self.assertEqual(patch.methode, "PATCH")
        self.assertNotIn("patrimoine_immobilier", patch.corps["properties"])

    def test_diff_avant_apres(self):
        plan = debrief("appel_01_moreau").plan
        metier = next(l for l in plan.diff if l.propriete == "jobtitle")
        self.assertEqual((metier.avant, metier.apres, metier.statut), ("Ingénieur", "Ingénieur aéronautique (cadre)", "ecrire"))
        self.assertEqual(metier.raison, "Remplace la valeur existante.")

    def test_cycle_de_vie_decide_par_le_code(self):
        plan = debrief("appel_01_moreau").plan
        self.assertEqual({l.propriete: l.apres for l in plan.cycle},
                         {"lifecyclestage": "opportunity", "hs_lead_status": "OPEN_DEAL"})

    def test_transaction(self):
        t = debrief("appel_01_moreau").plan.transaction
        self.assertEqual(t["amount"], "80000")
        self.assertEqual(t["dealstage"], "presentationscheduled")
        self.assertEqual(t["closedate"], "2026-11-15T12:00:00Z")

    def test_taches_et_identifiants_d_association(self):
        plan = debrief("appel_01_moreau").plan
        sujets = [t.sujet for t in plan.taches]
        self.assertEqual(len(sujets), 3)
        self.assertTrue(sujets[2].startswith("Compléter le recueil DDA"))
        rappel = plan.taches[1]
        self.assertEqual((rappel.type, rappel.echeance), ("CALL", "2026-10-27T18:30"))
        self.assertEqual(plan.taches[2].echeance, "2026-10-27T18:30")   # questions DDA rattachées au rappel
        taches = [o for o in plan.operations if o.chemin.endswith("/tasks")]
        types = [a["types"][0]["associationTypeId"] for a in taches[0].corps["associations"]]
        self.assertEqual(types, [ASSOCIATIONS["tache_vers_contact"], ASSOCIATIONS["tache_vers_deal"]])

    def test_heure_locale_convertie_en_utc(self):
        self.assertEqual(vers_utc("2026-10-22T20:00"), "2026-10-22T18:00:00Z")   # heure d'été
        self.assertEqual(vers_utc("2026-10-27T18:30"), "2026-10-27T17:30:00Z")   # heure d'hiver

    def test_escalade(self):
        d = debrief("appel_03_marchand")
        plan = d.plan
        self.assertIsNone(plan.transaction)
        self.assertEqual(plan.cycle, [])
        self.assertEqual(len(plan.taches), 1)
        self.assertEqual(plan.taches[0].assignee, "conformite")
        origine = next(l for l in plan.diff if l.propriete == "origine_des_fonds")
        self.assertEqual(origine.statut, "retenu")
        note = next(o for o in plan.operations if o.chemin.endswith("/notes"))
        texte = json.dumps(note.corps, ensure_ascii=False).lower()
        for mot in ("espèces", "liquide", "associé", "affaires"):
            self.assertNotIn(mot, texte)


class TransportFactice:
    def __init__(self, reponses=None):
        self.appels, self.reponses = [], list(reponses or [])

    def __call__(self, methode, url, corps, entetes):
        self.appels.append((methode, url, corps, entetes))
        if self.reponses:
            r = self.reponses.pop(0)
            if isinstance(r, Exception):
                raise r
            return r
        return {"id": str(100 + len(self.appels))}


class TestClient(unittest.TestCase):
    def test_application_du_plan_substitue_l_id_de_la_transaction(self):
        transport = TransportFactice()
        client = HubSpotClient("pat-test", transport=transport)
        resultats = client.appliquer(debrief("appel_01_moreau").plan)
        self.assertEqual(len(resultats), len(transport.appels))
        methodes = [(m, u.split("/crm/v3/objects/")[1].split("/")[0]) for m, u, _, _ in transport.appels]
        self.assertEqual(methodes[:3], [("PATCH", "contacts"), ("POST", "deals"), ("POST", "notes")])
        deal_id = "102"
        corps_note = transport.appels[2][2]
        self.assertIn(deal_id, json.dumps(corps_note))
        self.assertNotIn(DEAL_ID, json.dumps(corps_note))
        self.assertEqual(transport.appels[0][3]["Authorization"], "Bearer pat-test")

    def test_reessai_sur_limite_de_debit(self):
        pauses = []
        transport = TransportFactice([ErreurHubSpot(429, "rate limit"), {"id": "1"}])
        client = HubSpotClient("pat-test", transport=transport, pause=pauses.append)
        self.assertEqual(client.requete("GET", "/crm/v3/objects/contacts/1"), {"id": "1"})
        self.assertEqual(pauses, [1])

    def test_erreur_definitive_remontee(self):
        client = HubSpotClient("pat-test", transport=TransportFactice([ErreurHubSpot(400, "bad property")]))
        with self.assertRaises(ErreurHubSpot):
            client.requete("PATCH", "/crm/v3/objects/contacts/1", {"properties": {}})

    def test_jeton_obligatoire(self):
        with self.assertRaises(ValueError):
            HubSpotClient("")


if __name__ == "__main__":
    unittest.main()
