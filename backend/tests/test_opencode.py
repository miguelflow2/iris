"""Déléguer la programmation à OpenCode : un agent qui écrit des fichiers ne se rattrape pas.

Ces tests protègent trois promesses, dans l'ordre où elles comptent.

1. Tant qu'OpenCode n'est pas installé — c'est l'état de la machine aujourd'hui, donc le chemin de
   loin le plus emprunté — IRIS le DIT en français et ne lance rien. Jamais une erreur technique.
2. Le périmètre fait partie de l'accord. Un oui donné pour un dossier ne vaut pas pour un autre.
   C'est exactement le défaut trouvé le 5 septembre 2026 dans telephonie.py, où l'accord donné pour
   un brouillon sur l'iPhone restait valable si la voie basculait sur un service payant.
3. Le compte rendu est honnête : « il n'a rien modifié » se dit aussi nettement que « c'est fait »,
   et un délai dépassé ne se raconte pas comme une annulation.

AUCUN test ici ne lance de processus : ni OpenCode, ni git. Le lanceur est injecté, et il compte
ses appels — un lanceur qui n'a jamais été appelé est la seule preuve acceptable de « rien n'a été
lancé ». La liste noire est injectée elle aussi : sous Windows, pytest range ses dossiers
temporaires dans ~/AppData/Local/Temp, qui est justement interdit par défaut.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from iris.opencode import (
    DUREE_ACCORD,
    MODE_EMPLOI,
    Autorisation,
    AutorisationInvalide,
    Chantier,
    CheminRefuse,
    Contremaitre,
    ErreurOpenCode,
    OpenCodeIndisponible,
    Resultat,
    comparer,
    inventaire,
    politique_iris,
    racines_interdites_par_defaut,
    resoudre_dossier,
    trouver_opencode,
)

BINAIRE = "C:\\faux\\opencode.exe"  # n'existe pas : rien ne doit jamais tenter de l'exécuter
CONSIGNE = "corrige le bogue d'affichage du panier"


# --------------------------------------------------------------------------- doublures
class FauxLanceur:
    """Le seul endroit qui « lancerait » quelque chose. Il ne lance rien et compte tout.

    Il répond aussi à git, parce que le service interroge le dépôt avant de déléguer — et un test
    ne doit pas dépendre du fait que ce dossier temporaire soit versionné ou non.
    """

    def __init__(
        self,
        code: int = 0,
        sortie: str = "",
        expire: bool = False,
        introuvable: bool = False,
        depot: bool = False,
        propre: bool = True,
        tetes: tuple[str, ...] = ("a1b2c3",),
        effet: Any = None,  # ce qu'OpenCode « écrit » dans le dossier
        au_lancement: Any = None,  # observé au moment précis du lancement
    ):
        self.code = code
        self.sortie = sortie
        self.expire = expire
        self.introuvable = introuvable
        self.depot = depot
        self.propre = propre
        self.tetes = tetes
        self.effet = effet
        self.au_lancement = au_lancement
        self.appels: list[dict] = []
        self.lancements = 0
        self._tete = 0

    def __call__(self, argv, dossier, delai, env=None) -> Resultat:
        self.appels.append({"argv": list(argv), "dossier": dossier, "delai": delai, "env": env})
        if argv[:1] == ["git"]:
            return self._git(argv)
        self.lancements += 1
        if self.au_lancement:
            self.au_lancement(dossier)
        if self.effet:
            self.effet(Path(dossier))
        return Resultat(code=self.code, sortie=self.sortie, expire=self.expire, introuvable=self.introuvable)

    def _git(self, argv) -> Resultat:
        if not self.depot:
            return Resultat(code=128, sortie="fatal: not a git repository")
        if argv[1] == "status":
            return Resultat(code=0, sortie="" if self.propre else " M app.py")
        if argv[1] == "rev-parse":
            sha = self.tetes[min(self._tete, len(self.tetes) - 1)]
            self._tete += 1
            return Resultat(code=0, sortie=sha)
        return Resultat(code=0)


def lanceur_interdit(*_a, **_k):
    """Détecteur : si ce module lance quoi que ce soit alors qu'il ne devrait pas, le test le voit."""
    raise AssertionError("un processus a été lancé alors que rien ne devait l'être")


class FauxRegistre:
    def __init__(self) -> None:
        self.entrees: list[tuple[str, str, str]] = []

    def log(self, event_type: str, data_type: str | None = None, agent: str | None = None, detail: str = "") -> None:
        self.entrees.append((event_type, agent or "", detail))

    @property
    def evenements(self) -> list[str]:
        return [e[0] for e in self.entrees]


class Horloge:
    """Horloge pilotée : vérifier qu'un accord expire ne doit pas prendre cinq minutes."""

    def __init__(self, depart: float = 1_000.0):
        self.t = depart

    def __call__(self) -> float:
        return self.t

    def avancer(self, secondes: float) -> None:
        self.t += secondes


@dataclass
class ReglagesOpenCode:
    """Reproduit ce que config.py exposera. Absent aujourd'hui : le service doit s'en passer."""

    racines: list = field(default_factory=list)
    duree_max_minutes: Any = None
    actif: bool = True


@dataclass
class FauxUtilisateur:
    local_only: bool = False
    opencode: Any = None


class FauxSettings:
    def __init__(self, data_dir: Path, **kwargs):
        self.data_dir = Path(data_dir)
        self.user = FauxUtilisateur(**kwargs)


