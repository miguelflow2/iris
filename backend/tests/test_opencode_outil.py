"""Le câblage de la délégation à OpenCode.

Ce fichier ne teste presque pas d'algorithme : il teste des BRANCHEMENTS. C'est délibéré. Le
5 septembre 2026, deux fois dans la même journée, des modules entiers — écrits, relus, couverts par
des dizaines de tests verts — sont restés parfaitement inutilisables parce que personne ne les avait
appelés. Un test qui vérifie qu'une fonction calcule juste ne dit rien de cela. Les tests qui
suivent vérifient donc, un par un, les endroits où le fil peut être coupé : la déclaration de
l'outil, sa présence dans la liste réellement envoyée au modèle, les TROIS constructions de
ToolContext dans chat.py, et l'existence du service dans l'application.

Et une garantie de plus, qui prime sur tout le reste cette semaine : tant qu'OpenCode n'est pas
installé — ce qui est le cas sur cette machine le 5 septembre 2026, aucun binaire nulle part — IRIS
doit se comporter EXACTEMENT comme si rien n'avait été ajouté. Miguel présente mardi.
"""
from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

RACINE = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------- doublures
class FauxOpenCode:
    """Le service tel que l'outil a le droit de le supposer, avec EXACTEMENT la signature du vrai
    `Contremaitre` : dire s'il est disponible, expliquer son silence, et déléguer APRÈS accord.

    Le `genre` est en tête et n'a pas de valeur par défaut, comme dans le vrai module — c'est ce
    détail-là qui ferait échouer un appel écrit de mémoire, et seulement le jour de l'usage réel.
    """

    def __init__(self, *, utilisable: bool = True, raison: str = "", resultat: dict | None = None):
        self._utilisable = utilisable
        self._raison = raison
        self._resultat = resultat
        self.registre = None  # comme le vrai : None = personne ne trace, l'outil s'en charge
        self.appels: list[tuple[str, str, str, str]] = []
        self.confirmations: list[tuple[str, str]] = []

    @property
    def disponible(self) -> bool:
        return self._utilisable

    def pourquoi_pas_pret(self) -> str:
        return self._raison

    async def deleguer_apres_accord(self, genre: str, dossier: str, consigne: str, confirmer,
                                    source: str = "text") -> dict:
        self.appels.append((genre, dossier, consigne, source))
        if source == "voice":
            return {"ok": False, "dossier": dossier,
                    "message": f"Je peux confier ça à OpenCode dans {dossier}, mais il faut que tu "
                               "valides à l'écran."}
        accorde = await confirmer(f"Confier à OpenCode le travail dans {dossier}", consigne)
        self.confirmations.append((dossier, consigne))
        if not accorde:
            return {"ok": False, "dossier": dossier,
                    "message": "Je n'ai rien lancé : ça n'a pas été confirmé."}
        return self._resultat or {
            "ok": True, "dossier": dossier,
            "message": "3 fichiers modifiés, 12 lignes ajoutées, 4 supprimées, dans site-flowcare.",
        }


def _contexte(**extra):
    """Un ToolContext minimal, sans base de données : la plupart des chemins testés ici s'arrêtent
    avant le moindre effet de bord."""
    from iris.tools import ToolContext

    async def accepter(titre: str, detail: str) -> bool:
        return True

    # `_run_inner` lit la politique de confirmation dès sa première ligne, pour tous les outils.
    reglages = SimpleNamespace(user=SimpleNamespace(confirm_commands="dangerous", computer_use=True))
    base = dict(settings=reglages, consent=SimpleNamespace(log=lambda *a, **k: None),
                capture=None, memory=None, agent="test", confirm=accepter)
    base.update(extra)
    return ToolContext(**base)


def _appeler(ctx, args: dict | None = None):
    from iris.tools import make_tool_runner

    return asyncio.run(make_tool_runner(ctx)("deleguer_programmation", args or {}))


# --------------------------------------------- 1. IRIS ne bouge pas tant qu'OpenCode est absent
def test_sans_opencode_la_liste_doutils_est_exactement_celle_davant():
    """La garantie qui compte cette semaine.

    Si cette assertion tombe, un outil de plus est proposé au modèle alors qu'OpenCode n'est pas
    installé : il l'appellerait, échouerait, et la démonstration de mardi se jouerait sur un
    message d'erreur au lieu d'une action."""
    from iris.tools import TOOL_SPECS, tool_specs

    noms = {s.name for s in tool_specs(_contexte(create_task=None))}
    assert "deleguer_programmation" not in noms
    assert noms == {s.name for s in TOOL_SPECS if s.name not in ("create_task", "deleguer_programmation")}


