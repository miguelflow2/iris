"""« Décrire devant moi » (Ctrl+Maj+D et barre système) ne présente plus comme prête une photo refusée.

Contre-vérification du 2026-09-14 (groupe renderer) : le raccourci envoyait toujours {mode: scene, source:
lunettes} alors que le service refuse la caméra des lunettes (409 camera_non_confirmee) tant que son protocole
n'est pas confirmé ; l'écran Accessibilité affirmait « Le raccourci Ctrl+Maj+D suit ce choix » et le menu de la
barre système proposait l'entrée comme si elle marchait.

La décision vit dans electron/main/decrire.ts (sans Electron) : Node l'exécute ici tel quel (effacement des
types de Node 24), nourri par la VRAIE réponse de GET /api/lunettes/presence. Chaque test échoue sans le
correctif (module absent, photo demandée malgré camera_lunettes_active=false, phrase inconditionnelle).
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
DECRIRE_TS = RACINE / "electron" / "main" / "decrire.ts"
INDEX_TS = RACINE / "electron" / "main" / "index.ts"
ACCESSIBILITE_TSX = RACINE / "renderer" / "src" / "screens" / "AccessibiliteScreen.tsx"


def _node(*expressions: str) -> list:
    """Évalue chaque expression (qui peut utiliser `m`, le module decrire.ts) en UN seul lancement de Node
    et rend la liste de leurs résultats JSON."""
    node = shutil.which("node")
    if not node:
        pytest.skip("Node est absent de cette machine : la décision TypeScript ne peut pas être exécutée.")
    assert DECRIRE_TS.exists(), "electron/main/decrire.ts manque : la décision du raccourci n'est pas isolée"
    script = (
        f"const m = await import({json.dumps(DECRIRE_TS.as_uri())});"
        f"process.stdout.write(JSON.stringify([{', '.join(expressions)}]));"
    )
    sortie = subprocess.run(
        [node, "--no-warnings", "--input-type=module", "-e", script],
        capture_output=True, text=True, encoding="utf-8", timeout=60,
    )
    assert sortie.returncode == 0, sortie.stderr
    return json.loads(sortie.stdout)


def test_camera_non_activee_aucune_photo_et_limite_dite(client, app):
    from iris.lunettes_camera import MESSAGE_CAMERA_NON_CONFIRMEE

    presence = client.get("/api/lunettes/presence").json()
    assert presence["camera_lunettes_active"] is False
    presence["presentes"] = True  # lunettes vues : seule la caméra reste en cause
    decision, message, libelle = _node(
        f"m.decisionDecrire({json.dumps({'ok': True, 'status': 200, 'data': presence})})",
        "m.MESSAGE_CAMERA_NON_CONFIRMEE",
        "m.libelleMenuDecrire(false)",
    )
    assert "decrire" not in decision, "le raccourci demanderait une photo que le service refuse"
    assert MESSAGE_CAMERA_NON_CONFIRMEE in decision["notifier"]["corps"]
    assert "Accessibilité" in decision["notifier"]["corps"]  # où le faire aujourd'hui
    assert message == MESSAGE_CAMERA_NON_CONFIRMEE
    assert "pas encore activée" in libelle and "Ctrl+Maj+D" not in libelle


def test_camera_activee_par_le_service_la_photo_est_demandee(client, app):
    app.state.ctx.settings.update({"lunettes_exploration": True})
    try:
        presence = client.get("/api/lunettes/presence").json()
    finally:
        app.state.ctx.settings.update({"lunettes_exploration": False})
    assert presence["camera_lunettes_active"] is True
    presence["presentes"] = True
    decision, libelle = _node(
        f"m.decisionDecrire({json.dumps({'ok': True, 'status': 200, 'data': presence})})",
        "m.libelleMenuDecrire(true)",
    )
    assert decision == {"decrire": {"mode": "scene", "source": "lunettes"}}
    assert libelle == "Décrire devant moi (Ctrl+Maj+D)"


def test_ordre_des_refus_et_service_ancien():
    # Lunettes absentes : on le dit d'abord, avec le lien d'achat.
    absentes, verrou, injoignable, ancien = _node(
        "m.decisionDecrire({ok: true, status: 200, data: {presentes: false, acheter_url: 'https://exemple.test/a'}})",
        "m.decisionDecrire({ok: false, status: 401, data: {detail: 'IRIS est verrouillée à distance.'}})",
        "m.decisionDecrire({ok: false, status: 0, data: null})",
        "m.decisionDecrire({ok: true, status: 200, data: {presentes: true}})",
    )
    assert absentes["notifier"]["titre"] == "IRIS — lunettes requises"
    assert "https://exemple.test/a" in absentes["notifier"]["corps"]
    # Verrou et présence invérifiable : aucune capture.
    assert "notifier" in verrou and "notifier" in injoignable
    # Service qui ne dit rien de la caméra : pas de photo supposée.
    assert "notifier" in ancien


def test_index_passe_par_la_decision_avant_tout_appel_de_description():
    texte = INDEX_TS.read_text(encoding="utf-8")
    debut = texte.index("async function decrireDevantMoi")
    fin = texte.index("\n}\n", debut)
    corps = texte[debut:fin]
    assert "decisionDecrire(presence)" in corps
    assert corps.index("decisionDecrire(presence)") < corps.index("/api/accessibilite/decrire")
    assert "source: 'lunettes'" not in corps  # la paire vient de la décision, pas d'un littéral qui la contourne
    assert "label: 'Décrire devant moi (Ctrl+Maj+D)'" not in texte
    assert "libelleMenuDecrire(cameraLunettesActive)" in texte


def test_ecran_accessibilite_ne_promet_pas_le_raccourci_sans_camera():
    texte = ACCESSIBILITE_TSX.read_text(encoding="utf-8")
    # La phrase « suit ce choix » n'apparaît plus que sous la condition de la caméra activée.
    lignes = texte.splitlines()
    for i, ligne in enumerate(lignes):
        if ligne.lstrip().startswith("//") or not re.search(r"Ctrl\+Maj\+D[^\n]*suit ce choix|^\s*Ctrl\+Maj\+D suit ce choix", ligne):
            continue
        contexte = "\n".join(lignes[max(0, i - 3):i + 1])
        assert "camera_lunettes_active === true" in contexte, "promesse du raccourci sans condition de caméra"
    assert not re.search(r"Le raccourci\s*\n\s*Ctrl\+Maj\+D suit ce choix\.", texte)
    assert "ne prend aucune photo" in texte