@dataclass
class Atelier:
    """Un faux disque : un dossier de projets autorisé, un dossier privé qui ne l'est pas."""

    racine: Path
    projets: Path
    site: Path
    autre: Path
    prive: Path
    donnees: Path


# --------------------------------------------------------------------------- fixtures
@pytest.fixture()
def atelier(tmp_path: Path) -> Atelier:
    projets = tmp_path / "projets"
    site = projets / "site"
    autre = projets / "autre"
    prive = tmp_path / "prive"
    donnees = tmp_path / "iris-data"
    for dossier in (site, autre, prive, donnees):
        dossier.mkdir(parents=True)
    (site / "index.html").write_text("<h1>bonjour</h1>", encoding="utf-8")
    (site / "style.css").write_text("body{}", encoding="utf-8")
    (prive / "secret.txt").write_text("clé", encoding="utf-8")
    return Atelier(racine=tmp_path, projets=projets, site=site, autre=autre, prive=prive, donnees=donnees)


def contremaitre(
    atelier: Atelier,
    lanceur: Any = None,
    binaire: str = BINAIRE,
    registre: Any = None,
    horloge: Any = None,
    racines: list | None = None,
    **reglages,
) -> Contremaitre:
    """Un contremaître prêt à travailler, sans qu'aucun binaire ni aucun dépôt n'existe vraiment."""
    section = ReglagesOpenCode(racines=[str(atelier.projets)] if racines is None else racines, **reglages)
    settings = FauxSettings(atelier.donnees, opencode=section)
    return Contremaitre(
        settings,
        lanceur=lanceur or lanceur_interdit,
        chercheur=lambda: binaire,
        registre=registre,
        horloge=horloge or (lambda: 0.0),
        racines_interdites=[],  # voir le module : ~/AppData contient les dossiers temporaires de pytest
    )


def accorder(service: Contremaitre, chantier: Chantier, reponse: bool = True) -> Autorisation | None:
    """Passe par le SEUL chemin qui produit une autorisation : la confirmation de l'utilisateur."""

    async def confirmer(_titre: str, _detail: str) -> bool:
        return reponse

    return asyncio.run(service.demander_accord(chantier, confirmer))


def ecrire(nom: str, contenu: str):
    """Fabrique un « effet OpenCode » : ce que l'agent écrit vraiment sur le disque."""

    def effet(dossier: Path) -> None:
        (dossier / nom).write_text(contenu, encoding="utf-8")

    return effet


# --------------------------------------------------------------------------- 1. inutilisable proprement
def test_sans_opencode_installe_iris_le_dit_en_francais_et_ne_lance_rien(atelier: Atelier):
    """C'est l'état de la machine aujourd'hui. Si ce chemin levait, « corrige mon site » finirait
    en trace d'exception à l'écran au lieu d'une phrase que Miguel peut comprendre."""
    service = contremaitre(atelier, binaire="")
    assert service.installe is False
    assert service.disponible is False
    raison = service.pourquoi_pas_pret()
    assert raison == MODE_EMPLOI
    assert "n'est pas installé" in raison
    assert "je n'installe rien" in raison.lower(), "IRIS ne doit jamais proposer d'installer elle-même"
    with pytest.raises(OpenCodeIndisponible) as refus:
        service.preparer("correction", str(atelier.site), CONSIGNE)
    assert str(refus.value) == MODE_EMPLOI


def test_letat_dun_service_indisponible_se_lit_sans_lever(atelier: Atelier):
    """L'écran des réglages appelle etat() à chaque affichage : il ne doit jamais pouvoir planter."""
    etat = contremaitre(atelier, binaire="").etat()
    assert etat["installe"] is False and etat["disponible"] is False
    assert etat["explication"]
    assert json.dumps(etat, ensure_ascii=False), "l'état doit rester sérialisable pour l'interface"


def test_toutes_les_erreurs_du_module_portent_une_phrase_lisible(atelier: Atelier):
    """Une exception d'ici est lue à voix haute. Si elle héritait d'autre chose qu'ErreurOpenCode,
    la couche d'appel la traiterait comme une panne et dirait « erreur interne »."""
    service = contremaitre(atelier, binaire="")
    for classe in (OpenCodeIndisponible, CheminRefuse, AutorisationInvalide):
        assert issubclass(classe, ErreurOpenCode)
    with pytest.raises(ErreurOpenCode):
        service.preparer("correction", str(atelier.site), CONSIGNE)


def test_la_recherche_du_binaire_ne_leve_jamais(atelier: Atelier):
    """PATH exotique, lecteur réseau déconnecté : chercher un programme absent n'est pas une panne."""
    assert isinstance(trouver_opencode(), str)

    def chercheur_casse():
        raise OSError("PATH illisible")

    service = Contremaitre(FauxSettings(atelier.donnees), lanceur=lanceur_interdit, chercheur=chercheur_casse)
    assert service.chemin_binaire == ""
    assert service.pourquoi_pas_pret() == MODE_EMPLOI


def test_le_mode_local_interdit_denvoyer_le_code_source_a_un_tiers(atelier: Atelier):
    """OpenCode transmet le code au fournisseur d'IA qu'il utilise. Le mode local promet l'inverse."""
    settings = FauxSettings(atelier.donnees, local_only=True,
                            opencode=ReglagesOpenCode(racines=[str(atelier.projets)]))
    service = Contremaitre(settings, lanceur=lanceur_interdit, chercheur=lambda: BINAIRE, racines_interdites=[])
    assert service.disponible is False
    assert "mode local" in service.pourquoi_pas_pret().lower()