def test_un_service_present_mais_pas_utilisable_ne_montre_pas_loutil_non_plus():
    """OpenCode désinstallé après coup, ou binaire introuvable : le service existe, la porte reste
    fermée. La fonctionnalité est inactive PAR CONSTRUCTION, pas par un drapeau qu'on peut oublier."""
    from iris.tools import tool_specs

    ctx = _contexte(create_task=None, opencode=FauxOpenCode(utilisable=False))
    assert "deleguer_programmation" not in {s.name for s in tool_specs(ctx)}


def test_un_contexte_minimal_ne_fait_pas_planter_la_liste_doutils():
    """Plusieurs tests déjà écrits appellent tool_specs avec un objet qui n'a QUE create_task.
    Lire ctx.opencode sans précaution les casserait tous d'un coup — et personne n'aurait relié la
    panne à la délégation."""
    from iris.tools import tool_specs

    assert tool_specs(SimpleNamespace(create_task=None))


# --------------------------------------------------------- 2. l'outil existe et il est offert
def test_loutil_est_declare_et_exige_le_dossier():
    """Le schéma rend le dossier obligatoire. Sans lui, le modèle pourrait déléguer « quelque part »,
    et l'accord de l'utilisateur ne porterait sur rien de vérifiable."""
    from iris.tools import TOOL_SPECS

    spec = next(s for s in TOOL_SPECS if s.name == "deleguer_programmation")
    assert set(spec.input_schema["required"]) == {"dossier", "consigne"}
    assert "dossier" in spec.description.lower()


def test_loutil_est_offert_au_modele_quand_opencode_est_utilisable():
    """Déclaré ne suffit pas : il doit se retrouver dans la liste réellement envoyée au modèle.
    C'est la ligne que personne n'avait vérifiée le 5 septembre."""
    from iris.tools import tool_specs

    ctx = _contexte(create_task=None, opencode=FauxOpenCode())
    assert "deleguer_programmation" in {s.name for s in tool_specs(ctx)}


def test_loutil_reste_offert_meme_sans_ecran_sans_clavier_et_sans_web():
    """Déléguer la programmation n'a rien à voir avec la souris ni le navigateur : l'outil ne doit
    disparaître avec aucun de ces trois groupes, sinon « corrige le bogue » cesserait de marcher
    dès qu'IRIS juge la demande non graphique — c'est-à-dire presque toujours."""
    from iris.tools import tool_specs

    ctx = _contexte(create_task=None, opencode=FauxOpenCode())
    noms = {s.name for s in tool_specs(ctx, screen=False, keyboard=False, web=False)}
    assert "deleguer_programmation" in noms


# ------------------------------------------------------------------- 3. le refus est structurel
def test_rien_ne_part_sans_accord():
    """La serrure du courriel et du SMS, appliquée à la programmation : le service reçoit la
    fonction de confirmation et n'agit qu'après un oui. Un refus doit rester un refus visible."""
    async def refuser(titre: str, detail: str) -> bool:
        return False

    service = FauxOpenCode()
    resultat = _appeler(_contexte(opencode=service, confirm=refuser),
                        {"dossier": "~/Documents/IRIS/site-flowcare", "consigne": "corrige le bogue"})
    assert service.confirmations, "le service n'a jamais demandé l'accord"
    assert isinstance(resultat, dict) and resultat.get("is_error")
    assert "confirmé" in resultat["content"]


def test_laccord_donne_laisse_travailler_et_rend_compte():
    """Le chemin heureux : IRIS relaie la phrase du service, celle qui se dit à voix haute."""
    service = FauxOpenCode()
    resultat = _appeler(_contexte(opencode=service),
                        {"dossier": "~/Documents/IRIS/site-flowcare", "consigne": "corrige le bogue",
                         "genre": "correction"})
    assert service.appels == [("correction", "~/Documents/IRIS/site-flowcare", "corrige le bogue", "text")]
    assert "3 fichiers modifiés" in str(resultat)


