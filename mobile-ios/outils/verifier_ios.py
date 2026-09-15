"""Vérifications rejouables de l'app iPhone IRIS, SANS Mac ni compilateur Swift.

Ce script ne remplace pas la compilation ni les tests XCTest (IRISTests, à lancer sur un Mac : ⌘U). Il
prouve ce qu'on peut prouver depuis Windows, en relisant le code Swift comme du texte :

1. le protocole des lunettes porté en Swift (TramesLunettes.swift) et les valeurs attendues par
   IRISTests/TramesLunettesTests.swift rendent les MÊMES octets que le service Python
   (backend/iris/lunettes_trames.py, lunettes_camera.py) ;
2. les motifs « mode invité » de l'app (App/CommandesLocales.swift) sont identiques à ceux du service
   (mode_invite.py), et les phrases des tests Swift y sont classées comme le service les classe ;
3. les noms de couleur attendus par les tests Swift sortent bien de l'algorithme de
   AnalyseImageLocale.nomCouleur (porté ici ligne à ligne : c'est une preuve de COHÉRENCE des attentes,
   pas une exécution du Swift) ;
4. les couleurs de texte de Style.swift atteignent le contraste WCAG AA (4,5:1) sur les fonds testés ;
5. chaque route « /api/… » écrite dans le code Swift existe dans le service (main.py, routes_*.py) ;
6. chaque champ des corps de requête Swift (camelCase -> snake_case) existe dans le modèle pydantic de la
   route : FastAPI ignore en silence un champ inconnu (un « parler » mal nommé ferait parler l'ordinateur
   resté à la maison) ;
7. les phrases de refus que l'app reconnaît (IRIS verrouillée, iPhone pas encore associé) sont toujours
   celles du service ;
8. (rédaction de cours en arrière-plan) ;
9. les réponses JSON écrites dans les tests Swift sont REJOUÉES sur le vrai service, en mémoire : session
   révoquée par un effacement à distance (401 efface_a_distance), consentement manquant lu par sondage
   (issue_non_gardee), POST /api/voix/commande (consentement synchrone, refus du micro de la maison), route
   inconnue (404 « Not Found ») ;
10. les correctifs Swift du 2026-09-14 sont branchés là où ils doivent l'être (commande parlée par
   /api/voix/commande, fermeture synchrone du micro de la voix, effacement vu par un 401, sondage des alertes
   en arrière-plan, retrait d'attestation nommé).

Usage : backend/.venv/Scripts/python.exe mobile-ios/outils/verifier_ios.py   (code de sortie 1 si échec)
"""
from __future__ import annotations

import ast
import math
import re
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
IOS = RACINE / "mobile-ios"
APP = IOS / "IRIS"
TESTS = IOS / "IRISTests"
BACKEND = RACINE / "backend"
SERVICE = BACKEND / "iris"

sys.path.insert(0, str(BACKEND))

echecs: list[str] = []
reussites = 0


def verifier(condition: bool, message: str) -> None:
    global reussites
    if condition:
        reussites += 1
    else:
        echecs.append(message)


def lire(chemin: Path) -> str:
    return chemin.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- 1. trames des lunettes
