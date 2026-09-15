"""Bouton des lunettes -> description (interface D, chantier du 2026-09-13).

Paquets Bluetooth basse énergie synthétiques, faux service de description, faux bus : aucun
Bluetooth, aucune caméra, aucun moteur.

Ce qui est protégé ici, pour une personne aveugle qui appuie sur un bouton au lieu de sortir son
téléphone :
- le bouton appris est celui qui apparaît pendant l'appui, pas la batterie ni un battement ;
- quand les lunettes n'émettent rien, l'échec est dit tel quel, sans signature inventée ;
- un appui déclenche UNE description (anti-rebond de 3 s), avec le mode choisi, et sa voix ;
- un refus (consentement, caméra) est dit à voix haute ; le mode confidentiel ne photographie rien ;
- la chaîne réelle glasses._on_notify -> bus -> apprentissage -> déclenchement fonctionne par la route.
"""
from __future__ import annotations

import asyncio
import threading
import time
import types
from collections import Counter

from fastapi import HTTPException

from iris import bouton_lunettes as bl
from iris import lunettes_trames
from iris.config import Settings

BOUTON = "0000ae02-0000-1000-8000-00805f9b34fb"
COMMANDE = "de5bf72a-d711-4e47-af26-65e3012a5dc7"
BATTERIE = lunettes_trames.fabriquer(0x73, bytes([0x05, 84, 0x00])).hex()


