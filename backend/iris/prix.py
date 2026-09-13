"""Comparer les prix : ce produit, combien ailleurs au Canada ?

Pensé pour l'allée d'un magasin : l'utilisateur montre un produit aux lunettes (ou tape son nom) et IRIS
dit, en une ou deux phrases, les prix trouvés en ligne. Ce que le module promet, et ce qu'il ne promet pas :

- Identification : la vision d'accessibilité (mode « objet ») lit le nom, la marque, le format, les
  chiffres du code-barres s'ils sont lisibles et le prix affiché. Rien n'est deviné : un champ incertain
  reste vide, et un produit non identifié est refusé (reprendre la photo ou taper le nom).
- Recherche : une requête à l'API de recherche web d'IRIS (recherche_web.py), jamais le grattage d'un
  moteur. Les prix viennent des EXTRAITS de résultats, lus sur l'ordinateur par des règles : montant en
  dollars, devise canadienne (marqueur CA/CAD, site .ca ou marchand canadien connu), pas un rabais, un
  prix barré, des frais de livraison ou un prix au kilo. Une offre est gardée par marchand (la plus
  basse), les montants aberrants (accessoire, lot) sont écartés quand il y a de quoi comparer.
- Honnêteté : un extrait de recherche peut dater de quelques jours, et le prix comme le stock en
  magasin peuvent différer. La réponse le dit toujours (`avertissement`), et le résumé vocal aussi.
- Confidentialité : la requête quitte l'ordinateur (consentement « Texte de vos demandes », journalisé) ;
  la photo passe par la vision, qui vérifie « Images jointes ». Refus en mode 100 % local et en mode
  confidentiel. Rien n'est conservé par ce module.

Service exposé sous ctx.prix (voir routes_assistants.py).
"""
from __future__ import annotations

import asyncio
import logging
import re
import statistics
import time
from typing import Any, Callable
from urllib.parse import urlparse

from fastapi import HTTPException

from . import recherche_web
from .pas_a_pas import normaliser

log = logging.getLogger("iris.prix")

OFFRES_MAX = 8
RESULTATS_PAR_RECHERCHE = 8
PRIX_MIN, PRIX_MAX = 0.25, 100_000.0

AVERTISSEMENT = (
    "Prix trouvés en ligne à l'instant, à vérifier : le prix et le stock en magasin peuvent différer, et un extrait "
    "de recherche peut dater de quelques jours."
)
CONFIDENTIEL = "Le mode confidentiel est actif : IRIS ne prend aucune photo et ne cherche aucun prix tant qu'il l'est."
LOCAL_SEULEMENT = (
    "Le mode 100 % local est actif : comparer des prix exige une recherche sur le web, qui quitte l'ordinateur. "
    "Désactivez ce mode dans Confidentialité pour utiliser cette fonction."
)
NON_CONFIGUREE = (
    "La recherche web n'est pas configurée sur cet ordinateur : IRIS ne peut pas comparer les prix en ligne."
)
RESEAU = "La recherche web est injoignable : vérifiez la connexion Internet, puis réessayez."
REFUSEE = "Le service de recherche web a refusé la demande (clé invalide ou quota atteint). Réessayez plus tard."
VISION_ABSENTE = (
    "L'identification du produit par photo n'est pas disponible sur cet ordinateur : tapez le nom du produit."
)
NON_IDENTIFIE = (
    "Je n'ai pas pu identifier le produit sur la photo : reprenez-la plus près, l'étiquette bien visible, ou tapez "
    "le nom du produit."
)

QUESTION_PRODUIT = (
    "Pour comparer les prix en ligne : identifie le produit au centre de l'image. Réponds exactement en cinq lignes, "
    "sans rien d'autre : « NOM : … », « MARQUE : … », « FORMAT : … », « CODE-BARRES : … » (chiffres lus "
    "seulement), « PRIX AFFICHÉ : … ». Écris « inconnu » pour ce qui n'est pas visible ou pas certain ; ne devine "
    "jamais."
)