def verifier_trames() -> None:
    from iris import lunettes_camera, lunettes_trames

    swift = lire(APP / "Perception" / "TramesLunettes.swift")
    bloc = re.search(r"static let tramesObservees = \[(.*?)\]", swift, re.S)
    observees = re.findall(r'"([0-9a-f]+)"', bloc.group(1)) if bloc else []
    verifier(len(observees) == 4, "tramesObservees introuvables dans TramesLunettes.swift")
    niveaux = []
    for hexa in observees:
        niveau = lunettes_trames.batterie(bytes.fromhex(hexa))
        verifier(niveau is not None, f"trame observée {hexa} refusée par lunettes_trames.batterie")
        niveaux.append(niveau)

    tests = lire(TESTS / "TramesLunettesTests.swift")
    attendus = re.search(r"let attendus = \[([0-9, ]+)\]", tests)
    verifier(attendus is not None and [int(x) for x in attendus.group(1).split(",")] == niveaux,
             f"niveaux attendus par les tests Swift != service ({niveaux})")

    refaite = lunettes_trames.fabriquer(0x73, bytes([0x05, 86, 0x00])).hex()
    verifier(refaite == observees[0] if observees else False, "fabriquer() ne redonne pas la première trame observée")
    verifier(f'"{refaite}"' in tests, "la trame 0xBC attendue par TramesLunettesTests.swift diffère du service")

    charge = re.search(r"static let chargePhoto: \[UInt8\] = \[([^\]]+)\]", swift)
    octets = bytes(int(x.strip(), 16) for x in charge.group(1).split(",")) if charge else b""
    verifier(octets == lunettes_camera.PAYLOAD_PHOTO, "chargePhoto Swift != PAYLOAD_PHOTO du service")
    type_camera = re.search(r"static let typeCamera: UInt8 = (\d+)", swift)
    verifier(type_camera is not None and int(type_camera.group(1)) == lunettes_camera.TYPE_CAMERA,
             "typeCamera Swift != TYPE_CAMERA du service")
    hypothese = lunettes_camera.fabriquer_trame_camera(lunettes_camera.PAYLOAD_PHOTO).hex()
    verifier(f'"{hypothese}"' in tests, f"trame caméra attendue par les tests Swift != service ({hypothese})")
    crc = lunettes_trames.crc_modbus(bytes([1, 4, 0]))
    verifier(f"0x{crc:04X}" in tests, f"CRC attendu par les tests Swift != service (0x{crc:04X})")
    verifier("static let enteteConfirme = false" in swift,
             "ProtocoleCamera.enteteConfirme a changé : exige une preuve sur le vrai matériel")

    indices = re.search(r"static let indicesNom = \[([^\]]*)\]", swift)
    noms = re.findall(r'"([^"]+)"', indices.group(1)) if indices else []
    verifier(set(noms) == {"vela", "m01", "lunette", "k900"}, f"indicesNom inattendus : {noms}")
    verifier("m01" in "m01 pro_f444", "le nom réel de la paire (M01 Pro_F444) doit rester reconnu")


# --------------------------------------------------------------------------- 2. mode invité
def _motif_swift(source: str, nom: str, politesse: str) -> str:
    bloc = re.search(rf"static let {nom} = try\? NSRegularExpression\(pattern:(.*?)\)\n", source, re.S)
    if not bloc:
        return ""
    morceaux = re.findall(r'"((?:[^"\\]|\\.)*)"|\b(politesse)\b', bloc.group(1))
    return "".join(politesse if ident else litteral for litteral, ident in morceaux)


def verifier_mode_invite() -> None:
    from iris import mode_invite

    swift = lire(APP / "App" / "CommandesLocales.swift")
    politesse = re.search(r'static let politesse = "([^"]+)"', swift)
    politesse_txt = politesse.group(1) if politesse else ""
    activer = _motif_swift(swift, "motifActiver", politesse_txt)
    quitter = _motif_swift(swift, "motifQuitter", politesse_txt)
    verifier(activer == mode_invite._ACTIVER.pattern, f"motif Swift d'activation != service :\n  {activer}\n  {mode_invite._ACTIVER.pattern}")
    verifier(quitter == mode_invite._DESACTIVER.pattern, f"motif Swift de sortie != service :\n  {quitter}\n  {mode_invite._DESACTIVER.pattern}")

    tests = lire(TESTS / "VoixEtCommandesTests.swift")
    for phrase, attendu in re.findall(r'CommandesLocales\.reconnaitre\("((?:[^"\\]|\\.)*)"\)(?:, \.(\w+)\))?', tests):
        norme = mode_invite._normaliser(phrase)
        if mode_invite._DESACTIVER.match(norme):
            service = "quitterModeInvite"
        elif mode_invite._ACTIVER.match(norme):
            service = "activerModeInvite"
        else:
            service = ""
        verifier(service == attendu, f"« {phrase} » : test Swift attend {attendu or 'nil'}, le service classe {service or 'nil'}")