def test_le_genre_du_travail_est_transmis_et_a_un_defaut():
    """Le genre entre dans la phrase que Miguel lit avant d'approuver (« Envoyer OpenCode corriger
    dans site-flowcare »). Le modèle peut l'omettre ; le service ne doit pas recevoir une chaîne
    vide, qui produirait une phrase bancale au moment le plus important."""
    service = FauxOpenCode()
    _appeler(_contexte(opencode=service), {"dossier": "~/x", "consigne": "fais"})
    assert service.appels[0][0] == "tache"


def test_le_dossier_manquant_est_refuse_avant_tout_appel():
    """Deviner un chemin, c'est envoyer un agent modifier des fichiers au hasard. Le service ne doit
    même pas être sollicité."""
    service = FauxOpenCode()
    resultat = _appeler(_contexte(opencode=service), {"consigne": "corrige le bogue"})
    assert service.appels == []
    assert resultat["is_error"] and "dossier" in resultat["content"]


def test_la_consigne_vide_est_refusee_avant_tout_appel():
    """Une délégation sans consigne ferait tourner OpenCode sur une intention vide, dans un vrai
    dossier de Miguel."""
    service = FauxOpenCode()
    resultat = _appeler(_contexte(opencode=service), {"dossier": "~/Documents/IRIS/site-flowcare"})
    assert service.appels == []
    assert resultat["is_error"]


# ------------------------------------------------------------------------ 4. le trou vocal, dit
def test_la_source_de_la_demande_est_transmise_au_service():
    """Rien dans voice/ n'écoute « chat.confirm » : une confirmation demandée pendant que Miguel
    parle ne s'affiche nulle part. Le service sait le traiter — sa phrase nomme le dossier —, mais
    il ne peut le faire que si on lui dit d'où vient la demande. C'est le seul rôle de `source`
    dans ToolContext, et sans lui IRIS attendrait 180 secondes devant un écran que personne ne
    regarde, puis refuserait en silence : un comportement qui ressemble à une panne."""
    service = FauxOpenCode()
    resultat = _appeler(_contexte(opencode=service, source="voice"),
                        {"dossier": "~/Documents/IRIS/site-flowcare", "consigne": "corrige le bogue"})
    assert service.appels[0][3] == "voice"
    assert service.confirmations == [], "une modale invisible a été ouverte"
    # Une chaîne, pas une erreur : « va valider à l'écran » n'est pas un échec d'outil. Marqué en
    # erreur, IRIS répondrait « je n'ai pas réussi », ce qui est faux et décourage de réessayer.
    assert isinstance(resultat, str) and "à l'écran" in resultat


def test_un_service_qui_ignore_la_source_est_arrete_avant_la_modale_invisible():
    """Le filet, pour un service qui ne connaîtrait pas encore le trou vocal. Mieux vaut une phrase
    qui dit d'aller à l'écran qu'un accord demandé à quelqu'un qui conduit."""
    from iris.tools import PAS_A_LA_VOIX

    class SansSource(FauxOpenCode):
        async def deleguer_apres_accord(self, genre, dossier, consigne, confirmer):  # pas de `source`
            return await FauxOpenCode.deleguer_apres_accord(self, genre, dossier, consigne, confirmer)

    service = SansSource()
    resultat = _appeler(_contexte(opencode=service, source="voice"), {"dossier": "~/x", "consigne": "y"})
    assert service.appels == []
    assert resultat == PAS_A_LA_VOIX


def test_par_ecrit_le_meme_appel_passe():
    """Le contre-exemple du test précédent : c'est bien la SOURCE qui décide, pas l'outil qui est
    cassé. Sans cette paire, un refus permanent passerait pour une protection."""
    service = FauxOpenCode()
    _appeler(_contexte(opencode=service, source="text"),
             {"dossier": "~/Documents/IRIS/site-flowcare", "consigne": "corrige le bogue"})
    assert len(service.confirmations) == 1


# ---------------------------------------------------------------- 5. l'absence se dit en français
def test_opencode_pas_installe_est_annonce_en_francais():
    """Si le service explique lui-même son silence, c'est SA phrase qu'on relaie : lui seul sait
    s'il manque le binaire, la configuration ou autre chose."""
    service = FauxOpenCode(utilisable=False,
                           raison="OpenCode n'est pas installé sur cet ordinateur.")
    resultat = _appeler(_contexte(opencode=service), {"dossier": "x", "consigne": "y"})
    assert resultat["is_error"] and resultat["content"] == "OpenCode n'est pas installé sur cet ordinateur."