# Marchands canadiens connus (domaine -> nom affiché). Sert au nom lisible ET à la devise : un « $ » nu sur
# ces sites est un dollar canadien. Un site hors liste compte seulement s'il est en .ca ou marque CA/CAD.
MARCHANDS: dict[str, str] = {
    "walmart.ca": "Walmart", "bestbuy.ca": "Best Buy", "canadiantire.ca": "Canadian Tire", "amazon.ca": "Amazon.ca",
    "costco.ca": "Costco", "staples.ca": "Staples", "bureauengros.com": "Bureau en Gros",
    "homedepot.ca": "Home Depot", "rona.ca": "Rona", "renodepot.com": "Réno-Dépôt", "canac.ca": "Canac",
    "bmr.co": "BMR", "patrickmorin.com": "Patrick Morin", "iga.net": "IGA", "metro.ca": "Metro", "maxi.ca": "Maxi",
    "provigo.ca": "Provigo", "loblaws.ca": "Loblaws", "superc.ca": "Super C", "nofrills.ca": "No Frills",
    "realcanadiansuperstore.ca": "Real Canadian Superstore", "sobeys.com": "Sobeys", "safeway.ca": "Safeway",
    "foodbasics.ca": "Food Basics", "pharmaprix.ca": "Pharmaprix", "shoppersdrugmart.ca": "Shoppers Drug Mart",
    "jeancoutu.com": "Jean Coutu", "uniprix.com": "Uniprix", "familiprix.com": "Familiprix", "brunet.ca": "Brunet",
    "londondrugs.com": "London Drugs", "thebay.com": "La Baie d'Hudson", "labaie.com": "La Baie d'Hudson",
    "simons.ca": "Simons", "sportchek.ca": "Sport Chek", "sail.ca": "SAIL", "decathlon.ca": "Decathlon",
    "visions.ca": "Visions Électronique", "memoryexpress.com": "Memory Express",
    "canadacomputers.com": "Canada Computers", "newegg.ca": "Newegg Canada", "indigo.ca": "Indigo",
    "renaud-bray.com": "Renaud-Bray", "archambault.ca": "Archambault", "toysrus.ca": "Toys R Us",
    "gianttiger.com": "Giant Tiger", "dollarama.com": "Dollarama", "well.ca": "Well.ca", "structube.com": "Structube",
    "leons.ca": "Leon's", "thebrick.com": "The Brick", "bouclair.com": "Bouclair", "ebay.ca": "eBay Canada",
    "ikea.com": "IKEA",
}
# Ces domaines .com servent aussi d'autres pays : canadiens seulement avec /ca/ ou en-ca / fr-ca dans l'adresse.
_MARCHANDS_A_CHEMIN = {"ikea.com", "thebay.com"}

_MONTANT = r"(?:\d{1,3}(?:[ \u00a0\u202f,]\d{3})+|\d+)(?:[.,]\d{2})?"
_PRIX = re.compile(
    r"(?P<pre>\b(?:CA|C|CAD|US|USD)\s?\$|\$(?:\s?(?:CA|CAD|US|USD)\b)?|\b(?:CAD|USD)\b)\s?(?P<m1>" + _MONTANT + r")(?![\d,.]*\d)"
    r"|(?<![\d.,])(?P<m2>" + _MONTANT + r")\s?(?P<post>\$(?:\s?(?:CA|CAD|US|USD)\b)?|\b(?:CAD|USD)\b)",
    re.IGNORECASE,
)
# Mots juste AVANT un montant qui disent que ce n'est pas le prix payé maintenant.
_AVANT_EXCLU = ("economisez", "economie", "epargnez", "save", "rabais de", "livraison", "shipping", "frais", "jusqu a",
                "up to", "gagnez", "carte cadeau", "gift card", "regulier", "reg", "was", "etait", "msrp", "suggere",
                "list price", "remise de", "coupon", "points", "financement", "plus de", "over", "moins de", "under",
                "de plus de", "commandes de", "achat de", "orders over")