def paquet(uuid: str, hexa: str) -> dict:
    return {"type": "glasses.packet", "ts": "2026-09-13T12:00:00+00:00", "uuid": uuid, "hex": hexa, "len": len(hexa) // 2}


class Bus:
    def __init__(self):
        self.evenements: list[dict] = []

    def publish(self, type_, **donnees):
        self.evenements.append({"type": type_, **donnees})
        return {}

    def de_type(self, type_):
        return [e for e in self.evenements if e["type"] == type_]


class FauxAccessibilite:
    def __init__(self, erreur: Exception | None = None):
        self.appels: list[dict] = []
        self.erreur = erreur

    async def decrire(self, **options):
        self.appels.append(options)
        if self.erreur is not None:
            raise self.erreur
        return {"ok": True, "texte": "Une table."}


def attendre(condition, delai: float = 3.0) -> bool:
    """La voix du bouton part dans son propre fil (jamais dans la boucle asyncio) : on attend qu'elle passe."""
    fin = time.monotonic() + delai
    while time.monotonic() < fin:
        if condition():
            return True
        time.sleep(0.01)
    return condition()


def faux_contexte(tmp_path, connectees: bool = True, accessibilite=None, **reglages):
    settings = Settings(tmp_path / "donnees")
    settings.update(reglages)
    dits: list[str] = []
    ctx = types.SimpleNamespace(
        settings=settings, hub=Bus(),
        glasses=types.SimpleNamespace(connected=connectees),
        tts=types.SimpleNamespace(speak=lambda texte, force=False: dits.append(texte) or True),
    )
    if accessibilite is not None:
        ctx.accessibilite = accessibilite
    return ctx, dits


# --------------------------------------------------------------------------- choix de la signature
def test_la_signature_retenue_est_nouvelle_ni_batterie_ni_battement():
    reference = Counter({f"{COMMANDE}:{BATTERIE}": 1, f"{BOUTON}:aa": 2})
    appui = Counter()
    for sig in (f"{BOUTON}:aa", f"{COMMANDE}:{BATTERIE}", f"{COMMANDE}:{lunettes_trames.fabriquer(0x73, bytes([5, 83, 0])).hex()}",
                f"{BOUTON}:07", f"{BOUTON}:07", f"{BOUTON}:07",  # un octet répété : un battement
                f"{BOUTON}:0a0101", f"{BOUTON}:0a0101", f"{BOUTON}:0b"):
        appui[sig] += 1
    assert bl.choisir_signature(reference, appui) == f"{BOUTON}:0a0101"
    assert bl.choisir_signature(reference, Counter({f"{BOUTON}:aa": 3})) is None


# --------------------------------------------------------------------------- apprentissage
async def _apprendre_avec(service, ctx, pendant_reference: list[dict], pendant_appui: list[dict]):
    async def injecter():
        for p in pendant_reference:
            service.recevoir_paquet(p)
        while not any(e.get("etat") == "appuyez" for e in ctx.hub.de_type("bouton.apprentissage")):
            await asyncio.sleep(0.01)
        for p in pendant_appui:
            service.recevoir_paquet(p)

    tache = asyncio.create_task(injecter())
    resultat = await service.apprendre(secondes=0.3, reference_s=0.15)
    await tache
    return resultat


def test_le_bouton_est_appris_et_enregistre(tmp_path, monkeypatch):
    monkeypatch.setattr(bl, "APPUI_MIN_S", 0.1)
    ctx, dits = faux_contexte(tmp_path)
    service = bl.ServiceBouton(ctx)
    resultat = asyncio.run(_apprendre_avec(
        service, ctx,
        [paquet(COMMANDE, BATTERIE), paquet(BOUTON, "aa")],
        [paquet(COMMANDE, BATTERIE), paquet(BOUTON, "aa"), paquet(BOUTON, "0a0101"), paquet(BOUTON, "0a0101")],
    ))
    assert resultat["etat"] == "appris" and resultat["signature"] == f"{BOUTON}:0a0101"
    assert ctx.settings.user.bouton_description_signature == f"{BOUTON}:0a0101"
    assert [e["etat"] for e in ctx.hub.de_type("bouton.apprentissage")] == ["reference", "appuyez", "appris"]
    assert ctx.hub.de_type("settings.updated")
    assert attendre(lambda: "Bouton appris." in dits)
    assert dits.index("Appuyez maintenant sur le bouton des lunettes, deux ou trois fois.") < dits.index("Bouton appris.")
    assert service.etat()["apprentissage"] is False


def test_rien_de_nouveau_echec_honnete(tmp_path, monkeypatch):
    monkeypatch.setattr(bl, "APPUI_MIN_S", 0.1)
    ctx, dits = faux_contexte(tmp_path)
    service = bl.ServiceBouton(ctx)
    resultat = asyncio.run(_apprendre_avec(service, ctx, [paquet(COMMANDE, BATTERIE)], [paquet(COMMANDE, BATTERIE)]))
    assert resultat["etat"] == "echec" and resultat["signature"] is None
    assert "n'émettent rien sur le canal Bluetooth basse énergie pour ce bouton" in resultat["raison"]
    assert ctx.settings.user.bouton_description_signature == ""
    assert ctx.hub.de_type("bouton.apprentissage")[-1]["etat"] == "echec"
    assert attendre(lambda: bool(dits) and dits[-1] == resultat["raison"])


def test_lunettes_non_connectees_ou_mode_confidentiel_echec_immediat(tmp_path):
    ctx, _dits = faux_contexte(tmp_path, connectees=False)
    debut = time.monotonic()
    resultat = asyncio.run(bl.ServiceBouton(ctx).apprendre(secondes=6))
    assert resultat["etat"] == "echec" and "pas connectées" in resultat["raison"]
    ctx2, _dits2 = faux_contexte(tmp_path / "b", privacy_mode=True)
    resultat = asyncio.run(bl.ServiceBouton(ctx2).apprendre(secondes=6))
    assert resultat["etat"] == "echec" and "confidentiel" in resultat["raison"]
    assert time.monotonic() - debut < 1.0


# --------------------------------------------------------------------------- déclenchement
def test_un_appui_declenche_une_seule_description_avec_le_mode_choisi(tmp_path, monkeypatch):
    acc = FauxAccessibilite()
    ctx, _dits = faux_contexte(tmp_path, accessibilite=acc, bouton_description_signature=f"{BOUTON}:0a0101",
                               bouton_description_mode="lecture")
    service = bl.ServiceBouton(ctx)
    horloge = [1000.0]
    monkeypatch.setattr(bl, "_horloge", lambda: horloge[0])

    async def scenario():
        service.recevoir_paquet(paquet(BOUTON, "0a0101"))
        service.recevoir_paquet(paquet(BOUTON, "0a0101"))  # même appui, deuxième paquet : ignoré
        service.recevoir_paquet(paquet(COMMANDE, BATTERIE))  # autre paquet : ignoré
        await asyncio.sleep(0.05)
        horloge[0] += bl.ANTI_REBOND_S + 0.1
        service.recevoir_paquet(paquet(BOUTON.upper(), "0A0101"))  # la casse ne compte pas
        await asyncio.sleep(0.05)

    asyncio.run(scenario())
    assert acc.appels == [{"mode": "lecture", "source": "lunettes", "parler": True}] * 2
    assert [e["action"] for e in ctx.hub.de_type("bouton.lunettes")] == ["decrire", "decrire"]


def test_un_refus_de_description_est_dit_a_voix_haute(tmp_path):
    refus = HTTPException(403, detail={"code": "consentement", "data_type": "image", "label": "Images jointes"})
    acc = FauxAccessibilite(erreur=refus)
    ctx, dits = faux_contexte(tmp_path, accessibilite=acc, bouton_description_signature=f"{BOUTON}:0a0101")

    async def scenario():
        bl.ServiceBouton(ctx).recevoir_paquet(paquet(BOUTON, "0a0101"))
        await asyncio.sleep(0.05)

    asyncio.run(scenario())
    evenement = ctx.hub.de_type("bouton.lunettes")[-1]
    assert evenement["action"] == "erreur" and "Images jointes" in evenement["raison"]
    assert attendre(lambda: bool(dits) and "consentement" in dits[-1])


def test_mode_confidentiel_et_description_absente(tmp_path):
    acc = FauxAccessibilite()
    ctx, dits = faux_contexte(tmp_path, accessibilite=acc, bouton_description_signature=f"{BOUTON}:01", privacy_mode=True)
    bl.ServiceBouton(ctx).recevoir_paquet(paquet(BOUTON, "01"))
    assert acc.appels == [] and ctx.hub.de_type("bouton.lunettes")[-1]["action"] == "refuse" and dits == []
    ctx2, dits2 = faux_contexte(tmp_path / "b", bouton_description_signature=f"{BOUTON}:01")
    bl.ServiceBouton(ctx2).recevoir_paquet(paquet(BOUTON, "01"))
    assert ctx2.hub.de_type("bouton.lunettes")[-1]["action"] == "indisponible"
    assert attendre(lambda: bool(dits2) and "n'est pas disponible" in dits2[-1])


def test_la_voix_du_bouton_ne_bloque_jamais_la_boucle(tmp_path):
    """Premier démarrage de la voix Windows : speak peut attendre de longues secondes. _dire rend la main
    tout de suite, et les phrases sont dites dans l'ordre."""
    ctx, dits = faux_contexte(tmp_path)

    def speak_lent(texte, force=False):
        time.sleep(1.0)
        dits.append(texte)
        return True

    ctx.tts.speak = speak_lent
    service = bl.ServiceBouton(ctx)
    debut = time.monotonic()
    service._dire("Première.")
    service._dire("Seconde.")
    assert time.monotonic() - debut < 0.5, "deux phrases d'une seconde chacune : _dire ne les attend pas"
    assert attendre(lambda: len(dits) == 2, 8.0) and dits == ["Première.", "Seconde."]


def test_oublier_efface_la_signature(tmp_path):
    ctx, _dits = faux_contexte(tmp_path, bouton_description_signature=f"{BOUTON}:01")
    assert bl.ServiceBouton(ctx).oublier() == {"ok": True}
    assert ctx.settings.user.bouton_description_signature == ""


# --------------------------------------------------------------------------- chaîne réelle par la route
def test_route_apprendre_puis_declencher_par_les_vrais_paquets(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from iris.main import create_app

    app = create_app(data_dir=tmp_path / "iris", token="test-token", use_keyring=False, enable_tts=False)
    ctx = app.state.ctx
    monkeypatch.setattr(bl, "REFERENCE_S", 0.3)
    acc = FauxAccessibilite()
    capteur = types.SimpleNamespace(uuid=BOUTON)
    batterie = types.SimpleNamespace(uuid=COMMANDE)
    try:
        with TestClient(app, headers={"Authorization": "Bearer test-token"}) as client:
            ctx.accessibilite = acc
            ctx.glasses.client = types.SimpleNamespace(is_connected=True)  # lunettes « connectées », sans Bluetooth
            assert client.get("/api/lunettes/bouton").json()["lunettes_connectees"] is True

            def appuyer():
                ctx.glasses._on_notify(batterie, bytearray.fromhex(BATTERIE))
                time.sleep(0.8)  # après la référence
                ctx.glasses._on_notify(capteur, bytearray.fromhex("0a0101"))

            fil = threading.Thread(target=appuyer, daemon=True)
            debut = time.monotonic()
            # La route borne l'appui à 2 s minimum ; la référence, abaissée ici, dure 0,3 s.
            fil.start()
            r = client.post("/api/lunettes/bouton/apprendre", json={"secondes": 2})
            fil.join(timeout=2)
            assert r.status_code == 200 and r.json()["etat"] == "appris", r.text
            assert r.json()["signature"] == f"{BOUTON}:0a0101" and time.monotonic() - debut < 6
            assert ctx.settings.user.bouton_description_signature == f"{BOUTON}:0a0101"

            ctx.glasses._on_notify(capteur, bytearray.fromhex("0a0101"))
            fin = time.monotonic() + 3
            while not acc.appels and time.monotonic() < fin:
                time.sleep(0.02)
            assert acc.appels and acc.appels[0]["source"] == "lunettes" and acc.appels[0]["mode"] == "scene"

            assert client.delete("/api/lunettes/bouton").json() == {"ok": True}
            assert ctx.settings.user.bouton_description_signature == ""
    finally:
        ctx.glasses.client = None
        ctx.close()