# --------------------------------------------------------------------------- 3. couleurs
def nom_couleur(r: float, v: float, b: float) -> str:
    """Portage ligne à ligne de AnalyseImageLocale.nomCouleur (Swift)."""
    maxi, mini = max(r, v, b), min(r, v, b)
    lum = (maxi + mini) / 2
    delta = maxi - mini
    sat = 0 if delta == 0 else delta / (1 - abs(2 * lum - 1))
    if lum < 0.12:
        return "noir"
    if sat < 0.15:
        if lum > 0.88:
            return "blanc"
        if lum > 0.65:
            return "gris clair"
        if lum < 0.3:
            return "gris foncé"
        return "gris"
    if delta == 0:
        teinte = 0.0
    elif maxi == r:
        teinte = 60 * math.fmod((v - b) / delta, 6)
    elif maxi == v:
        teinte = 60 * ((b - r) / delta + 2)
    else:
        teinte = 60 * ((r - v) / delta + 4)
    if teinte < 0:
        teinte += 360
    if 15 <= teinte < 45 and lum < 0.4:
        return "brun"
    if 20 <= teinte < 50 and sat < 0.5 and lum > 0.7:
        return "beige"
    if teinte < 15 or 345 <= teinte < 360:
        base = "rose" if lum > 0.7 else "rouge"
    elif teinte < 40:
        base = "orange"
    elif teinte < 68:
        base = "jaune"
    elif teinte < 165:
        base = "vert"
    elif teinte < 195:
        base = "turquoise"
    elif teinte < 255:
        base = "bleu"
    elif teinte < 310:
        base = "violet"
    else:
        base = "rose" if lum > 0.6 else "magenta"
    if base == "rose":
        return base
    if lum < 0.3:
        return f"{base} foncé"
    if lum > 0.72:
        return f"{base} clair"
    return base


def verifier_couleurs() -> None:
    swift = lire(APP / "Perception" / "AnalyseImageLocale.swift")
    verifier('base = luminosite > 0.7 ? "rose" : "rouge"' in swift and "case 195..<255:" in swift,
             "AnalyseImageLocale.nomCouleur a changé : mettre à jour le portage de ce script")
    tests = lire(TESTS / "PerceptionEtConfianceTests.swift")
    cas = re.findall(r'nomCouleur\(r: ([\d.]+), v: ([\d.]+), b: ([\d.]+)\), "([^"]+)"\)', tests)
    verifier(len(cas) >= 8, "cas de couleur introuvables dans les tests Swift")
    for r, v, b, attendu in cas:
        obtenu = nom_couleur(float(r), float(v), float(b))
        verifier(obtenu == attendu, f"nomCouleur({r}, {v}, {b}) : test Swift attend « {attendu} », l'algorithme rend « {obtenu} »")


# --------------------------------------------------------------------------- 4. contrastes
def _luminance(rgb: int) -> float:
    def canal(decalage: int) -> float:
        c = ((rgb >> decalage) & 0xFF) / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * canal(16) + 0.7152 * canal(8) + 0.0722 * canal(0)


def contraste(a: int, b: int) -> float:
    la, lb = _luminance(a), _luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def verifier_contrastes() -> None:
    swift = lire(APP / "Partage" / "Style.swift")
    palette = {nom: int(valeur, 16) for nom, valeur in
               re.findall(r"static let (\w+): UInt32 = 0x([0-9A-Fa-f]{6})", swift)}
    for texte, fond in (("attenue", "carte"), ("attenue", "fond"), ("attenue", "fond2"), ("texte2", "carte2")):
        if texte not in palette or fond not in palette:
            verifier(False, f"PaletteRGB.{texte} ou .{fond} introuvable dans Style.swift")
            continue
        ratio = contraste(palette[texte], palette[fond])
        verifier(ratio >= 4.5, f"contraste {texte} sur {fond} = {ratio:.2f}:1 < 4,5:1 (WCAG AA)")


# --------------------------------------------------------------------------- 5. routes
def _routes_service() -> set[str]:
    routes: set[str] = set()
    for fichier in SERVICE.glob("*.py"):
        for chemin in re.findall(r'@(?:app|routeur|router)\.(?:get|post|put|patch|delete|api_route)\(\s*"(/api/[^"]+)"', lire(fichier)):
            routes.add(re.sub(r"\{[^}]+\}", "{}", chemin))
    return routes


def verifier_routes() -> None:
    service = _routes_service()
    verifier(len(service) > 50, "routes du service introuvables")
    vues: set[str] = set()
    for fichier in APP.rglob("*.swift"):
        for litteral in re.findall(r'"(/api/(?:[^"\\]|\\\([^)]*\))*)"', lire(fichier)):
            chemin = re.sub(r"\\\([^)]*\)", "{}", litteral).rstrip("/")
            vues.add(chemin)
            verifier(chemin in service, f"{fichier.relative_to(IOS)} appelle {chemin}, absent du service")
    verifier(len(vues) > 20, "trop peu de routes trouvées dans le Swift (motif cassé ?)")