_APRES_EXCLU = ("de rabais", "off", "par mois", "per month", "de moins", "d economie", "de reduction", "en points")
_INCONNUS = ("inconnu", "inconnue", "non visible", "pas visible", "illisible", "aucun", "aucune", "n a", "na",
             "non lisible", "pas sure", "pas sur", "je ne suis pas sure", "non", "rien")
_ETIQUETTES = {"nom": "nom", "produit": "nom", "nom du produit": "nom", "marque": "marque", "format": "format",
               "quantite": "format", "code barres": "code_barres", "code barre": "code_barres",
               "prix affiche": "prix_vu", "prix": "prix_vu"}
_MOTS_VIDES = {"les", "des", "pour", "avec", "sans", "une", "prix", "canada", "format", "paquet", "the", "and", "for",
               "with", "inconnu", "produit", "boite", "sac", "unite", "unites"}


class RefusPrix(HTTPException):
    """Refus documenté : un HTTPException avec sa phrase courte à dire à voix haute."""

    def __init__(self, statut: int, message: str, detail: Any = None, phrase: str | None = None):
        super().__init__(status_code=statut, detail=detail if detail is not None else message)
        self.message = message
        self.phrase = phrase or message


# =============================================================================== lecture
def valeur_montant(brut: str) -> float | None:
    texte = (brut or "").replace("\u00a0", " ").replace("\u202f", " ").strip()
    m = re.match(r"^(.*?)(?:[.,](\d{2}))?$", texte)
    if not m:
        return None
    entier = re.sub(r"[ ,.]", "", m.group(1))
    if not entier.isdigit():
        return None
    return round(float(f"{entier}.{m.group(2) or '00'}"), 2)


def montant_parle(valeur: float) -> str:
    """« 39,99 $ », « 40 $ » : la forme lue à voix haute."""
    if abs(valeur - round(valeur)) < 0.005:
        return f"{int(round(valeur))} $"
    return f"{valeur:.2f}".replace(".", ",") + " $"