def test_un_service_muet_a_quand_meme_une_phrase():
    """Un service qui ne sait pas s'expliquer ne doit pas produire une réponse vide : « » n'apprend
    rien à personne."""
    from iris.tools import OPENCODE_ABSENT

    resultat = _appeler(_contexte(opencode=FauxOpenCode(utilisable=False, raison="")),
                        {"dossier": "x", "consigne": "y"})
    assert resultat["content"] == OPENCODE_ABSENT


def test_sans_service_du_tout_loutil_ne_leve_rien():
    """Le module opencode.py peut manquer (il est écrit en parallèle). Une exception ici remonterait
    jusqu'à la boucle de chat et ferait taire IRIS."""
    resultat = _appeler(_contexte(opencode=None), {"dossier": "x", "consigne": "y"})
    assert resultat["is_error"] and "pas branchée" in resultat["content"]


def test_un_service_qui_explose_en_repondant_ne_fait_pas_taire_iris():
    """Vu ailleurs dans ce projet : une exception avalée par l'exécuteur d'outils laisse IRIS
    silencieuse, et rien n'explique pourquoi."""
    class Cassé:
        def utilisable(self) -> bool:
            raise RuntimeError("processus mort")

    resultat = _appeler(_contexte(opencode=Cassé()), {"dossier": "x", "consigne": "y"})
    assert resultat["is_error"]


# ------------------------------------------------------------------------------ 6. la trace
def test_la_delegation_laisse_une_trace_du_dossier_pas_du_code():
    """Le registre chaîné répond à « qu'a fait IRIS ». Il doit porter le dossier RÉSOLU par le
    service — pas la chaîne dite par le modèle, qui peut désigner autre chose — et jamais le
    contenu des fichiers : le détail est tronqué à 500 caractères et n'est pas chiffré."""
    entrees: list[tuple] = []
    service = FauxOpenCode(resultat={"ok": True, "dossier": r"C:\Users\migue\Documents\IRIS\site",
                                     "phrase": "C'est corrigé."})
    ctx = _contexte(opencode=service,
                    consent=SimpleNamespace(log=lambda ev, **kw: entrees.append((ev, kw))))
    _appeler(ctx, {"dossier": "~/documents/iris/SITE", "consigne": "corrige le bogue de connexion"})
    assert entrees and entrees[0][0] == "opencode_termine"
    assert r"C:\Users\migue\Documents\IRIS\site" in entrees[0][1]["detail"]


def test_un_refus_se_trace_aussi():
    """« Rien ne s'est passé » et « on n'a pas voulu » sont deux réponses différentes à la même
    question, et seul le registre peut les distinguer après coup."""
    async def refuser(titre: str, detail: str) -> bool:
        return False

    entrees: list[tuple] = []
    ctx = _contexte(opencode=FauxOpenCode(), confirm=refuser,
                    consent=SimpleNamespace(log=lambda ev, **kw: entrees.append((ev, kw))))
    _appeler(ctx, {"dossier": "~/Documents/IRIS/site", "consigne": "corrige"})
    assert [e[0] for e in entrees] == ["opencode_refuse"]


def test_un_service_qui_tient_deja_le_registre_nest_pas_trace_deux_fois():
    """`Contremaitre` inscrit lui-même opencode_delegue, opencode_termine et opencode_refus dès
    qu'il reçoit le registre. Deux lignes pour un seul geste rendraient le journal illisible — et un
    journal illisible ne prouve plus rien, ce qui est exactement ce qu'on lui demande."""
    entrees: list[tuple] = []
    service = FauxOpenCode()
    service.registre = object()  # il trace tout seul
    ctx = _contexte(opencode=service,
                    consent=SimpleNamespace(log=lambda ev, **kw: entrees.append((ev, kw))))
    _appeler(ctx, {"dossier": "~/Documents/IRIS/site", "consigne": "corrige"})
    assert entrees == []