def test_la_delegation_se_desactive_dans_les_reglages(atelier: Atelier):
    """Un réglage à faux doit couper la fonctionnalité entière, avant même de chercher le binaire."""
    service = contremaitre(atelier, actif=False)
    assert service.disponible is False
    assert "désactivée" in service.pourquoi_pas_pret()


def test_sans_section_dans_les_reglages_le_service_tient_debout(atelier: Atelier):
    """config.py n'a pas encore de section « opencode » : le service doit s'en passer, pas planter."""
    service = Contremaitre(FauxSettings(atelier.donnees), lanceur=lanceur_interdit, chercheur=lambda: BINAIRE)
    assert service.racines() == []
    assert "aucun dossier" in service.pourquoi_pas_pret()


# --------------------------------------------------------------------------- 2. le périmètre
def test_aucun_dossier_nest_autorise_par_defaut(atelier: Atelier):
    """Le périmètre ne se déduit jamais de la conversation : « mon site » n'est pas un chemin."""
    service = contremaitre(atelier, racines=[])
    assert service.racines() == []
    assert service.disponible is False
    with pytest.raises(OpenCodeIndisponible) as refus:
        service.preparer("correction", str(atelier.site), CONSIGNE)
    assert "aucun dossier" in str(refus.value)


def test_un_dossier_hors_du_perimetre_est_refuse(atelier: Atelier):
    """Sans ça, « corrige le bogue » pointé sur ~/prive lâcherait un agent sur des fichiers personnels."""
    service = contremaitre(atelier)
    with pytest.raises(CheminRefuse) as refus:
        service.preparer("correction", str(atelier.prive), CONSIGNE)
    assert "autorisés" in str(refus.value)


def test_les_deux_points_ne_font_pas_sortir_du_perimetre(atelier: Atelier):
    """« projets/site/../../prive » est dans le périmètre à la lecture, et dehors une fois résolu."""
    evasion = str(atelier.site / ".." / ".." / "prive")
    with pytest.raises(CheminRefuse):
        resoudre_dossier(evasion, [atelier.projets])
    # et le même chemin, resté DANS le périmètre, doit passer
    assert resoudre_dossier(str(atelier.site / ".." / "autre"), [atelier.projets]) == atelier.autre.resolve()


