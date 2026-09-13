"""Navigateur piloté (Chrome installé via Playwright) : ouvrir, lire, cliquer, remplir, se connecter à un site
enregistré. Le mot de passe est rempli par l'outil lui-même : le modèle d'IA ne le voit jamais."""
from __future__ import annotations

import base64
import logging
import queue
import re
import threading
import time
from pathlib import Path
from typing import Any, Callable

from .config import Settings
from .events import EventHub
from .security.secrets import SecretStore

log = logging.getLogger("iris.web")

MAX_TEXT = 6000

# Profils de connexion connus (sélecteurs stables) ; les autres sites passent par des heuristiques.
SITE_PROFILES: dict[str, dict] = {
    "omnivox": {
        "match": "omnivox",
        "user": "#Identifiant",
        "password": "#Password",
        "submit": "#formLogin button[type=submit]",
        "logged_in": lambda url: "/intr" in url.lower() and "/login" not in url.lower(),
    },
}


class WebAgent:
    """Toutes les opérations Playwright (API synchrone) s'exécutent sur un thread dédié."""

    def __init__(self, settings: Settings, hub: EventHub, secrets: SecretStore):
        self.settings = settings
        self.hub = hub
        self.secrets = secrets
        self.profile_dir = Path(settings.data_dir) / "browser-profile"
        self._jobs: "queue.Queue[tuple[Callable[[], Any], queue.Queue]]" = queue.Queue()
        self._thread: threading.Thread | None = None
        self._pw = None
        self._ctx = None
        self._page = None
        self._visible = False  # fenêtre affichée ? (voir _browser)
        self.error: str | None = None
        self.last_url = ""

    # ------------------------------------------------------------------ thread + navigateur
    def _ensure_thread(self) -> None:
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._worker, name="iris-web", daemon=True)
            self._thread.start()

    def _worker(self) -> None:
        while True:
            fn, out = self._jobs.get()
            try:
                out.put((True, fn()))
            except Exception as exc:  # noqa: BLE001
                out.put((False, exc))

    def _run(self, fn: Callable[[], Any], timeout: float = 180.0) -> Any:
        self._ensure_thread()
        out: queue.Queue = queue.Queue()
        self._jobs.put((fn, out))
        ok, value = out.get(timeout=timeout)
        if not ok:
            raise value
        return value

    # `visible` remonte jusqu'aux outils : « montre-moi » ouvre la fenetre. Limite qu'IRIS a
    # elle-meme nommee le 6 septembre 2026 (« mes recherches ne t'ouvrent pas de fenetre ») —
    # l'invisible reste le defaut, parce que personne n'a envie de voir IRIS chercher.
    def _browser(self, visible: bool = False):
        """Contexte Chrome persistant : cookies et sessions conservés d'une fois sur l'autre.

        Invisible par défaut. Quand IRIS va chercher une information, personne n'a envie de voir
        une fenêtre s'ouvrir et défiler : on veut la réponse. La fenêtre ne s'affiche que pour une
        connexion à un compte, parce qu'il faut alors pouvoir reprendre la main — un captcha, une
        double authentification. Changer de mode referme le contexte : Chrome ne partage pas un
        même profil entre deux instances."""
        if self._ctx is not None and self._visible != visible:
            self.close()
        if self._ctx is not None:
            try:
                if self._page is None or self._page.is_closed():
                    self._page = self._ctx.new_page()
                return self._page
            except Exception:
                self._ctx = None
        from playwright.sync_api import sync_playwright

        if self._pw is None:
            self._pw = sync_playwright().start()
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        last_exc: Exception | None = None
        for channel in ("chrome", "msedge", None):
            try:
                kwargs = dict(headless=not visible, viewport={"width": 1280, "height": 860}, args=["--disable-blink-features=AutomationControlled"])
                if channel:
                    kwargs["channel"] = channel
                self._ctx = self._pw.chromium.launch_persistent_context(str(self.profile_dir), **kwargs)
                break
            except Exception as exc:  # navigateur absent
                last_exc = exc
                self._ctx = None
        if self._ctx is None:
            raise RuntimeError(f"Aucun navigateur pilotable (Chrome ou Edge requis) : {last_exc}")
        pages = self._ctx.pages
        self._page = pages[0] if pages else self._ctx.new_page()
        self._page.set_default_timeout(15000)
        self._visible = visible
        return self._page

    # ------------------------------------------------------------------ opérations
    @staticmethod
    def _clean(text: str) -> str:
        return re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n", text or "")).strip()

    def search(self, query: str, max_chars: int = 4000, visible: bool = False) -> dict:
        """Cherche sur le web et rend le texte des résultats. Aucune fenêtre ne s'ouvre.

        D'ABORD une API de recherche officielle (Tavily/Brave) si une clé est configurée : accès
        sanctionné, aucun CAPTCHA, aucun navigateur ouvert — donc rien à bloquer côté anti-robot.
        SANS clé : repli sur le navigateur piloté (comportement historique), fragile parce que les
        moteurs bloquent les robots. IRIS ne triche jamais avec un moteur ; la fiabilité vient de
        l'API. Voir docs/RECHERCHE-WEB.md.

        Personne n'a envie de voir défiler les recherches d'IRIS : on veut la réponse. Le
        navigateur (repli) travaille en arrière-plan, et seul le résultat remonte."""
        from urllib.parse import quote_plus

        from . import recherche_web

        client = recherche_web.ClientRecherche(self.secrets)
        actif = client.fournisseur_actif()
        if actif is not None:
            fournisseur, _ = actif
            try:
                res = client.rechercher(query, max_chars=max_chars)
                return {"query": query, "url": res.url, "text": res.text}
            except recherche_web.RechercheError as exc:
                # Erreur d'API : on remonte un message clair au lieu d'une exception crue, et on ne
                # bascule PAS en douce sur le grattage de moteur (ce serait rouvrir la porte du
                # blocage anti-robot qu'on vient de fermer).
                log.warning("recherche API (%s) a échoué : %s", fournisseur, exc)
                return {"query": query, "url": "", "text": f"[Recherche indisponible] {exc}"}

        log.warning("recherche API non configurée, repli navigateur (peut être bloqué par anti-robot)")

        def job():
            page = self._browser(visible)
            page.goto("https://duckduckgo.com/html/?q=" + quote_plus(query), wait_until="domcontentloaded")
            page.wait_for_timeout(600)
            return {"query": query, "url": page.url, "text": self._clean(page.inner_text("body"))[:max_chars]}

        return self._run(job)

    def open(self, url: str, visible: bool = False) -> dict:
        url = (url or "").strip()
        if not url.lower().startswith(("http://", "https://")):
            url = "https://" + url

        def job():
            page = self._browser(visible)
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_timeout(800)
            self.last_url = page.url
            return {"url": page.url, "title": page.title()}

        result = self._run(job)
        self.hub.publish("web.navigated", **result)
        return result

    # Un site peut dresser un mur anti-robot / CAPTCHA. IRIS ne le résout JAMAIS et ne le contourne
    # jamais : elle le DIT honnêtement et propose que l'utilisateur fasse la vérification lui-même.
    # (La recherche, elle, ne rencontre plus ce mur : elle passe par une API officielle — voir search.)
    _MOTS_MUR = (
        "verify you are human", "vérifiez que vous êtes humain", "i'm not a robot",
        "je ne suis pas un robot", "unusual traffic", "trafic inhabituel",
        "verify you are a human", "checking your browser", "vérification de votre navigateur",
        "prouvez que vous êtes humain", "confirmez que vous êtes",
    )

    @classmethod
    def _mur_verification(cls, page) -> bool:
        """Détecte un mur de vérification humaine (CAPTCHA, contrôle anti-robot). Ne lève jamais."""
        try:
            if page.locator("iframe[src*='recaptcha'], iframe[src*='captcha'], iframe[src*='hcaptcha'], "
                            "iframe[title*='challenge'], #captcha, .g-recaptcha, .h-captcha, .cf-turnstile").count() > 0:
                return True
        except Exception:
            pass
        try:
            bas = (page.inner_text("body") or "").lower()[:4000]
            return any(m in bas for m in cls._MOTS_MUR)
        except Exception:
            return False

    def read(self, max_chars: int = MAX_TEXT) -> dict:
        def job():
            page = self._browser()
            text = self._clean(page.inner_text("body"))
            links = []
            for el in page.query_selector_all("a[href], button, [role=button], [role=link], input[type=submit]")[:120]:
                try:
                    if not el.is_visible():
                        continue
                    label = self._clean(el.inner_text() or el.get_attribute("value") or el.get_attribute("aria-label") or "")
                    if label:
                        links.append(label[:60])
                except Exception:
                    continue
            self.last_url = page.url
            result = {"url": page.url, "title": page.title(), "text": text[:max_chars] + ("…" if len(text) > max_chars else ""), "clickable": list(dict.fromkeys(links))[:60]}
            if self._mur_verification(page):
                result["verification_humaine"] = (
                    "Ce site demande une vérification humaine (CAPTCHA / contrôle anti-robot). "
                    "Je ne la résous pas moi-même : ouvre la page et fais la vérification, je continue ensuite."
                )
            return result

        return self._run(job)

    def click(self, target: str) -> dict:
        target = (target or "").strip()

        def job():
            page = self._browser()
            loc = self._locate(page, target)
            loc.first.click(timeout=10000)
            page.wait_for_load_state("domcontentloaded")
            page.wait_for_timeout(600)
            self.last_url = page.url
            return {"clicked": target, "url": page.url, "title": page.title()}

        return self._run(job)

    def fill(self, target: str, value: str, submit: bool = False) -> dict:
        def job():
            page = self._browser()
            loc = self._locate(page, target, fields=True)
            loc.first.fill(value)
            if submit:
                loc.first.press("Enter")
                page.wait_for_load_state("domcontentloaded")
                page.wait_for_timeout(600)
            self.last_url = page.url
            return {"filled": target, "url": page.url}

        return self._run(job)

    def press(self, key: str) -> dict:
        def job():
            page = self._browser()
            page.keyboard.press(key)
            page.wait_for_timeout(400)
            return {"pressed": key, "url": page.url}

        return self._run(job)

    def back(self) -> dict:
        def job():
            page = self._browser()
            page.go_back(wait_until="domcontentloaded")
            self.last_url = page.url
            return {"url": page.url, "title": page.title()}

        return self._run(job)

    def screenshot(self) -> dict:
        def job():
            page = self._browser()
            data = page.screenshot(type="jpeg", quality=70, full_page=False)
            return {"media_type": "image/jpeg", "data": base64.b64encode(data).decode("ascii"), "url": page.url}

        return self._run(job)

    def close(self) -> None:
        def job():
            try:
                if self._ctx is not None:
                    self._ctx.close()
            finally:
                self._ctx = None
                self._page = None
                if self._pw is not None:
                    self._pw.stop()
                    self._pw = None
            return True

        try:
            self._run(job, timeout=20)
        except Exception:
            pass

    # ------------------------------------------------------------------ localisation
    def _locate(self, page, target: str, fields: bool = False):
        t = target.strip()
        if t.startswith(("#", ".", "//", "[")) or re.match(r"^[a-z]+\[", t):
            return page.locator(t)
        if fields:
            for finder in (lambda: page.get_by_label(t, exact=False), lambda: page.get_by_placeholder(t, exact=False), lambda: page.locator(f"[name='{t}']"), lambda: page.get_by_role("textbox", name=re.compile(re.escape(t), re.I))):
                try:
                    loc = finder()
                    if loc.count() > 0:
                        return loc
                except Exception:
                    continue
            return page.locator("input:visible, textarea:visible").first
        for finder in (
            lambda: page.get_by_role("link", name=re.compile(re.escape(t), re.I)),
            lambda: page.get_by_role("button", name=re.compile(re.escape(t), re.I)),
            lambda: page.get_by_text(t, exact=False),
        ):
            try:
                loc = finder()
                if loc.count() > 0:
                    return loc
            except Exception:
                continue
        raise RuntimeError(f"« {target} » introuvable sur la page. Utilise web_read pour voir les éléments cliquables.")

    # ------------------------------------------------------------------ connexion à un site enregistré
    def site_names(self) -> list[str]:
        return list((self.settings.user.sites or {}).keys())

    def resolve_site(self, name: str) -> tuple[str, dict] | None:
        sites = self.settings.user.sites or {}
        n = (name or "").strip().lower()
        for key, site in sites.items():
            url = (getattr(site, "url", None) or (site.get("url") if isinstance(site, dict) else "") or "").lower()
            if key.lower() == n or n in key.lower() or (n and n in url):
                return key, site
        return None

    def login(self, name: str) -> dict:
        found = self.resolve_site(name)
        if not found:
            known = ", ".join(self.site_names()) or "aucun"
            raise RuntimeError(f"Site « {name} » inconnu. Sites enregistrés : {known}. Ajoute-le dans Paramètres › Comptes web.")
        key, site = found
        creds = self.secrets.get_site(key)
        if not creds or not creds.get("password"):
            raise RuntimeError(f"Mot de passe absent pour « {key} » : l'utilisateur doit le saisir dans Paramètres › Comptes web.")
        site_url = getattr(site, "url", None) or (site.get("url") if isinstance(site, dict) else "") or ""
        site_user = getattr(site, "username", None) or (site.get("username") if isinstance(site, dict) else "") or ""
        username = site_user or creds.get("username") or ""
        url = site_url
        profile = next((p for p in SITE_PROFILES.values() if p["match"] in url.lower() or p["match"] in key.lower()), None)

        def job():
            # Connexion à un compte : la fenêtre s'affiche, l'utilisateur doit pouvoir reprendre
            # la main sur un captcha ou une double authentification.
            page = self._browser(visible=True)
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_timeout(800)
            if profile and profile["logged_in"](page.url):
                return {"status": "already_logged_in", "url": page.url, "title": page.title()}
            user_sel = profile["user"] if profile else "input[type=text]:visible, input[type=email]:visible, input:not([type]):visible"
            pass_sel = profile["password"] if profile else "input[type=password]:visible"
            if page.locator(pass_sel).count() == 0:
                return {"status": "no_login_form", "url": page.url, "title": page.title()}
            page.locator(user_sel).first.fill(username)
            page.locator(pass_sel).first.fill(creds["password"])
            if profile and profile.get("submit"):
                page.locator(profile["submit"]).first.click()
            else:
                page.locator(pass_sel).first.press("Enter")
            # contrôle de sécurité (reCAPTCHA) : jamais contourné, l'utilisateur le résout dans la fenêtre
            deadline = time.time() + 150
            notified = False
            while time.time() < deadline:
                page.wait_for_timeout(700)
                current = page.url
                if profile and profile["logged_in"](current):
                    break
                if not profile and page.locator(pass_sel).count() == 0:
                    break
                captcha = page.locator("iframe[src*='recaptcha'], iframe[src*='captcha'], #captcha, .g-recaptcha").count() > 0
                if captcha and not notified:
                    notified = True
                    self.hub.publish("web.captcha", url=current)
            page.wait_for_timeout(500)
            ok = profile["logged_in"](page.url) if profile else page.locator(pass_sel).count() == 0
            self.last_url = page.url
            return {"status": "logged_in" if ok else "login_failed", "url": page.url, "title": page.title(), "captcha": notified}

        result = self._run(job, timeout=200)
        self.hub.publish("web.login", site=key, status=result["status"])
        return {"site": key, **result}