# ------------------------------------------- 7. le vrai service, appelé par le vrai exécuteur
def _contremaitre(tmp_path, monkeypatch, *, racine=None, registre=None):
    """Le vrai `Contremaitre`, avec un binaire et un lanceur simulés : aucun processus n'est lancé,
    ni OpenCode ni git, et le test ne dépend pas de ce qui est installé sur la machine.

    La liste noire est neutralisée ici, et seulement ici : les dossiers temporaires de pytest vivent
    sous `~/AppData/Local/Temp`, or `~/AppData` est interdit — à juste titre, c'est là que dorment
    `.env` et `iris.db`. Sans ce retrait, ce test ne prouverait qu'une chose : que la liste noire
    marche. Elle a ses propres tests dans le module qui la contient ; celui-ci vérifie le CÂBLAGE.
    """
    from iris import opencode as mod

    monkeypatch.setattr(mod, "racines_interdites_par_defaut", tuple)
    lancements: list[list[str]] = []

    def lanceur(argv, dossier, delai, env=None):
        lancements.append(list(argv))
        if argv and argv[0] == "git":
            return mod.Resultat(code=-1, introuvable=True)  # le dossier n'est pas versionné
        return mod.Resultat(code=0, sortie="Bogue corrigé dans index.html.")

    reglages = SimpleNamespace(
        data_dir=tmp_path / "donnees",
        user=SimpleNamespace(local_only=False, opencode_racines=[str(racine or tmp_path / "projets")]),
    )
    service = mod.Contremaitre(reglages, lanceur=lanceur,
                               chercheur=lambda: str(tmp_path / "faux" / "opencode.exe"),
                               registre=registre)
    return service, lancements


def test_le_vrai_service_est_appele_avec_la_bonne_signature(tmp_path, monkeypatch):
    """LE test qui vaut tous les autres de ce fichier : le vrai Contremaitre, le vrai exécuteur
    d'outils, et rien entre les deux.

    `deleguer_apres_accord(genre, dossier, consigne, confirmer, source)` commence par `genre`, sans
    valeur par défaut. Un appel écrit de mémoire — (dossier, consigne, confirmer) — lèverait un
    TypeError, et il le lèverait au moment exact où Miguel demande de corriger un bogue : jamais
    pendant les tests, toujours en démonstration."""
    from iris.tools import tool_specs

    projet = tmp_path / "projets" / "site-flowcare"
    projet.mkdir(parents=True)
    (projet / "index.html").write_text("<h1>bonjour</h1>", encoding="utf-8")
    service, lancements = _contremaitre(tmp_path, monkeypatch)

    assert "deleguer_programmation" in {s.name for s in tool_specs(_contexte(create_task=None, opencode=service))}
    resultat = _appeler(_contexte(opencode=service),
                        {"dossier": str(projet), "consigne": "corrige le bogue d'affichage",
                         "genre": "correction"})
    assert any(a[1:2] == ["run"] for a in lancements), f"OpenCode n'a pas été lancé : {lancements}"
    assert "corrige le bogue d'affichage" in " ".join(lancements[-1])
    assert not (isinstance(resultat, dict) and resultat.get("is_error")), resultat


def test_le_vrai_service_refuse_un_dossier_hors_perimetre_et_iris_le_dit(tmp_path, monkeypatch):
    """Le périmètre est une liste blanche explicite : ce qui n'y est pas est refusé, et le refus
    doit remonter en français jusqu'à l'utilisateur, pas en trace d'exception."""
    dehors = tmp_path / "ailleurs"
    dehors.mkdir()
    (tmp_path / "projets").mkdir()
    service, lancements = _contremaitre(tmp_path, monkeypatch)
    resultat = _appeler(_contexte(opencode=service), {"dossier": str(dehors), "consigne": "corrige"})
    assert isinstance(resultat, dict) and resultat["is_error"]
    assert lancements == [], "un dossier hors périmètre a quand même été touché"
    assert resultat["content"].strip() and "Traceback" not in resultat["content"]


def test_sans_dossier_autorise_le_vrai_service_ne_delegue_rien(tmp_path):
    """La liste des racines est vide par défaut, et c'est voulu : « corrige mon site » ne désigne
    pas un dossier, il désigne une idée. Tant que Miguel n'en a nommé aucun, l'outil n'est même pas
    offert au modèle."""
    from iris.tools import tool_specs

    from iris import opencode as mod

    reglages = SimpleNamespace(data_dir=tmp_path, user=SimpleNamespace(local_only=False, opencode_racines=[]))
    service = mod.Contremaitre(reglages, lanceur=lambda *a, **k: mod.Resultat(),
                               chercheur=lambda: str(tmp_path / "opencode.exe"))
    assert service.disponible is False
    assert "deleguer_programmation" not in {s.name for s in tool_specs(_contexte(create_task=None, opencode=service))}