# --------------------------------------------------------------------------- 6. corps des requêtes
CORRESPONDANCES = {
    # structure Swift : (fichier du service, modèle pydantic)
    "DemandeDescription": ("routes_accessibilite.py", "DecrireIn"),
    "DemandeTraduction": ("routes_interprete.py", "TexteIn"),
    "DemandeAnalyseRecu": ("routes_quotidien.py", "AnalyserIn"),
    "DemandePasAPas": ("routes_assistants.py", "PasAPasDemarrerIn"),
    "CommandePasAPas": ("routes_assistants.py", "PasAPasCommandeIn"),
    "DemandeEntrainement": ("routes_assistants.py", "EntrainementDemarrerIn"),
    "CommandeEntrainement": ("routes_assistants.py", "EntrainementCommandeIn"),
    "DemandeComparaison": ("routes_assistants.py", "ComparerIn"),
    "DemandeInvite": ("routes_confiance.py", "InviteIn"),
    "NouvelleZone": ("routes_confiance.py", "ZoneIn"),
    "SignalZone": ("routes_confiance.py", "ZoneSignaleeIn"),
    "DemandeDeverrouillage": ("routes_confiance.py", "MotDePasseIn"),
    "EnvoiMessage": ("main.py", "MessageIn"),
    "ReponseConfirmation": ("main.py", "ConfirmIn"),
    "NouvelleConversation": ("main.py", "ConversationCreate"),
    "DemandeAttestation": ("main.py", "AttestationLunettesIn"),
    "DemandeAssociation": ("main.py", "AssociationLunettesIn"),
    "DemandeCommandeVocale": ("main.py", "CommandeVocaleIn"),
}


def _snake(nom: str) -> str:
    return re.sub(r"(?<=[a-z0-9])([A-Z])", r"_\1", nom).lower()


def _champs_pydantic(fichier: str, classe: str) -> set[str] | None:
    arbre = ast.parse(lire(SERVICE / fichier))
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.ClassDef) and noeud.name == classe:
            return {c.target.id for c in noeud.body if isinstance(c, ast.AnnAssign) and isinstance(c.target, ast.Name)}
    return None


def _champs_swift(nom: str) -> set[str] | None:
    for fichier in APP.rglob("*.swift"):
        bloc = re.search(rf"struct {nom}: [^{{]*\{{(.*?)\n\}}", lire(fichier), re.S)
        if bloc:
            return {_snake(c) for c in re.findall(r"^\s*(?:let|var) (\w+):", bloc.group(1), re.M)}
    return None


def verifier_corps() -> None:
    for swift, (fichier, classe) in CORRESPONDANCES.items():
        champs_swift = _champs_swift(swift)
        champs_service = _champs_pydantic(fichier, classe)
        if champs_swift is None or champs_service is None:
            verifier(False, f"{swift} ou {fichier}:{classe} introuvable")
            continue
        inconnus = champs_swift - champs_service
        verifier(not inconnus, f"{swift} envoie {sorted(inconnus)} que {classe} ({fichier}) ignore en silence")


# --------------------------------------------------------------------------- 7. phrases du service reconnues
def verifier_phrases_service() -> None:
    """L'app reconnaît deux refus du service à leur phrase : si la phrase change côté ordinateur, l'écran de
    verrouillage ou l'association de l'iPhone cesseraient de s'afficher en silence."""
    from iris import lunettes_presence

    attestation = lire(APP / "Pont" / "AttestationLunettes.swift")
    motif = re.search(r'localizedCaseInsensitiveContains\("([^"]+)"\)', attestation)
    verifier(motif is not None and motif.group(1).lower() in lunettes_presence.MESSAGE_APPAREIL_NON_ASSOCIE.lower(),
             "AttestationLunettes ne reconnaît plus MESSAGE_APPAREIL_NON_ASSOCIE du service")
    verifier(motif is not None and motif.group(1).lower() not in lunettes_presence.MESSAGE_AUTRES_LUNETTES.lower(),
             "le motif d'association attrape aussi MESSAGE_AUTRES_LUNETTES")
    tests = lire(TESTS / "PontTests.swift")
    verifier(lunettes_presence.MESSAGE_APPAREIL_NON_ASSOCIE.replace("’", "'") in tests,
             "PontTests.swift ne reprend plus la phrase exacte MESSAGE_APPAREIL_NON_ASSOCIE")
    verifier(lunettes_presence.MESSAGE_AUTRES_LUNETTES in tests,
             "PontTests.swift ne reprend plus la phrase exacte MESSAGE_AUTRES_LUNETTES")

    main_py = lire(SERVICE / "main.py")
    for phrase in re.findall(r'return "(IRIS est verrouillée[^"]*)"', main_py):
        verifier("verrouill" in phrase.lower(), f"refus de verrou sans « verrouill » : {phrase}")
    verifier(len(re.findall(r'return "(IRIS est verrouillée[^"]*)"', main_py)) >= 2,
             "phrases de verrou introuvables dans main.py (raison_de_refus)")