def hote(url: str) -> str:
    try:
        nom = (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""
    return nom[4:] if nom.startswith("www.") else nom


def _domaine_connu(nom_hote: str) -> str | None:
    for domaine in MARCHANDS:
        if nom_hote == domaine or nom_hote.endswith("." + domaine):
            return domaine
    return None


def site_canadien(url: str) -> bool:
    nom_hote = hote(url)
    if not nom_hote:
        return False
    if nom_hote.endswith(".ca"):
        return True
    domaine = _domaine_connu(nom_hote)
    if domaine is None:
        return False
    if domaine in _MARCHANDS_A_CHEMIN:
        chemin = (url or "").lower()
        return any(m in chemin for m in ("/ca/", "en-ca", "fr-ca", "/ca-"))
    return True


def nom_marchand(url: str) -> str:
    nom_hote = hote(url)
    domaine = _domaine_connu(nom_hote)
    if domaine:
        return MARCHANDS[domaine]
    morceaux = [m for m in nom_hote.split(".") if m]
    if len(morceaux) >= 2:
        return morceaux[-2].replace("-", " ").title()
    return nom_hote or "Marchand inconnu"


def devise(prefixe: str, suffixe: str, url: str) -> str | None:
    """« CAD », « USD », ou None quand un « $ » nu vient d'un site qui n'est pas reconnu comme canadien."""
    marques = set(normaliser(f"{prefixe or ''} {suffixe or ''}").split())
    if marques & {"us", "usd"}:
        return "USD"
    if marques & {"ca", "cad", "c"}:
        return "CAD"
    return "CAD" if site_canadien(url) else None


def _derniers_mots(texte: str, n: int = 3) -> str:
    mots = [m for m in normaliser(texte).split() if not m.isdigit()]
    return " ".join(mots[-n:])


def prix_dans(texte: str, url: str) -> list[tuple[float, int, int]]:
    """[(prix CAD, début, fin)] des montants qui sont vraisemblablement un prix payé maintenant."""
    trouves: list[tuple[float, int, int]] = []
    fin_precedente = 0
    for m in _PRIX.finditer(texte or ""):
        # Le contexte d'un montant s'arrête au montant précédent : dans « Prix régulier 59,99 $ Prix spécial
        # 44,99 $ », « régulier » qualifie 59,99 $, pas 44,99 $.
        contexte = texte[max(fin_precedente, m.start() - 40):m.start()]
        fin_precedente = m.end()
        brut = m.group("m1") or m.group("m2")
        valeur = valeur_montant(brut)
        if valeur is None or not PRIX_MIN <= valeur <= PRIX_MAX:
            continue
        if devise(m.group("pre") or "", m.group("post") or "", url) != "CAD":
            continue
        avant = f" {_derniers_mots(contexte)} "
        if any(f" {mot} " in avant for mot in _AVANT_EXCLU):
            continue
        suite = texte[m.end():m.end() + 16]
        if re.match(r"\s*/", suite):
            continue  # prix au kilo, par mois, par 100 g
        debut_suite = " ".join(normaliser(suite).split()[:2])
        if any(debut_suite.startswith(mot) for mot in _APRES_EXCLU):
            continue
        trouves.append((valeur, m.start(), m.end()))
    return trouves


def lire_produit(texte: str) -> dict:
    """{nom, marque, format, code_barres, prix_vu} depuis la réponse en lignes « NOM : … ». Rien de deviné."""
    produit: dict[str, Any] = {"nom": None, "marque": None, "format": None, "code_barres": None, "prix_vu": None}
    # Une réponse sur une seule ligne (« NOM : X, MARQUE : Y ») est redécoupée avant chaque étiquette.
    decoupe = re.sub(r"\s*\b(?=(?:nom|marque|format|code[- ]?barres?|prix affich[ée]e?)\s*[:：])", "\n",
                     texte or "", flags=re.IGNORECASE)
    for ligne in decoupe.splitlines():
        m = re.match(r"^\s*[-*•«\"]*\s*([^:：]{2,24}?)\s*[:：]\s*(.+?)\s*$", ligne)
        if not m:
            continue
        cle = _ETIQUETTES.get(normaliser(m.group(1)))
        if not cle or produit[cle] is not None:
            continue
        valeur = m.group(2).strip().strip("«»\"'").strip(" ,;.").strip()
        norme = normaliser(valeur)
        if not norme or norme in _INCONNUS or norme.startswith(("inconnu", "non visible", "pas visible", "illisible",
                                                                 "je ne suis pas", "aucun", "non lisible")):
            continue
        if cle == "code_barres":
            chiffres = re.sub(r"\D", "", valeur)
            produit[cle] = chiffres if len(chiffres) in (8, 12, 13, 14) else None
        elif cle == "prix_vu":
            montants = [valeur_montant(x.group(0)) for x in re.finditer(_MONTANT, valeur)]
            montants = [x for x in montants if x is not None and PRIX_MIN <= x <= PRIX_MAX]
            produit[cle] = montants[0] if montants else None
        else:
            produit[cle] = valeur[:120]
    return produit


def designation(produit: dict) -> str:
    nom = produit.get("nom") or ""
    marque = produit.get("marque") or ""
    base = nom if (not marque or normaliser(marque) in normaliser(nom)) else f"{marque} {nom}"
    fmt = produit.get("format") or ""
    if fmt and normaliser(fmt) not in normaliser(base):
        base = f"{base} {fmt}"
    return " ".join(base.split())


def construire_requetes(produit: dict, precision: str | None = None) -> list[str]:
    base = designation(produit)
    if precision and normaliser(precision) not in normaliser(base):
        base = f"{base} {precision}"
    requetes = [f"{base} prix Canada"]
    if produit.get("code_barres"):
        requetes.append(f"{produit['code_barres']} prix")
    return requetes


def mots_cles(produit: dict) -> list[str]:
    mots = normaliser(f"{produit.get('marque') or ''} {produit.get('nom') or ''}").split()
    return list(dict.fromkeys(m for m in mots if len(m) >= 3 and m not in _MOTS_VIDES and not m.isdigit()))


def mots_marque(produit: dict) -> list[str]:
    """Mots qui désignent la marque ou le modèle : la marque lue, sinon les mots à majuscule (hors premier mot)
    ou mêlant lettres et chiffres du nom (« Oster », « WH-1000XM5 »). Une fiche en anglais ne partage souvent
    que ceux-là avec une requête en français."""
    if produit.get("marque"):
        return [m for m in normaliser(produit["marque"]).split() if len(m) >= 2]
    mots = re.findall(r"[^\W_]+", produit.get("nom") or "")
    retenus = [m for i, m in enumerate(mots)
               if (i > 0 and any(c.isupper() for c in m)) or (re.search(r"\d", m) and re.search(r"[^\W\d_]", m))]
    return [normaliser(m) for m in retenus if len(normaliser(m)) >= 2]


def pertinent(resultat: dict, mots: list[str], code_barres: str | None, marque: list[str] | None = None) -> bool:
    """Le résultat parle-t-il de CE produit ? Le code-barres, la marque (ou le modèle), ou au moins deux mots-clés
    (tous s'il y en a moins)."""
    texte = normaliser(f"{resultat.get('titre') or ''} {resultat.get('extrait') or ''} {resultat.get('url') or ''}")
    if code_barres and code_barres in texte.replace(" ", ""):
        return True
    if marque and any(f" {m} " in f" {texte} " for m in marque):
        return True
    if not mots:
        return True
    return sum(1 for m in mots if m in texte) >= min(2, len(mots))


def extraire_offres(resultats: list[dict], produit: dict) -> list[dict]:
    """Une offre par résultat pertinent : le premier prix payé maintenant de l'extrait (ou du titre)."""
    mots = mots_cles(produit)
    marque = mots_marque(produit)
    offres: list[dict] = []
    for r in resultats or []:
        url = (r.get("url") or "").strip()
        if not url.lower().startswith(("http://", "https://")):
            continue  # une réponse résumée sans source ne se vérifie pas : jamais une offre
        if not pertinent(r, mots, produit.get("code_barres"), marque):
            continue
        for champ in ("extrait", "titre"):
            texte = " ".join(str(r.get(champ) or "").split())
            trouves = prix_dans(texte, url)
            if not trouves:
                continue
            valeur, debut, fin = trouves[0]
            gauche, droite = max(0, debut - 90), min(len(texte), fin + 60)
            extrait = ("…" if gauche > 0 else "") + texte[gauche:droite].strip() + ("…" if droite < len(texte) else "")
            offres.append({"marchand": nom_marchand(url), "prix": valeur, "devise": "CAD", "url": url,
                           "extrait": extrait, "titre": (r.get("titre") or "").strip()[:160]})
            break
    return offres


def trier_offres(offres: list[dict], prix_vu: float | None = None) -> tuple[list[dict], int]:
    """(offres dédupliquées par marchand, triées du moins cher au plus cher, bornées ; nombre écartées).

    Un montant trois fois plus bas ou plus haut que la référence est écarté : c'est presque toujours un
    accessoire, une pièce ou un lot. La référence est le prix vu sur place s'il a été lu, sinon la médiane
    (seulement à partir de trois offres : à deux, rien ne dit laquelle se trompe).

    Le filtre passe AVANT le dédoublonnage : sinon le tiroir ramasse-miettes à 4,99 $ d'un marchand
    remplacerait, comme « offre la plus basse », le grille-pain du même marchand."""
    reference = prix_vu or (statistics.median(o["prix"] for o in offres) if len(offres) >= 3 else None)
    plausibles = [o for o in offres if reference / 3 <= o["prix"] <= reference * 3] if reference else list(offres)
    par_marchand: dict[str, dict] = {}
    for o in plausibles:
        cle = hote(o["url"]) or o["marchand"]
        if cle not in par_marchand or o["prix"] < par_marchand[cle]["prix"]:
            par_marchand[cle] = o
    uniques = sorted(par_marchand.values(), key=lambda o: o["prix"])
    return uniques[:OFFRES_MAX], len(offres) - min(len(uniques), OFFRES_MAX)


def resume_vocal(produit: dict, offres: list[dict]) -> str:
    nom = designation(produit) or "ce produit"
    prix_vu = produit.get("prix_vu")
    if not offres:
        phrase = f"Je n'ai trouvé aucun prix en ligne au Canada pour {nom}."
    elif len(offres) == 1:
        o = offres[0]
        phrase = f"{nom} : un seul prix trouvé en ligne, {montant_parle(o['prix'])} chez {o['marchand']}."
    else:
        bas, haut = offres[0], offres[-1]
        phrase = (f"{nom} : {len(offres)} prix trouvés en ligne. Le plus bas : {montant_parle(bas['prix'])} chez "
                  f"{bas['marchand']} ; le plus haut : {montant_parle(haut['prix'])} chez {haut['marchand']}.")
    if prix_vu:
        phrase += f" Prix vu sur place : {montant_parle(prix_vu)}."
    if offres:
        phrase += " Prix en ligne à vérifier : le magasin peut différer."
    return phrase


# =============================================================================== service
class ServicePrix:
    def __init__(self, ctx: Any):
        self.ctx = ctx
        # Fabrique remplaçable (tests) : la vraie passe par l'API de recherche configurée d'IRIS.
        self.fabrique_recherche: Callable[[], Any] = lambda: recherche_web.ClientRecherche(ctx.secrets)

    async def dire(self, texte: str) -> None:
        tts = getattr(self.ctx, "tts", None)
        if tts is None or not texte or getattr(self.ctx.settings.user, "privacy_mode", False):
            return
        try:
            await asyncio.to_thread(tts.speak, texte, True)
        except Exception as exc:  # pragma: no cover
            log.debug("lecture à voix haute impossible : %s", exc)

    def _verifier_envoi_texte(self) -> None:
        """La requête quitte l'ordinateur : consentement « Texte de vos demandes ». Lève RefusPrix 403 / 409."""
        from .consent import DATA_TYPES, ConsentRequired, LocalOnlyMode

        try:
            self.ctx.consent.check("transcript")
        except ConsentRequired as exc:
            libelle = DATA_TYPES.get(exc.data_type, {}).get("label", exc.data_type)
            message = (f"Pour chercher des prix en ligne, IRIS doit envoyer le nom du produit à la recherche web. "
                       f"Autorisez « {libelle} » dans Confidentialité, puis réessayez.")
            raise RefusPrix(403, message, detail={"code": "consentement", "data_type": exc.data_type,
                                                  "label": libelle, "message": message},
                            phrase=f"Je ne peux pas chercher sans ton accord : autorise « {libelle} » dans Confidentialité.")
        except LocalOnlyMode:
            raise RefusPrix(409, LOCAL_SEULEMENT, phrase="Le mode 100 % local est actif : je ne peux pas chercher en ligne.")

    async def _identifier(self, source: str, image: Any) -> tuple[dict, str]:
        acces = getattr(self.ctx, "accessibilite", None)
        if acces is None or not callable(getattr(acces, "decrire", None)):
            raise RefusPrix(409, VISION_ABSENTE, phrase="Je ne peux pas identifier le produit par la caméra ici.")
        resultat = await acces.decrire("objet", source, image=image, question=QUESTION_PRODUIT,
                                       parler=False, memoriser=False)
        texte = (resultat.get("texte") or "").strip()
        return lire_produit(texte), texte

    async def _chercher(self, client: Any, requetes: list[str], produit: dict) -> tuple[list[dict], int, int]:
        offres: list[dict] = []
        faites = 0
        for i, requete in enumerate(requetes[:2]):
            if i > 0 and len(trier_offres(offres, produit.get("prix_vu"))[0]) >= 2:
                break  # la recherche par code-barres ne sert qu'à compléter une première recherche maigre
            self.ctx.consent.log("external_send", data_type="transcript", agent="recherche_web", detail=requete[:120])
            try:
                res = await asyncio.to_thread(client.rechercher, requete, max_chars=6000,
                                              max_results=RESULTATS_PAR_RECHERCHE)
            except recherche_web.RechercheNonConfiguree:
                raise RefusPrix(409, NON_CONFIGUREE, phrase="La recherche web n'est pas configurée sur cet ordinateur.")
            except recherche_web.RechercheError as exc:
                # Le message nomme le fournisseur de recherche : il reste au journal.
                log.warning("comparaison de prix : recherche en erreur (%s)", exc)
                if i > 0:
                    break  # la première recherche a déjà donné quelque chose : on le garde
                if isinstance(exc, recherche_web.RechercheReseau):
                    raise RefusPrix(502, RESEAU, phrase="La recherche web est injoignable pour l'instant.")
                raise RefusPrix(502, REFUSEE, phrase="La recherche web a refusé la demande. Réessaie plus tard.")
            faites += 1
            offres.extend(extraire_offres(list(getattr(res, "resultats", None) or []), produit))
        gardees, ecartees = trier_offres(offres, produit.get("prix_vu"))
        return gardees, ecartees, faites

    async def comparer(self, source: str = "image", image: Any = None, requete: str | None = None,
                       parler: bool = False) -> dict:
        """Identifie le produit, cherche ses prix en ligne au Canada et résume. Lève RefusPrix (ou les refus
        de la vision) : 403 consentement, 409 confidentiel / local / non configuré, 422, 502 recherche."""
        debut = time.monotonic()
        u = self.ctx.settings.user
        source = (source or "image").strip().lower()
        if source not in ("lunettes", "image", "texte"):
            raise RefusPrix(422, f"Source inconnue : « {source} ». Sources : lunettes, image.")
        requete = " ".join(str(requete or "").split())[:200] or None
        if hasattr(image, "model_dump"):
            image = image.model_dump()
        image_fournie = isinstance(image, dict) and bool(image.get("data"))
        if getattr(u, "privacy_mode", False):
            raise RefusPrix(409, CONFIDENTIEL, phrase="Le mode confidentiel est actif.")
        if getattr(u, "local_only", False):
            raise RefusPrix(409, LOCAL_SEULEMENT, phrase="Le mode 100 % local est actif : je ne peux pas chercher en ligne.")
        # Tout ce qui peut refuser est vérifié AVANT la photo : photographier pour rien, c'est capter des
        # passants sans raison.
        client = self.fabrique_recherche()
        if client.fournisseur_actif() is None:
            raise RefusPrix(409, NON_CONFIGUREE, phrase="La recherche web n'est pas configurée sur cet ordinateur.")
        self._verifier_envoi_texte()

        description: str | None = None
        if requete and not image_fournie:
            produit = {"nom": requete, "marque": None, "format": None, "code_barres": None, "prix_vu": None}
            source, precision = "texte", None
        else:
            if source in ("image", "texte") and not image_fournie:
                raise RefusPrix(422, "Image manquante : la source « image » exige une image, ou donnez le nom du produit.")
            source = "image" if image_fournie else "lunettes"
            produit, description = await self._identifier(source, image if image_fournie else None)
            precision = requete
            if not produit.get("nom"):
                raise RefusPrix(422, NON_IDENTIFIE, detail={"code": "non_identifie", "message": NON_IDENTIFIE,
                                                            "description": description},
                                phrase="Je n'ai pas pu identifier le produit. Reprends la photo plus près de l'étiquette.")

        offres, ecartees, faites = await self._chercher(client, construire_requetes(produit, precision), produit)
        resume = resume_vocal(produit, offres)
        resultat = {
            "produit": produit, "offres": offres, "resume": resume, "avertissement": AVERTISSEMENT, "local": False,
            "source": source, "description": description, "ecartees": ecartees, "recherches": faites,
            "duree_ms": int((time.monotonic() - debut) * 1000),
        }
        self.ctx.consent.log("prix_comparaison", detail=f"{source} / {len(offres)} offre(s)")
        if parler:
            await self.dire(resume)
        return resultat

    # ------------------------------------------------------------------ voix
    def interception(self, texte: str):
        """« Compare les prix », « compare les prix de la cafetière Bodum » (priorité 60)."""
        requete = demande_vocale(texte)
        if requete is None:
            return None
        return self._comparaison_vocale(requete or None)

    async def _comparaison_vocale(self, requete: str | None) -> str:
        try:
            resultat = await self.comparer("lunettes" if not requete else "texte", requete=requete)
        except HTTPException as exc:
            phrase = getattr(exc, "phrase", None)
            return str(phrase) if phrase else "Je ne peux pas comparer les prix pour l'instant."
        except Exception:
            log.exception("comparaison de prix vocale en erreur")
            return "Je n'ai pas réussi à comparer les prix."
        return resultat["resume"]

    def brancher_voix(self) -> None:
        voice = getattr(self.ctx, "voice", None)
        if voice is not None and hasattr(voice, "ajouter_interception"):
            voice.ajouter_interception("assistants-prix", self.interception, priorite=60)

    def debrancher_voix(self) -> None:
        voice = getattr(self.ctx, "voice", None)
        if voice is not None and hasattr(voice, "retirer_interception"):
            voice.retirer_interception("assistants-prix")


DECLENCHEURS = ("compare les prix", "compare le prix", "comparer les prix", "comparer le prix", "compare prix",
                "meilleur prix", "combien ca coute ailleurs", "c est combien ailleurs", "moins cher ailleurs",
                "trouve moins cher", "comparaison de prix")
_DEICTIQUES = {"ca", "cela", "ceci", "celui ci", "celle ci", "cet objet", "ce produit", "ce truc", "cette affaire",
               "ce que je tiens", "ce que je regarde"}
_ARTICLES = ("la", "le", "les", "l", "un", "une", "des", "du", "de", "d", "mon", "ma", "mes", "ce", "cette", "cet", "ces")


def demande_vocale(texte: str) -> str | None:
    """None si la phrase ne demande pas de comparer ; "" pour « ce que je montre » ; sinon le produit nommé."""
    # Positions gardées : le produit est rendu tel que dit (« grille-pain », pas « grille pain »).
    brut = texte or ""
    js = [(m.start(), normaliser(m.group(0))) for m in re.finditer(r"[^\W_]+", brut) if normaliser(m.group(0))]
    norm = [n for _p, n in js]
    phrase = " ".join(norm)
    if len(norm) > 14:
        return None
    for declencheur in DECLENCHEURS:
        if f" {declencheur} " not in f" {phrase} ":
            continue
        mots = declencheur.split()
        for i in range(len(norm) - len(mots) + 1):
            if norm[i:i + len(mots)] != mots:
                continue
            reste = js[i + len(mots):]
            if reste and reste[0][1] in ("de", "du", "des", "d", "pour", "sur"):
                reste = reste[1:]
            while reste and reste[0][1] in _ARTICLES:
                reste = reste[1:]
            nom = brut[reste[0][0]:].strip().rstrip(" ?!.,;") if reste else ""
            if not nom or normaliser(nom) in _DEICTIQUES:
                return ""
            return nom
    return None