def test_un_lien_qui_pointe_hors_du_perimetre_est_suivi_puis_refuse(atelier: Atelier):
    """Un lien posé dans un dossier autorisé est la façon la plus simple d'en faire sortir un agent.

    On ne s'appuie jamais sur is_symlink() pour ça : sur Windows, une jonction rend False tout en
    pointant ailleurs (mesuré sur « C:\\Users\\migue\\Application Data »). C'est resolve() qui
    tranche, et c'est lui qu'on vérifie ici.
    """
    passerelle = atelier.projets / "passerelle"
    try:
        passerelle.symlink_to(atelier.prive, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("création de lien symbolique non autorisée sur cette machine")
    with pytest.raises(CheminRefuse):
        resoudre_dossier(str(passerelle), [atelier.projets])


def test_un_chemin_peripherique_est_refuse_avant_toute_resolution(atelier: Atelier):
    """Mesuré : Path(r'\\\\?\\C:\\a\\..\\..\\Windows').resolve() rend « C:Users\\Windows » — ni le
    chemin de départ, ni un confinement valable. Ce qui casse la normalisation ne s'analyse pas."""
    for peripherique in ("\\\\?\\C:\\Users\\migue\\projets\\site", "\\\\.\\C:\\projets\\site"):
        with pytest.raises(CheminRefuse) as refus:
            resoudre_dossier(peripherique, [atelier.projets])
        assert "périphérique" in str(refus.value)


def test_un_partage_reseau_est_refuse(atelier: Atelier):
    """Sur un partage, ce qui se passe ne se surveille pas et ne se répare pas."""
    with pytest.raises(CheminRefuse) as refus:
        resoudre_dossier("\\\\serveur\\public\\site", [atelier.projets])
    assert "réseau" in str(refus.value)


def test_un_chemin_relatif_au_lecteur_est_refuse(atelier: Atelier):
    """Mesuré : « C:site » ne veut pas dire C:\\site, mais « site » à côté du dossier courant du
    backend — c'est-à-dire dans le dépôt d'IRIS."""
    with pytest.raises(CheminRefuse) as refus:
        resoudre_dossier("C:site", [atelier.projets])
    assert "complet" in str(refus.value)
    with pytest.raises(CheminRefuse):
        resoudre_dossier("projets/site", [atelier.projets])


def test_une_variable_denvironnement_non_resolue_est_refusee(atelier: Atelier):
    """Un modèle recopie volontiers « %USERPROFILE%\\site » depuis un fichier de configuration.
    Non remplacée, cette chaîne désigne un dossier littéralement nommé « %USERPROFILE% »."""
    with pytest.raises(CheminRefuse) as refus:
        resoudre_dossier("%USERPROFILE%\\projets\\site", [atelier.projets])
    assert "variable" in str(refus.value)


def test_un_chemin_vide_ne_devient_pas_le_dossier_courant(atelier: Atelier):
    """Une chaîne vide résolue donnerait le dossier depuis lequel IRIS tourne : son propre backend."""
    for rien in ("", "   ", None):
        with pytest.raises(CheminRefuse):
            resoudre_dossier(rien, [atelier.projets])  # type: ignore[arg-type]


def test_la_liste_noire_prime_sur_la_liste_blanche(atelier: Atelier):
    """Autoriser ~/Documents ne doit pas autoriser ~/Documents/.ssh par ricochet."""
    interdit = atelier.projets / "site" / "secrets"
    interdit.mkdir()
    with pytest.raises(CheminRefuse) as refus:
        resoudre_dossier(str(interdit), [atelier.projets], [interdit.parent / "secrets"])
    assert "protégé" in str(refus.value)


def test_le_depot_diris_et_son_dossier_de_donnees_sont_interdits_doffice(atelier: Atelier):
    """OpenCode est DÉJÀ venu dans le backend d'IRIS tout seul — son journal montre ses appels à
    127.0.0.1:8765. Et le dossier de données contient .env, settings.json et iris.db : un agent
    envoyé corriger un site n'a pas à lire les clés ElevenLabs."""
    defaut = racines_interdites_par_defaut()
    depot = Path(__file__).resolve().parents[1].parent  # …/iris (le dépôt), depuis backend/tests
    assert depot in defaut, "le dépôt d'IRIS doit être interdit sans qu'on ait à y penser"

    service = contremaitre(atelier)  # liste noire injectée vide : seul le dossier de données reste
    assert atelier.donnees.resolve() in service.racines_interdites()
    with pytest.raises(CheminRefuse):
        resoudre_dossier(str(atelier.donnees), [atelier.racine], service.racines_interdites())


def test_la_racine_dun_disque_et_le_dossier_personnel_sont_refuses(atelier: Atelier):
    """Deux réponses qu'un modèle donne quand il ne sait pas : « C:\\ » et le dossier personnel.
    Les deux reviennent à lâcher un agent sur tout l'ordinateur."""
    with pytest.raises(CheminRefuse) as racine:
        resoudre_dossier(str(Path(atelier.racine.anchor)), [Path(atelier.racine.anchor)])
    assert "racine" in str(racine.value)
    with pytest.raises(CheminRefuse) as maison:
        resoudre_dossier(str(Path.home()), [Path.home()])
    assert "personnel" in str(maison.value)


def test_un_dossier_inexistant_nest_jamais_cree(atelier: Atelier):
    """Sur un nom approximatif, OpenCode travaillerait dans un dossier vide et inventerait un projet."""
    fantome = atelier.projets / "site-flowcar"  # une lettre en moins
    with pytest.raises(CheminRefuse) as refus:
        resoudre_dossier(str(fantome), [atelier.projets])
    assert "trouve pas" in str(refus.value)
    assert not fantome.exists(), "IRIS ne crée pas le dossier qu'elle ne trouve pas"


def test_un_fichier_nest_pas_un_dossier_de_travail(atelier: Atelier):
    with pytest.raises(CheminRefuse) as refus:
        resoudre_dossier(str(atelier.site / "index.html"), [atelier.projets])
    assert "fichier" in str(refus.value)


def test_une_racine_mal_ecrite_ne_desactive_pas_les_autres(atelier: Atelier):
    """settings.json se modifie à la main : une ligne bancale ne doit pas emporter la fonctionnalité."""
    service = contremaitre(atelier, racines=["%NIMPORTEQUOI%", "", str(atelier.projets)])
    assert service.racines() == [atelier.projets.resolve()]


def test_le_chantier_retient_le_chemin_resolu_pas_la_phrase_dite(atelier: Atelier):
    """Tout ce qui suit — l'empreinte, le lancement, le compte rendu — part de ce chemin-là.
    On a mesuré que la chaîne dite et le chemin réel peuvent désigner deux choses différentes."""
    service = contremaitre(atelier, lanceur=FauxLanceur())
    chantier = service.preparer("correction", str(atelier.site / ".." / "site"), CONSIGNE)
    assert chantier.dossier == atelier.site.resolve()
    assert ".." not in str(chantier.dossier)


# --------------------------------------------------------------------------- 3. la serrure
def test_rien_ne_part_sans_autorisation(atelier: Atelier):
    """Si executer() acceptait autre chose qu'une Autorisation, un appelant distrait lancerait un
    agent sur les fichiers de quelqu'un sans que personne n'ait dit oui."""
    lanceur = FauxLanceur()
    service = contremaitre(atelier, lanceur=lanceur)
    chantier = service.preparer("correction", str(atelier.site), CONSIGNE)
    with pytest.raises(AutorisationInvalide):
        service.executer(chantier)  # type: ignore[arg-type]
    with pytest.raises(AutorisationInvalide):
        service.executer(True)  # type: ignore[arg-type]
    assert lanceur.lancements == 0


def test_une_autorisation_ne_se_fabrique_pas_a_la_main(atelier: Atelier):
    """Le sceau privé distingue « confirmé » de « quelqu'un a mis True quelque part »."""
    service = contremaitre(atelier, lanceur=FauxLanceur())
    chantier = service.preparer("correction", str(atelier.site), CONSIGNE)
    with pytest.raises(AutorisationInvalide):
        Autorisation(chantier, object())
    with pytest.raises(TypeError):
        Autorisation(chantier)  # type: ignore[call-arg]


def test_un_accord_ne_sert_quune_fois(atelier: Atelier):
    """Sans ça, un modèle qui boucle relancerait OpenCode dix fois sur un seul oui."""
    lanceur = FauxLanceur()
    service = contremaitre(atelier, lanceur=lanceur)
    accord = accorder(service, service.preparer("correction", str(atelier.site), CONSIGNE))
    assert accord is not None
    service.executer(accord)
    with pytest.raises(AutorisationInvalide):
        service.executer(accord)
    assert lanceur.lancements == 1


def test_un_accord_perime_est_refuse(atelier: Atelier):
    """Un oui donné il y a une heure, retrouvé dans une file d'attente, ne vaut plus rien."""
    lanceur = FauxLanceur()
    service = contremaitre(atelier, lanceur=lanceur)
    accord = accorder(service, service.preparer("correction", str(atelier.site), CONSIGNE))
    assert accord is not None
    accord._accorde_a -= DUREE_ACCORD + 1
    assert accord.utilisable is False
    with pytest.raises(AutorisationInvalide):
        service.executer(accord)
    assert lanceur.lancements == 0


def test_un_accord_donne_pour_un_dossier_ne_vaut_pas_pour_un_autre(atelier: Atelier):
    """LE test de ce fichier. C'est le défaut trouvé dans telephonie.py, transposé : là-bas l'accord
    donné pour un envoi depuis l'iPhone restait valable si la voie basculait sur un service payant.
    Ici la variable est le DOSSIER. Si l'empreinte ne le couvrait pas, un oui pour un petit site
    personnel autoriserait un agent à travailler dans un dépôt de production."""
    lanceur = FauxLanceur()
    service = contremaitre(atelier, lanceur=lanceur)
    ici = service.preparer("correction", str(atelier.site), CONSIGNE)
    ailleurs = service.preparer("correction", str(atelier.autre), CONSIGNE)
    assert ici.empreinte != ailleurs.empreinte, "deux dossiers, deux accords"

    accord = accorder(service, ici)
    assert accord is not None
    # Le détournement réaliste : le chantier approuvé est réutilisé après avoir été rectifié.
    object.__setattr__(accord.chantier, "dossier", atelier.autre.resolve())
    assert accord.utilisable is False
    with pytest.raises(AutorisationInvalide) as refus:
        service.executer(accord)
    assert "changé" in str(refus.value)
    assert lanceur.lancements == 0


def test_un_accord_ne_couvre_ni_une_autre_consigne_ni_une_autre_duree(atelier: Atelier):
    """L'empreinte couvre tout ce que la confirmation a montré : ce qui a été lu est ce qui part."""
    service = contremaitre(atelier, lanceur=FauxLanceur())
    chantier = service.preparer("correction", str(atelier.site), CONSIGNE)
    for champ, valeur in (("consigne", "supprime les tests"), ("duree_max", 3600.0), ("genre", "revue")):
        accord = accorder(service, service.preparer("correction", str(atelier.site), CONSIGNE))
        assert accord is not None
        object.__setattr__(accord.chantier, champ, valeur)
        assert accord.utilisable is False
    assert chantier.empreinte == chantier.calculer_empreinte()


def test_un_refus_ne_lance_aucun_processus(atelier: Atelier):
    """Un non, un silence ou un délai dépassé donnent tous False : rien ne doit démarrer."""
    lanceur = FauxLanceur()
    registre = FauxRegistre()
    service = contremaitre(atelier, lanceur=lanceur, registre=registre)
    chantier = service.preparer("correction", str(atelier.site), CONSIGNE)
    assert accorder(service, chantier, reponse=False) is None
    assert lanceur.lancements == 0
    assert "opencode_refus" in registre.evenements

    async def confirmer_non(_t, _d):
        return False

    resultat = asyncio.run(service.deleguer_apres_accord("correction", str(atelier.site), CONSIGNE, confirmer_non))
    assert resultat["ok"] is False and resultat["modifie"] is False
    assert "rien lancé" in resultat["message"]
    assert lanceur.lancements == 0


def test_sans_moyen_de_confirmer_iris_ne_lance_rien(atelier: Atelier):
    """Si la fenêtre est fermée, il n'y a personne pour dire oui — et donc rien à faire."""
    service = contremaitre(atelier, lanceur=FauxLanceur())
    chantier = service.preparer("correction", str(atelier.site), CONSIGNE)
    with pytest.raises(AutorisationInvalide):
        asyncio.run(service.demander_accord(chantier, None))  # type: ignore[arg-type]


def test_le_perimetre_est_reverifie_au_moment_dagir(atelier: Atelier):
    """Entre l'accord et l'action, la liste des dossiers autorisés a pu changer. Vérifier seulement
    à la préparation laisserait passer un accord devenu caduc."""
    lanceur = FauxLanceur()
    section = ReglagesOpenCode(racines=[str(atelier.projets)])
    settings = FauxSettings(atelier.donnees, opencode=section)
    service = Contremaitre(settings, lanceur=lanceur, chercheur=lambda: BINAIRE, racines_interdites=[])
    accord = accorder(service, service.preparer("correction", str(atelier.site), CONSIGNE))
    assert accord is not None

    section.racines = [str(atelier.autre)]  # Miguel a retiré le dossier entre-temps
    with pytest.raises(CheminRefuse):
        service.executer(accord)
    assert lanceur.lancements == 0
    assert accord.utilisable is True, "un refus de périmètre ne doit pas brûler l'accord"


def test_la_confirmation_nomme_le_dossier_et_avoue_ce_quiris_ne_peut_pas_empecher(atelier: Atelier):
    """Ce qui compte dans cet accord, c'est OÙ. Et la phrase ne doit pas laisser croire à une prison :
    une fois lancé, OpenCode tourne avec les droits de Miguel et peut écrire ailleurs."""
    service = contremaitre(atelier, lanceur=FauxLanceur())
    chantier = service.preparer("correction", str(atelier.site), CONSIGNE)
    vus: list[tuple[str, str]] = []

    async def confirmer(titre: str, detail: str) -> bool:
        vus.append((titre, detail))
        return True

    asyncio.run(service.demander_accord(chantier, confirmer))
    titre, detail = vus[0]
    assert "site" in titre
    assert str(atelier.site) in detail, "le chemin complet doit être lisible, pas seulement le nom"
    assert CONSIGNE in detail
    assert "minutes" in detail, "la durée fait partie de ce qu'on approuve"
    assert "empêcher" in detail and "enferme" in detail


def test_un_dossier_git_sale_est_signale_avant_daccepter(atelier: Atelier):
    """Si l'arbre est déjà sale, « reviens en arrière » ne saura plus distinguer le travail
    d'OpenCode de celui de Miguel. Il doit le savoir avant de dire oui, pas après."""
    propre = contremaitre(atelier, lanceur=FauxLanceur(depot=True, propre=True))
    chantier = propre.preparer("correction", str(atelier.site), CONSIGNE)
    assert chantier.sous_git and chantier.arbre_propre
    assert "revenir en arrière restera possible" in chantier.apercu()

    sale = contremaitre(atelier, lanceur=FauxLanceur(depot=True, propre=False))
    assert "non enregistrées" in sale.preparer("correction", str(atelier.site), CONSIGNE).apercu()

    sans = contremaitre(atelier, lanceur=FauxLanceur(depot=False))
    chantier_sans = sans.preparer("correction", str(atelier.site), CONSIGNE)
    assert chantier_sans.sous_git is False
    assert "pas sous git" in chantier_sans.apercu()


def test_une_consigne_vide_est_refusee(atelier: Atelier):
    """Un agent envoyé sans consigne fait ce qu'il croit utile. C'est comme ça qu'un site marche
    moins bien après."""
    service = contremaitre(atelier, lanceur=FauxLanceur())
    with pytest.raises(ErreurOpenCode):
        service.preparer("correction", str(atelier.site), "   ")


# --------------------------------------------------------------------------- 4. le compte rendu
def test_iris_dit_franchement_quand_opencode_na_rien_modifie(atelier: Atelier):
    """C'est le compte rendu le plus facile à maquiller en réussite. Si cette phrase se ramollissait,
    Miguel croirait son bogue corrigé et ne le vérifierait pas."""
    service = contremaitre(atelier, lanceur=FauxLanceur(code=0))
    accord = accorder(service, service.preparer("correction", str(atelier.site), CONSIGNE))
    compte = service.executer(accord)  # type: ignore[arg-type]
    assert compte["termine"] is True
    assert compte["modifie"] is False
    assert compte["nb_changements"] == 0
    assert "sans rien modifier" in compte["message"]


def test_les_fichiers_touches_sont_nommes_dans_le_compte_rendu(atelier: Atelier):
    """Sans git — le cas courant : les projets de ~/Documents/IRIS n'en ont aucun — c'est la seule
    façon de répondre à « qu'est-ce qu'elle a changé hier ? »."""

    def travail(dossier: Path) -> None:
        (dossier / "index.html").write_text("<h1>bonjour tout le monde</h1>", encoding="utf-8")
        (dossier / "panier.js").write_text("// corrigé", encoding="utf-8")
        (dossier / "style.css").unlink()

    service = contremaitre(atelier, lanceur=FauxLanceur(effet=travail))
    accord = accorder(service, service.preparer("correction", str(atelier.site), CONSIGNE))
    compte = service.executer(accord)  # type: ignore[arg-type]
    assert compte["ok"] is True and compte["modifie"] is True
    assert compte["changements"]["modifies"] == ["index.html"]
    assert compte["changements"]["ajoutes"] == ["panier.js"]
    assert compte["changements"]["supprimes"] == ["style.css"]
    assert "1 fichier modifié" in compte["message"] and "site" in compte["message"]


def test_un_echec_nest_jamais_presente_comme_une_reussite(atelier: Atelier):
    """Et il doit dire ce qui a quand même été écrit : un plantage n'annule rien sur le disque."""
    lanceur = FauxLanceur(code=1, sortie="Error: cannot read package.json", effet=ecrire("brouillon.js", "à moitié"))
    service = contremaitre(atelier, lanceur=lanceur)
    accord = accorder(service, service.preparer("correction", str(atelier.site), CONSIGNE))
    compte = service.executer(accord)  # type: ignore[arg-type]
    assert compte["ok"] is False and compte["termine"] is False
    assert "erreur" in compte["message"]
    assert "reste en place" in compte["message"]
    assert "package.json" in compte["message"]


def test_le_delai_depasse_dit_ce_qui_a_change_et_que_rien_na_ete_annule(atelier: Atelier):
    """Un délai dépassé n'est ni une réussite ni une annulation. Le raconter autrement laisserait
    Miguel croire son dossier intact alors que des fichiers ont déjà été réécrits."""
    lanceur = FauxLanceur(expire=True, effet=ecrire("index.html", "<h1>travail interrompu en plein milieu</h1>"))
    service = contremaitre(atelier, lanceur=lanceur)
    accord = accorder(service, service.preparer("correction", str(atelier.site), CONSIGNE))
    compte = service.executer(accord)  # type: ignore[arg-type]
    assert compte["expire"] is True and compte["ok"] is False and compte["termine"] is False
    assert compte["modifie"] is True
    assert "pas fini" in compte["message"]
    assert "Rien n'a été annulé" in compte["message"]
    assert lanceur.appels[-1]["delai"] == pytest.approx(600.0), "le délai doit être imposé au lancement"


def test_un_delai_depasse_sans_aucune_ecriture_le_dit_aussi(atelier: Atelier):
    service = contremaitre(atelier, lanceur=FauxLanceur(expire=True))
    accord = accorder(service, service.preparer("correction", str(atelier.site), CONSIGNE))
    compte = service.executer(accord)  # type: ignore[arg-type]
    assert "n'avait encore rien modifié" in compte["message"]


def test_un_binaire_disparu_entre_laccord_et_laction_se_dit(atelier: Atelier):
    """Désinstallation, antivirus, session changée : ça se raconte, ça ne remonte pas en trace."""
    service = contremaitre(atelier, lanceur=FauxLanceur(introuvable=True))
    accord = accorder(service, service.preparer("correction", str(atelier.site), CONSIGNE))
    compte = service.executer(accord)  # type: ignore[arg-type]
    assert compte["ok"] is False
    assert "disparu" in compte["message"] and "Rien n'a été fait" in compte["message"]


def test_un_commit_est_repere_meme_quand_aucun_fichier_ne_bouge(atelier: Atelier):
    """L'inventaire ignore .git volontairement : sinon un commit ferait bouger des centaines de
    fichiers internes. Mais alors un travail entièrement enregistré passerait pour « rien fait »."""
    lanceur = FauxLanceur(depot=True, tetes=("aaaaaa", "bbbbbb"))
    service = contremaitre(atelier, lanceur=lanceur)
    accord = accorder(service, service.preparer("correction", str(atelier.site), CONSIGNE))
    compte = service.executer(accord)  # type: ignore[arg-type]
    assert compte["commit"] is True and compte["modifie"] is True
    assert "commit" in compte["message"]


def test_le_dossier_de_travail_est_celui_qui_a_ete_approuve(atelier: Atelier):
    """Le lancement se fait DANS le dossier résolu — c'est ce qui épingle OpenCode, pas une option
    de ligne de commande dont le nom n'a jamais pu être vérifié faute de binaire sur la machine."""
    lanceur = FauxLanceur()
    service = contremaitre(atelier, lanceur=lanceur)
    accord = accorder(service, service.preparer("correction", str(atelier.site), CONSIGNE))
    service.executer(accord)  # type: ignore[arg-type]
    lancement = [a for a in lanceur.appels if a["argv"][:1] != ["git"]][0]
    assert Path(lancement["dossier"]) == atelier.site.resolve()
    assert lancement["argv"][0] == BINAIRE
    assert CONSIGNE in lancement["argv"]


def test_un_dossier_trop_gros_est_annonce_comme_partiellement_inspecte(atelier: Atelier):
    """Mieux vaut dire « je n'ai pas tout vu » que laisser croire à un inventaire complet."""
    for i in range(5):
        (atelier.site / f"f{i}.txt").write_text("x", encoding="utf-8")
    photo, complet = inventaire(atelier.site, max_fichiers=3)
    assert complet is False and len(photo) <= 3


def test_linventaire_ignore_les_dossiers_qui_ne_sont_pas_du_travail(atelier: Atelier):
    """node_modules et .git bougent tout le temps sans que ce soit « ce qu'OpenCode a modifié »."""
    (atelier.site / "node_modules").mkdir()
    (atelier.site / "node_modules" / "paquet.js").write_text("x", encoding="utf-8")
    (atelier.site / ".git").mkdir()
    (atelier.site / ".git" / "HEAD").write_text("ref: main", encoding="utf-8")
    photo, _ = inventaire(atelier.site)
    assert set(photo) == {"index.html", "style.css"}


def test_comparer_distingue_les_trois_sortes_de_changement():
    """Ajouté, modifié, supprimé : trois phrases différentes pour Miguel, trois listes ici."""
    avant = {"a.py": (10, 1), "b.py": (20, 2), "c.py": (30, 3)}
    apres = {"a.py": (10, 1), "b.py": (99, 9), "d.py": (5, 5)}
    assert comparer(avant, apres) == {"ajoutes": ["d.py"], "modifies": ["b.py"], "supprimes": ["c.py"]}


# --------------------------------------------------------------------------- 5. politique et traces
def test_la_politique_imposee_interdit_le_partage_et_la_sortie_du_dossier(atelier: Atelier):
    """« share » vaut « manual » par défaut chez OpenCode : le code d'un client pourrait devenir une
    page web publique. Et webfetch fermé, parce qu'un agent qui va chercher sur le web peut aussi
    y envoyer."""
    politique = politique_iris()
    assert politique["share"] == "disabled"
    assert politique["permission"]["external_directory"] == "deny"
    assert politique["permission"]["webfetch"] == "deny"


def test_la_politique_passe_par_lenvironnement_et_jamais_par_le_fichier_de_miguel(atelier: Atelier):
    """~/.config/opencode/opencode.jsonc appartient à Miguel. IRIS impose sa politique le temps d'un
    processus, par OPENCODE_CONFIG_CONTENT, et ne touche pas à ses réglages."""
    lanceur = FauxLanceur()
    service = contremaitre(atelier, lanceur=lanceur)
    accord = accorder(service, service.preparer("correction", str(atelier.site), CONSIGNE))
    service.executer(accord)  # type: ignore[arg-type]
    lancement = [a for a in lanceur.appels if a["argv"][:1] != ["git"]][0]
    envoyee = json.loads(lancement["env"]["OPENCODE_CONFIG_CONTENT"])
    assert envoyee == politique_iris()


def test_le_journal_dintervention_est_ecrit_avant_le_lancement(atelier: Atelier):
    """Si IRIS est fermée pendant qu'OpenCode travaille, il doit rester sur le disque de quoi dire
    ce qu'elle a lancé, où et pourquoi."""
    vu: dict = {}

    def observer(_dossier) -> None:
        fiches = list((atelier.donnees / "opencode").glob("*/chantier.json"))
        vu["au_lancement"] = [f.read_text(encoding="utf-8") for f in fiches]

    service = contremaitre(atelier, lanceur=FauxLanceur(au_lancement=observer))
    accord = accorder(service, service.preparer("correction", str(atelier.site), CONSIGNE))
    compte = service.executer(accord)  # type: ignore[arg-type]

    assert vu["au_lancement"], "le chantier doit être sur le disque AVANT qu'OpenCode démarre"
    fiche = json.loads(vu["au_lancement"][0])
    assert fiche["dossier"] == str(atelier.site.resolve()) and fiche["consigne"] == CONSIGNE
    rendu = json.loads((Path(compte["journal"]) / "compte-rendu.json").read_text(encoding="utf-8"))
    assert rendu["message"] == compte["message"]


def test_un_journal_impossible_a_ecrire_nempeche_pas_de_rendre_compte(atelier: Atelier):
    """Une trace qui échoue ne doit pas priver Miguel de sa réponse."""
    settings = FauxSettings(atelier.donnees / "index.html", opencode=ReglagesOpenCode(racines=[str(atelier.projets)]))
    (atelier.donnees / "index.html").write_text("je suis un fichier, pas un dossier", encoding="utf-8")
    service = Contremaitre(settings, lanceur=FauxLanceur(), chercheur=lambda: BINAIRE, racines_interdites=[])
    accord = accorder(service, service.preparer("correction", str(atelier.site), CONSIGNE))
    compte = service.executer(accord)  # type: ignore[arg-type]
    assert compte["message"] and compte["journal"] == ""


def test_le_registre_garde_la_trace_du_refus_comme_du_travail(atelier: Atelier):
    """Un journal qui ne montre que les succès ne prouve rien."""
    registre = FauxRegistre()
    service = contremaitre(atelier, lanceur=FauxLanceur(), registre=registre)
    accorder(service, service.preparer("correction", str(atelier.site), CONSIGNE), reponse=False)
    accord = accorder(service, service.preparer("correction", str(atelier.site), CONSIGNE))
    service.executer(accord)  # type: ignore[arg-type]
    assert registre.evenements == ["opencode_refus", "opencode_delegue", "opencode_termine"]
    assert all(str(atelier.site.resolve()) in detail for _e, _a, detail in registre.entrees)


def test_la_consigne_nest_pas_recopiee_en_entier_dans_le_registre(atelier: Atelier):
    """Le registre s'exporte en CSV, se lit à l'écran, et n'est pas chiffré. Ce qu'il doit prouver,
    c'est OÙ IRIS a envoyé un agent, pas ce que Miguel lui a demandé mot pour mot."""
    registre = FauxRegistre()
    service = contremaitre(atelier, lanceur=FauxLanceur(), registre=registre)
    secrete = "remplace le mot de passe hunter2 dans la configuration"
    accord = accorder(service, service.preparer("correction", str(atelier.site), secrete))
    service.executer(accord)  # type: ignore[arg-type]
    assert not any("hunter2" in detail for _e, _a, detail in registre.entrees)


def test_un_registre_en_panne_nempeche_pas_de_travailler(atelier: Atelier):
    class RegistreCasse:
        def log(self, *_a, **_k):
            raise RuntimeError("base verrouillée")

    service = contremaitre(atelier, lanceur=FauxLanceur(), registre=RegistreCasse())
    accord = accorder(service, service.preparer("correction", str(atelier.site), CONSIGNE))
    assert service.executer(accord)["message"]  # type: ignore[arg-type]


# --------------------------------------------------------------------------- 6. la voix
def test_une_demande_dictee_renvoie_a_lecran_sans_ouvrir_de_modale_invisible(atelier: Atelier):
    """Rien dans backend/iris/voice/ n'écoute « chat.confirm » : une confirmation demandée à la voix
    s'afficherait sur un écran que personne ne regarde, puis expirerait au bout de 180 secondes sur
    un « refusé » silencieux. Autant le dire tout de suite, à voix haute, où il l'entendra."""
    lanceur = FauxLanceur()
    service = contremaitre(atelier, lanceur=lanceur)
    modales: list = []

    async def confirmer(titre: str, detail: str) -> bool:
        modales.append(titre)
        return True

    compte = asyncio.run(
        service.deleguer_apres_accord("correction", str(atelier.site), CONSIGNE, confirmer, source="voice")
    )
    assert modales == [], "aucune modale ne doit s'ouvrir pour une demande dictée"
    assert lanceur.lancements == 0
    assert "valides à l'écran" in compte["message"]
    assert compte["ok"] is False and compte["modifie"] is False


def test_la_meme_demande_ecrite_passe_par_la_confirmation_normale(atelier: Atelier):
    """Le contre-exemple du test précédent : au clavier, la modale existe et le travail se fait."""
    lanceur = FauxLanceur(effet=ecrire("index.html", "<h1>corrigé pour de bon</h1>"))
    service = contremaitre(atelier, lanceur=lanceur)
    modales: list = []

    async def confirmer(titre: str, _detail: str) -> bool:
        modales.append(titre)
        return True

    compte = asyncio.run(
        service.deleguer_apres_accord("correction", str(atelier.site), CONSIGNE, confirmer, source="text")
    )
    assert len(modales) == 1 and lanceur.lancements == 1
    assert compte["ok"] is True and compte["modifie"] is True