# --------------------------------------------------------------------------- 8. rédaction de cours en arrière-plan
def verifier_generation_cours() -> None:
    """Un long cours répond 202 {en_arriere_plan, phrase} : l'app ne doit pas le prendre pour une fin de rédaction
    (demande de la revue service-a, 2026-09-14), et lit « erreur_generation » du cours."""
    cours_py = lire(SERVICE / "cours.py")
    ecran = lire(APP / "Ecrans" / "Cours" / "EcranCours.swift")
    contrats = lire(APP / "Partage" / "Contrats.swift")
    verifier('"en_arriere_plan": True' in cours_py and '"phrase"' in cours_py and '"erreur_generation"' in cours_py,
             "cours.py ne rend plus en_arriere_plan / phrase / erreur_generation")
    verifier("let enArrierePlan: Bool?" in ecran and "let phrase: String?" in ecran,
             "EcranCours.swift ne décode pas la réponse 202 de /generer")
    verifier("let _: ReponseIgnoree = try await env.pont.post(\"/api/cours/" not in ecran,
             "EcranCours.swift ignore encore la réponse de /generer")
    verifier("let erreurGeneration: String?" in contrats, "CoursDetail (Contrats.swift) ne lit pas erreur_generation")


# --------------------------------------------------------------------------- 9. réponses rejouées sur le service
def _json_du_test(source: str, fonction: str, indice: int = 0) -> dict:
    """Le indice-ième littéral JSON brut (#"{…}"#) écrit dans la fonction de test Swift nommée."""
    import json

    corps = re.search(rf"func {fonction}\(\)[^{{]*\{{(.*?)\n    }}\n", source, re.S)
    if not corps:
        raise AssertionError(f"test Swift {fonction} introuvable")
    litteraux = re.findall(r'#"(\{.*?\})"#', corps.group(1))
    return json.loads(litteraux[indice])


def _champs_swift_snake(nom: str) -> set[str]:
    champs = _champs_swift(nom)
    if champs is None:
        raise AssertionError(f"structure Swift {nom} introuvable")
    return champs