# ----------------------------------------------------- 8. le câblage, aux trois endroits exacts
def test_les_trois_constructions_de_toolcontext_portent_le_service():
    """LA raison d'être de ce fichier.

    chat.py construit un ToolContext à trois endroits : commande locale, routine, et tour de modèle.
    Brancher le service dans un seul suffirait à faire passer une démonstration et à laisser deux
    chemins morts — c'est exactement la forme du bogue du 5 septembre. On lit donc le fichier
    lui-même, plutôt que d'espérer qu'un test d'intégration passe par les trois."""
    arbre = ast.parse((RACINE / "iris" / "chat.py").read_text(encoding="utf-8"))
    appels = [n for n in ast.walk(arbre)
              if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "ToolContext"]
    assert len(appels) == 3, f"chat.py construit {len(appels)} ToolContext, pas 3 : revois ce test"
    for appel in appels:
        mots = {kw.arg for kw in appel.keywords}
        assert "opencode" in mots, "un ToolContext de chat.py ne porte pas le service OpenCode"
        assert "source" in mots, "un ToolContext de chat.py ne dit pas d'où vient la demande"


def test_le_service_existe_dans_lapplication_et_le_chat_le_voit(app):
    """L'autre moitié du même câblage : créé dans AppContext, et RELIÉ au chat. Un service créé mais
    jamais injecté est un service qui n'existe pas — c'est mot pour mot ce qui s'est passé le
    5 septembre 2026 avec le courriel et la téléphonie.

    `construire_opencode` fabrique le service en lisant la signature réelle de sa classe. Si elle
    change et que la construction échoue, main.py journalise et rend None, en silence : cette
    assertion est le seul endroit où ce silence devient un échec."""
    ctx = app.state.ctx
    assert ctx.opencode is not None, "iris/opencode.py est là mais AppContext n'a pas su le construire"
    assert ctx.chat.opencode is ctx.opencode
    assert ctx.opencode.registre is ctx.consent, "le service ne peut pas tracer ce qu'il fait"


def test_lapplication_demarre_quoi_quil_arrive_a_opencode(app):
    """Le module opencode.py peut manquer, le binaire aussi, et aucun dossier n'est autorisé par
    défaut. Rien de tout cela ne doit empêcher IRIS de se lancer : la voix, elle, doit marcher.

    L'assertion porte sur l'ÉQUIVALENCE plutôt que sur l'état de cette machine — l'outil est offert
    si et seulement si la délégation est réellement possible. Écrit autrement (« utilisable est
    faux »), ce test deviendrait faux le jour où Miguel installera OpenCode, et il le deviendrait
    sans rien signaler d'utile."""
    from iris.tools import opencode_utilisable, tool_specs

    ctx = app.state.ctx
    noms = {s.name for s in tool_specs(_contexte(create_task=None, opencode=ctx.opencode))}
    assert ("deleguer_programmation" in noms) is opencode_utilisable(ctx.opencode)


def test_letat_de_la_delegation_est_lisible_par_lapplication(client):
    """L'outil disparaît de la liste quand OpenCode manque — c'est voulu, mais ça rend l'absence
    muette. Cette route est le seul endroit où elle reste lisible ; sans elle, personne ne saurait
    jamais qu'il suffit d'installer OpenCode.

    Et l'absence doit être EXPLIQUÉE : un « utilisable : faux » sans phrase n'apprend rien à
    personne, surtout pas à quelqu'un qui vient de demander de corriger un bogue."""
    etat = client.get("/api/opencode/etat").json()
    assert set(etat) == {"branche", "utilisable", "raison"}
    assert bool(etat["raison"].strip()) is not etat["utilisable"]


# --------------------------------------------------- 9. la voix et la traduction restent intactes
@pytest.mark.parametrize("fichier", ["iris/traduction.py", "iris/quick_commands.py",
                                     "iris/voice/listener.py"])
def test_la_voix_et_la_traduction_ne_dependent_de_rien_de_tout_ceci(fichier):
    """La voix a subi une panne TOTALE le 5 septembre 2026 et vient d'être réparée. Elle ne doit
    dépendre d'aucune ligne écrite pour OpenCode : si l'un de ces fichiers importait le module, une
    erreur dans une fonctionnalité que personne n'utilise encore pourrait rendre IRIS sourde."""
    source = (RACINE / fichier).read_text(encoding="utf-8", errors="replace").lower()
    assert "opencode" not in source