def verifier_reponses_rejouees() -> None:
    import asyncio
    import tempfile
    import time

    from fastapi.testclient import TestClient

    import iris.chat as chat_module
    import iris.comptes as comptes_module
    from iris import lunettes_presence
    from iris import main as main_module
    from iris.connectors.base import BaseConnector, Chunk
    from iris.main import create_app

    pont_tests = lire(TESTS / "PontTests.swift")
    voix_tests = lire(TESTS / "VoixEtCommandesTests.swift")
    pont_swift = lire(APP / "Pont" / "ClientPontPC.swift")

    # Le code du 401 lu par l'app est celui du service.
    code = re.search(r'static let codeEffaceADistance = "([^"]+)"', pont_swift)
    verifier(code is not None and code.group(1) == main_module.CODE_EFFACE_A_DISTANCE,
             "ClientPontPC.codeEffaceADistance != main.CODE_EFFACE_A_DISTANCE")
    # Refus d'association : le service lève un detail en OBJET ; le test Swift rejoue cette forme exacte.
    verifier('{"code": "appareil_non_associe", "message": MESSAGE_APPAREIL_NON_ASSOCIE}' in lire(SERVICE / "lunettes_presence.py"),
             "lunettes_presence.attester ne lève plus detail {code: appareil_non_associe, message}")
    attendu = {"detail": {"code": "appareil_non_associe",
                          "message": lunettes_presence.MESSAGE_APPAREIL_NON_ASSOCIE.replace("’", "'")}}
    verifier(_json_du_test(pont_tests, "testAppareilNonAssocieAvecDetailEnObjet") == attendu,
             "PontTests.testAppareilNonAssocieAvecDetailEnObjet ne rejoue pas la réponse exacte du service")

    class MoteurMuet(BaseConnector):
        name = "claude"
        supports_tools = False

        def __init__(self, api_key=None, model="faux", base_url=None):
            super().__init__(api_key, model, base_url)

        async def stream(self, messages, system, tools=None, run_tool=None, options=None):
            yield Chunk("text", text="Réponse.")
            yield Chunk("done")

        async def test(self):
            return {"ok": True, "message": "ok", "model": self.model, "latency_ms": 1}

    ancien_connecteur, anciennes_iterations = chat_module.build_connector, comptes_module.ITERATIONS
    chat_module.build_connector = lambda name, settings, secrets: MoteurMuet()
    comptes_module.ITERATIONS = 2_000
    dossier = Path(tempfile.mkdtemp(prefix="verifier-ios-")) / "data"
    dossier.mkdir(parents=True)
    app = create_app(data_dir=dossier, token="test-token", use_keyring=False, enable_tts=False)
    ctx = app.state.ctx
    try:
        with TestClient(app, headers={"Authorization": "Bearer test-token"}) as c:
            # Route inconnue d'un ordinateur ancien : la 404 que l'app prend pour « pas de /api/voix/commande ».
            inconnue = c.post("/api/route-qui-n-existe-pas", json={})
            verifier(inconnue.status_code == 404 and inconnue.json() == {"detail": "Not Found"},
                     f"404 d'une route inconnue inattendue : {inconnue.status_code} {inconnue.text}")
            verifier('#"{"detail":"Not Found"}"#' in voix_tests, "le test Swift du repli ne rejoue plus {detail: Not Found}")

            # Consentement manquant, liaison fermée : issue_non_gardee lue par sondage.
            c.put("/api/agents/claude", json={"active": True, "api_key": "cle-factice-test"})
            conv = c.post("/api/conversations", json={}).json()
            c.post(f"/api/conversations/{conv['id']}/messages", json={"text": "salut", "agent": "auto", "images": []})
            corps: dict = {}
            fin = time.monotonic() + 15
            while time.monotonic() < fin:
                corps = c.get(f"/api/conversations/{conv['id']}").json()
                if corps.get("issue_non_gardee"):
                    break
                time.sleep(0.1)
            reelle = corps.get("issue_non_gardee") or {}
            fixture = _json_du_test(voix_tests, "testConsentementLuParSondageQuandLEvenementEstPerdu")
            verifier(bool(reelle), "GET /api/conversations/{id} ne rend pas issue_non_gardee après un consentement manquant")
            verifier(set(reelle) == set(fixture["issue_non_gardee"]),
                     f"clés issue_non_gardee : service {sorted(reelle)} != test Swift {sorted(fixture['issue_non_gardee'])}")
            verifier(set(reelle.get("consentement") or {}) == set(fixture["issue_non_gardee"]["consentement"]),
                     "clés de issue_non_gardee.consentement : service != test Swift")
            verifier((reelle.get("consentement") or {}).get("label") == fixture["issue_non_gardee"]["consentement"]["label"],
                     f"libellé du consentement : service {reelle.get('consentement')} != test Swift")
            utilisateur = [m for m in corps.get("messages", []) if m["role"] == "user"]
            verifier(bool(utilisateur) and reelle.get("apres") == utilisateur[-1]["id"],
                     "issue_non_gardee.apres ne nomme pas le message de l'utilisateur")
            verifier({"apres", "message", "consentement"} <= _champs_swift_snake("IssueNonGardee"),
                     "IssueNonGardee (Swift) ne lit pas apres / message / consentement")

            # POST /api/voix/commande, lunettes attestées par l'iPhone, consentement manquant : réponse synchrone.
            ctx.settings.update({"require_glasses": True, "demo_sans_lunettes": False,
                                 "glasses": {"name": "M01 Pro_F444", "address": "65:A2:9F:5C:F4:44", "auto_connect": False}})
            ctx.voice.lunettes_presentes = lambda: False
            r = c.post("/api/lunettes/attestation", json={"nom": "M01 Pro_F444", "identifiant": "ios-1", "source": "iphone"})
            verifier(r.status_code == 200, f"attestation de l'iPhone refusée : {r.text}")
            r = c.post("/api/voix/commande", json={"texte": "raconte-moi une histoire", "source": "iphone",
                                                   "conversation_id": conv["id"]})
            reelle = r.json() if r.status_code == 200 else {}
            fixture = _json_du_test(voix_tests, "testConsentementRequisSynchrone")
            verifier(r.status_code == 200 and reelle.get("consentement_requis") == "transcript",
                     f"/api/voix/commande ne rend pas consentement_requis : {r.status_code} {r.text}")
            verifier(set(reelle) == set(fixture), f"clés /api/voix/commande : service {sorted(reelle)} != test Swift {sorted(fixture)}")
            verifier(reelle.get("texte") == fixture.get("texte"), "phrase du consentement : service != test Swift")
            inconnus = set(fixture) - _champs_swift_snake("ReponseCommandeVocale")
            verifier(not inconnus, f"ReponseCommandeVocale (Swift) ne lit pas {sorted(inconnus)}")
            refus = c.post("/api/voix/commande", json={"texte": "mode interprète anglais", "source": "iphone"}).json()
            fixture_refus = _json_du_test(voix_tests, "testRefusDuMicroDeLaMaison")
            verifier(refus.get("refus") == fixture_refus["refus"] and refus.get("texte") == fixture_refus["texte"],
                     f"refus du micro de la maison : service {refus} != test Swift")

            # Effacement à distance vu par une session de téléphone qui n'a pas reçu verrou.etat.
            ctx.comptes.creer("MotDePasse-Tres-Long-123!", "Miguel")
            session = ctx.comptes.ouvrir_session()
            entete = {"Authorization": f"Bearer {session}"}
            verifier(c.get("/api/status", headers=entete).status_code == 200, "session de téléphone refusée avant l'effacement")
            asyncio.run(ctx.verrou.effacer())
            r = c.get("/api/status", headers=entete)
            verifier(r.status_code == 401, f"/api/status après effacement : {r.status_code}")
            verifier(r.json() == _json_du_test(pont_tests, "testSessionRevoqueeParUnEffacementADistance"),
                     f"401 après effacement : service {r.json()} != test Swift")
            # Finition B : déverrouillage puis « Déconnecter tous les appareils » avant la réouverture du téléphone.
            verifier(c.post("/api/confiance/deverrouiller", json={"mot_de_passe": "MotDePasse-Tres-Long-123!"}).status_code == 200,
                     "déverrouillage après effacement refusé")
            verifier(c.post("/api/compte/deconnexion").status_code == 200, "déconnexion de tous les appareils refusée")
            r = c.get("/api/status", headers=entete)
            verifier(r.status_code == 401 and r.json() == _json_du_test(pont_tests, "testEffacementVuApresDeconnexionDeTousLesAppareils"),
                     f"401 après effacement puis déconnexion de tous les appareils : service {r.status_code} {r.json()} != test Swift")
    finally:
        chat_module.build_connector = ancien_connecteur
        comptes_module.ITERATIONS = anciennes_iterations
        ctx.close()


# --------------------------------------------------------------------------- 10. correctifs branchés
def _corps_fonction(source: str, signature: str) -> str:
    debut = source.find(signature)
    if debut < 0:
        return ""
    fin = source.find("\n    }\n", debut)
    return source[debut:fin if fin > 0 else len(source)]


def verifier_branchements_2026_09_14() -> None:
    env = lire(APP / "App" / "EnvironnementIRIS.swift")
    conversation = lire(APP / "IA" / "ConversationIRIS.swift")
    moteur = lire(APP / "Voix" / "MoteurVoix.swift")
    micro = lire(APP / "Perception" / "MicroPerception.swift")
    alertes = lire(APP / "Perception" / "AlertesSonores.swift")
    pont = lire(APP / "Pont" / "ClientPontPC.swift")

    # Constats 1 et 3 : la commande PARLÉE passe par /api/voix/commande, le chat écrit seulement en repli.
    sur_commande = re.search(r"voix\.surCommande = \{(.*?)\n        \}", env, re.S)
    verifier(sur_commande is not None and "demanderAVoix(" in sur_commande.group(1) and ".demander(" not in sur_commande.group(1),
             "voix.surCommande n'appelle pas demanderAVoix")
    a_voix = _corps_fonction(env, "func demanderAVoix(")
    verifier("envoyerCommandeVocale(" in a_voix and "case .routeAbsente" in a_voix and "demander(texte)" in a_voix,
             "demanderAVoix ne se replie pas sur demander() quand la route manque")
    for ecran in ("Ecrans/Accueil/EcranAccueil.swift", "Ecrans/IA/EcranIA.swift"):
        verifier("env.demander(phrase)" not in lire(APP / ecran), f"{ecran} envoie encore une phrase DICTÉE par le chemin écrit")
    vocale = _corps_fonction(conversation, "func envoyerCommandeVocale(")
    verifier('"/api/voix/commande"' in vocale and 'source: "iphone"' in vocale and "routeVocaleAbsente(error)" in vocale,
             "envoyerCommandeVocale n'appelle pas /api/voix/commande (source iphone) avec repli sur 404")
    verifier("/messages" not in vocale, "envoyerCommandeVocale passe encore par le chat écrit")

    # Constat 8 : le sondage lit issue_non_gardee.
    verifier("phraseIssueNonGardee(conv.issueNonGardee, connus: attente.connus)" in conversation,
             "le sondage de la conversation ne lit pas issue_non_gardee")

    # Micro : la pause ferme la reconnaissance TOUT DE SUITE, écoute dirigée comprise.
    pause = _corps_fonction(moteur, "func suspendreVeille(")
    i_conclure = pause.find("attente.conclure(")
    i_fermer = pause.find("fermerReconnaissance()")
    verifier(i_conclure >= 0 and i_fermer > i_conclure and "return" not in pause[i_conclure:i_fermer],
             "suspendreVeille rend la main sans fermer la reconnaissance quand une écoute dirigée tourne")
    verifier("fermerMicroAuSuspens(ecouteDirigee: ecouteDirigee, etat: etat)" in pause,
             "suspendreVeille n'utilise pas la décision testée fermerMicroAuSuspens")
    demarrage = _corps_fonction(micro, "private func demarrerMoteur()")
    positions = [demarrage.find(x) for x in ("suspendreMotActivation()", "MoteurVoix.voixTientLeMicro(voix.etat)",
                                             "installerEtLancer()")]
    verifier(-1 not in positions and positions == sorted(positions),
             "MicroPerception ne refuse pas de démarrer tant que la voix tient le micro")

    # Constat 12 / nouveau 1 : effacement vu par un 401.
    classer = _corps_fonction(pont, "nonisolated static func classerRefus(")
    branche = re.search(r"\n\s*if code == Self\.codeEffaceADistance \{\s*return \(\.verrouillee\(Self\.raisonEffacement\), \.effacement\)",
                        classer)
    verifier(branche is not None and branche.start() < classer.find('"verrouill"'),
             "classerRefus ne reconnaît pas le code efface_a_distance avant la phrase « verrouillée »")
    traduire = _corps_fonction(pont, "private func traduireRefus(")
    bloc = traduire[traduire.find("case .effacement:"):traduire.find("case .oublierSession:")]
    verifier(all(x in bloc for x in ("Trousseau.effacer", "poserVerrou(Self.raisonEffacement)", "surEffacementDistant?()")),
             "traduireRefus(.effacement) n'oublie pas la session, ne pose pas le verrou ou ne retire pas les copies")

    # Nouveau 2 : alertes en arrière-plan.
    veilleur = _corps_fonction(alertes, "private func demarrerVeilleur()")
    verifier("doitSonderArrierePlan(" in veilleur and "sonderEnArrierePlan()" in veilleur,
             "le veilleur des alertes ne sonde pas l'ordinateur en arrière-plan")
    sonde = _corps_fonction(alertes, "private func sonderEnArrierePlan()")
    verifier('"/api/settings"' in sonde and "GardeCapture.messageConfidentiel" in sonde and "GardeCapture.messageVerrou" in sonde,
             "sonderEnArrierePlan n'arrête pas les alertes sur mode confidentiel / verrou")
    verifier("En arrière-plan, l'iPhone redemande à ton ordinateur" in alertes, "la limite du sondage en arrière-plan n'est pas dite")

    # Mineur : le retrait de l'attestation nomme cet appareil.
    attestation = lire(APP / "Pont" / "AttestationLunettes.swift")
    verifier(re.search(r'pont\.delete\(\s*"/api/lunettes/attestation",\s*parametres: Self\.parametresRetrait\(', attestation) is not None,
             "DELETE /api/lunettes/attestation envoyé sans ?identifiant=")


def main() -> int:
    for etape in (verifier_trames, verifier_mode_invite, verifier_couleurs, verifier_contrastes, verifier_routes,
                  verifier_corps, verifier_phrases_service, verifier_generation_cours, verifier_reponses_rejouees,
                  verifier_branchements_2026_09_14):
        try:
            etape()
        except Exception as exc:  # une étape cassée ne cache pas les autres
            echecs.append(f"{etape.__name__} : {exc!r}")
    for message in echecs:
        print("ÉCHEC :", message)
    print(f"{reussites} vérifications réussies, {len(echecs)} échec(s).")
    return 1 if echecs else 0


if __name__ == "__main__":
    sys.exit(main())
