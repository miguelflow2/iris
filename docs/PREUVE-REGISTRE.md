# Preuve réelle du registre de transparence

Rédigé le 13 septembre 2026. Ce document explique d'où vient le fichier
`site/assets/preuves/registre-session-essai-2026-09-13.json`, comment un visiteur le vérifie,
et comment publier plus tard le registre d'une vraie session.

## 1. Ce qui est publié

| Élément | Valeur |
|---|---|
| Fichier | `site/assets/preuves/registre-session-essai-2026-09-13.json` (3 763 octets) |
| SHA-256 du fichier (octets tels qu'exportés) | `b9630940f3a46ef4703422eb2d7878614b1680e633d0e0471cf8e08259ce9600` |
| Nombre d'entrées | 10 |
| Première empreinte | `28bad477b1bca24db90cf6745c8b404e1e89eab9631cabc03742c537bbd986ba` |
| **Empreinte finale (à publier sur la page)** | `6dfc0287079f30400cf5a5a44530f7cd8500b24838ddaf62724ae7cca0bad25e` |
| Horodatage | `2026-09-14T01:30:22+00:00` (UTC), soit le **13 septembre 2026 à 21 h 30, heure de l'Est** |
| Vérificateur du site | `site/assets/registre-preuve.js` |

Attention à la date : IRIS horodate en temps universel (UTC). La session a eu lieu le 13 septembre
au soir à Montréal, mais le fichier affiche le 14 septembre à 01 h 30 UTC. Ce n'est pas une erreur
et il ne faut pas « corriger » l'heure (le fichier ne se vérifierait plus). Le vérificateur affiche
les deux : l'heure UTC et l'heure de l'appareil du visiteur. Les dix entrées portent la même seconde
parce que la session a été jouée par un script, pas à la main.

### Structure de l'export (`GET /api/privacy/export?format=json`)

```text
{
  "exported_at":  "2026-09-14T01:30:22+00:00",       // moment de l'export (UTC)
  "verification": { "ok": true, "count": 10,           // résultat de ConsentGate.verify()
                    "first_bad_id": null,              //   calculé par IRIS au moment de l'export
                    "last_hash": "6dfc…d25e" },
  "events": [                                          // ORDER BY id ASC
    { "id": 1,                                         // entier, identifiant de la ligne
      "created_at": "2026-09-14T01:30:22+00:00",       // texte ISO 8601, UTC, à la seconde
      "event_type": "consent_granted",                 // texte
      "data_type": "transcript",                       // texte ou null
      "agent": null,                                   // texte ou null
      "detail": "",                                    // texte (500 caractères au plus)
      "prev_hash": "",                                 // empreinte de l'entrée précédente ("" pour la 1re)
      "hash": "28ba…86ba" }                            // SHA-256 hexadécimal (64 caractères)
  ]
}
```

Formule (identique à `ConsentGate._digest`, `backend/iris/consent.py`) :

```text
hash = SHA-256 hexadécimal de  prev | created_at | event_type | data_type ou "" | agent ou "" | detail ou ""
```

Une entrée est valide si son `hash` recalculé est exact **et** si son `prev_hash` est égal au `hash`
de l'entrée précédente. L'export ne contient pas l'entrée `register_exported` que l'export lui-même
ajoute au registre : IRIS calcule le fichier d'abord, puis journalise l'export.

### Les dix entrées

| # | event_type | data_type | detail |
|---|---|---|---|
| 1 | consent_granted | transcript | |
| 2 | consent_revoked | transcript | |
| 3 | memory_cleared | | `1 souvenirs` |
| 4 | privacy_mode_enabled | | |
| 5 | privacy_mode_disabled | | |
| 6 | local_only_enabled | | |
| 7 | local_only_disabled | | |
| 8 | purge_manual | | `{'memories': 0, 'messages': 0, 'events': 0}` |
| 9 | consent_granted | memory | |
| 10 | consent_revoked | memory | |

Aucun nom, courriel, chemin personnel, jeton, adresse IP ou adresse Bluetooth : contrôle automatique
(expressions régulières) puis relecture humaine du fichier. Le souvenir « Préférer le thé au café » n'y
apparaît pas : l'ajout d'un souvenir n'écrit pas dans le registre, seul l'effacement le fait
(`memory_cleared`, avec le nombre de souvenirs effacés). Aucun nom de fournisseur : le champ `agent`
est vide partout.

## 2. Comment la preuve a été produite

### Quel code a produit le fichier (à dire tel quel)

- Code exécuté : l'arbre de travail du dépôt au commit `e9a10a9` (IRIS **0.2.0 en développement**,
  aucun fichier suivi modifié au moment de l'exécution).
- Le module du registre, `backend/iris/consent.py`, est **identique** à celui de la version publiée
  0.1.0 (commit `7df2105`), fins de ligne mises à part :
  `git -C C:/Users/migue/Downloads/startup/iris show 7df2105:backend/iris/consent.py | diff --strip-trailing-cr - backend/iris/consent.py`
  ne renvoie aucune différence. Les appels au registre des routes utilisées (`/api/consent/{type}`,
  `DELETE /api/memory`, `PATCH /api/settings` pour `privacy_mode` et `local_only`,
  `/api/privacy/purge`, `/api/privacy/export`, `/api/privacy/verify`) sont les mêmes dans 0.1.0.
- Pourquoi pas directement le code de `7df2105` : extrait seul, il ne démarre pas. Il importe
  `iris/telecommande.py` et `iris/voice/piper.py`, qui n'étaient pas encore commités à cette date
  (ajoutés dans `1f83670`). **Le commit `7df2105` ne reproduit donc pas exactement l'installateur
  0.1.0**, construit à partir d'un arbre de travail qui contenait des fichiers non suivis. À corriger
  pour les prochaines versions : étiqueter (tag git) le commit exact de chaque installateur publié.

### Conditions

- Dossier de données **vierge et temporaire** (`tempfile.TemporaryDirectory`), supprimé après coup.
- `use_keyring=False` (rien dans le coffre Windows), `enable_tts=False` (pas de voix).
- `TestClient` utilisé **sans** bloc `with` : le cycle de vie de l'application ne démarre pas, donc
  aucune boucle de fond, aucun micro, aucune connexion aux lunettes, aucun appel réseau.
- Réglage préalable `voice_autostart = false` (n'écrit pas dans le registre) : sans lui, désactiver le
  mode confidentiel relancerait l'écoute du micro.
- Aucune fonction en ligne n'a été utilisée. La preuve montre donc la chaîne et la journalisation des
  réglages de confidentialité ; **elle ne contient aucun envoi (`external_send`) ni capture**.

### Commandes

Le script doit être placé dans un chemin court : avec le chemin très long du bloc-notes de session,
Python pour Windows ne trouve pas le fichier (limite de 260 caractères).

```bash
mkdir -p C:/Users/migue/AppData/Local/Temp/iris-preuve-0913
# y écrire session_registre.py (ci-dessous), puis :
cd C:/Users/migue/Downloads/startup/iris/backend
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe \
  C:/Users/migue/AppData/Local/Temp/iris-preuve-0913/session_registre.py \
  C:/Users/migue/Downloads/startup/iris/site/assets/preuves/registre-session-essai-2026-09-13.json
```

Sortie obtenue :

```text
version IRIS exercée : 0.2.0
verify avant export : {'ok': True, 'count': 10, 'first_bad_id': None, 'last_hash': '6dfc0287…d25e'}
verify après export (inclut l'entrée register_exported) : {'ok': True, 'count': 11, …}
relecture indépendante : OK, 10 entrées, empreinte finale 6dfc0287079f30400cf5a5a44530f7cd8500b24838ddaf62724ae7cca0bad25e
contrôle données personnelles : rien trouvé
```

Un essai à blanc a été fait avant, vers un fichier temporaire, pour relire le contenu. Le fichier
publié vient de la seconde exécution, écrit octet pour octet tel que renvoyé par l'API.

### Script `session_registre.py`

```python
"""Session d'essai scriptée : produit un registre de transparence RÉEL avec l'application IRIS.
Lancer avec le python du venv, le répertoire courant étant le dossier backend."""
from __future__ import annotations

import hashlib, json, re, sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))
from fastapi.testclient import TestClient
from iris import __version__
from iris.main import create_app


def etape(resp, attendu=200):
    if resp.status_code != attendu:
        raise SystemExit(f"échec {resp.request.method} {resp.request.url}: {resp.status_code} {resp.text[:300]}")
    return resp


def main() -> None:
    sortie = Path(sys.argv[1])
    print("version IRIS exercée :", __version__)
    with tempfile.TemporaryDirectory(prefix="iris-preuve-", ignore_cleanup_errors=True) as tmp:
        app = create_app(data_dir=Path(tmp), token="t", use_keyring=False, enable_tts=False)
        c = TestClient(app, headers={"Authorization": "Bearer t"})   # sans « with » : pas de lifespan

        etape(c.patch("/api/settings", json={"voice_autostart": False}))   # non journalisé
        etape(c.put("/api/consent/transcript", json={"granted": True}))
        etape(c.put("/api/consent/transcript", json={"granted": False}))
        etape(c.post("/api/memory", json={"text": "Préférer le thé au café"}))   # non journalisé
        etape(c.delete("/api/memory"))
        etape(c.patch("/api/settings", json={"privacy_mode": True}))
        etape(c.patch("/api/settings", json={"privacy_mode": False}))
        etape(c.patch("/api/settings", json={"local_only": True}))
        etape(c.patch("/api/settings", json={"local_only": False}))
        etape(c.post("/api/privacy/purge"))
        etape(c.put("/api/consent/memory", json={"granted": True}))
        etape(c.put("/api/consent/memory", json={"granted": False}))

        verif_avant = etape(c.get("/api/privacy/verify")).json()
        export = etape(c.get("/api/privacy/export", params={"format": "json"}))
        sortie.parent.mkdir(parents=True, exist_ok=True)
        sortie.write_bytes(export.content)                      # octets tels qu'exportés
        verif_apres = etape(c.get("/api/privacy/verify")).json()
        assert verif_avant["ok"] and verif_apres["ok"], "registre invalide"
        c.close()

    # Relecture indépendante (sans ConsentGate)
    doc = json.loads(sortie.read_bytes().decode("utf-8"))
    prev = ""
    for i, ev in enumerate(doc["events"]):
        payload = "|".join([prev, ev["created_at"], ev["event_type"], ev["data_type"] or "", ev["agent"] or "", ev["detail"] or ""])
        assert (ev["prev_hash"] or "") == prev, f"chaînage rompu à l'index {i}"
        assert ev["hash"] == hashlib.sha256(payload.encode("utf-8")).hexdigest(), f"empreinte fausse à l'index {i}"
        prev = ev["hash"]
    assert doc["verification"]["last_hash"] == prev

    # Contrôle des données personnelles
    texte = sortie.read_text(encoding="utf-8")
    motifs = {
        "chemin Windows": r"[A-Za-z]:[\\/]",
        "dossier utilisateur": r"(?i)users[\\/]|migue|iris-preuve-",
        "courriel": r"[\w.+-]+@[\w-]+\.[\w.]+",
        "adresse IP": r"\b\d{1,3}(\.\d{1,3}){3}\b",
        "adresse matérielle": r"(?i)\b[0-9a-f]{2}(:[0-9a-f]{2}){5}\b",
        "jeton": r"(?i)bearer|token|api[_-]?key|sk-",
    }
    trouves = {k: re.findall(m, texte) for k, m in motifs.items() if re.findall(m, texte)}
    print("contrôle données personnelles :", trouves or "rien trouvé")


if __name__ == "__main__":
    main()
```

### Vérification du JavaScript (Node 24)

Une copie de `site/assets/registre-preuve.js` (renommée `.cjs`) a été chargée dans Node 24.19.0 avec
`require`, et 17 contrôles ont tous passé :

- fichier réel : « intègre », 10 entrées, empreinte finale égale à celle publiée et à
  `verification.last_hash` ;
- pour les 10 entrées, `crypto.subtle` = `node:crypto` = empreintes écrites par IRIS (Python) ;
- bouton de démonstration (`alterer`) : entrée n° 2, `consent_revoked` → `consent_granted`, détectée à
  l'entrée n° 2 ; l'original en mémoire n'est pas touché ;
- `detail` modifié (entrée 8), `created_at` modifié (entrée 1) : détectés à la bonne entrée ;
- entrée supprimée, deux entrées échangées : détectées (chaînage rompu) ;
- chaîne **entièrement recalculée** après falsification : cohérente sans référence (limite connue,
  voir § 3), refusée dès qu'on fournit l'empreinte finale publiée ;
- entrée sans empreinte en tête (ancien registre) : tolérée comme dans `ConsentGate.verify` ;
- fichier sans `events` ou vide : signalé.

Le module a aussi été exécuté dans un vrai navigateur (Chromium), injecté sur la page
confidentialite.html du site en ligne, le JSON étant fourni par un substitut de `fetch` puisqu'il
n'est pas encore déployé. Version finale (SHA-256 du source `b28531f0…b0f1`, identique au fichier) :
chargement, « Chaîne intègre » + « Empreinte finale identique à celle publiée », altération (seule
l'entrée n° 2 marquée), bouton « Rétablir » contrôlés. Sur la révision précédente (libellés,
abréviation et marquage différents) : rendu dans le thème, vérification d'un fichier local re-scellé
(cohérent, empreinte publiée non appliquée) et d'un fichier invalide (signalé, bouton désactivé).

## 3. Ce que la vérification prouve, et ce qu'elle ne prouve pas

- **Elle prouve** que chaque entrée du fichier correspond à son empreinte et que les entrées se
  suivent sans trou, sans ajout ni réordonnancement. Et, si l'empreinte finale est publiée ailleurs
  (sur la page, dans ce document, dans l'historique git), que le fichier est bien celui-là.
- **Elle ne prouve pas à elle seule qui a produit le fichier.** La formule est publique : quelqu'un
  qui réécrit un registre et recalcule **toutes** les empreintes obtient une chaîne cohérente. C'est
  pourquoi l'empreinte finale doit être publiée à côté du fichier (`data-empreinte-finale`), et
  pourquoi le mode opératoire est documenté ici pour être refait.
- Sur la page, ne pas écrire que la chaîne rend « toute modification impossible » ou « détectable
  dans tous les cas » : la formulation exacte est « une modification d'une entrée casse la chaîne,
  sauf à recalculer toutes les empreintes suivantes — d'où l'empreinte finale publiée ».

## 4. Comment un visiteur vérifie

**Dans la page.** Le bloc « Preuve » télécharge le fichier (même origine), recalcule les empreintes
avec `crypto.subtle` et affiche : nombre d'entrées, première et dernière empreinte abrégées (16
premiers caractères, comme l'écran Confidentialité d'IRIS, puis les 8 derniers), horodatage UTC et
local, « Chaîne intègre » ou le numéro de la première entrée altérée. Le bouton « Altérer une entrée
pour voir » modifie une copie en mémoire et relance la vérification. Rien n'est envoyé.

**Hors de la page, sans rien installer d'autre que Python :**

```python
import hashlib, json, sys
doc = json.load(open(sys.argv[1], encoding="utf-8"))
prev = ""
for i, ev in enumerate(doc["events"]):
    if ev.get("hash") is None:
        prev = ""
        continue
    payload = "|".join([prev, ev["created_at"], ev["event_type"], ev["data_type"] or "", ev["agent"] or "", ev["detail"] or ""])
    if hashlib.sha256(payload.encode("utf-8")).hexdigest() != ev["hash"] or (ev["prev_hash"] or "") != prev:
        sys.exit(f"Chaîne rompue à l'entrée n° {i + 1}")
    prev = ev["hash"]
print("Chaîne intègre :", len(doc["events"]), "entrées, empreinte finale", prev)
```

Testé : « Chaîne intègre : 10 entrées, empreinte finale 6dfc0287…d25e » sur le fichier publié,
« Chaîne rompue à l'entrée n° 2 » après avoir remplacé `consent_revoked` par `consent_granted`.

Empreinte du fichier lui-même, sous Windows :
`certutil -hashfile registre-session-essai-2026-09-13.json SHA256` → `b9630940…9600`.
(Réindenter le JSON change cette empreinte-là, pas la validité de la chaîne.)

## 5. Brancher le vérificateur sur la page

CSP du site (`site/_headers`) : `script-src 'self'` et `connect-src 'self'`. Le module est un fichier
du site, sans script en ligne, et le registre est servi par le site : rien à changer dans la CSP.

Extrait pour `site/confidentialite.html`, dans la section `#preuve`, **après** la démonstration
existante (dont l'étiquette « Registre de transparence — exemple » peut devenir « Démo du principe ») :

```html
      <!-- Preuve réelle : registre exporté par IRIS, vérifié dans le navigateur (assets/registre-preuve.js) -->
      <div class="proof" style="margin:40px 0 20px">
        <div class="proof-main">
          <div class="proof-label">Preuve</div>
          <div class="proof-state">Registre produit par IRIS lors d’une session d’essai du 13 septembre 2026</div>
          <p class="proof-hint">Ce n’est pas une illustration&nbsp;: c’est l’export JSON, non retouché, du registre
            d’IRIS après une courte session d’essai scriptée, sur un dossier de données vierge, sans aucune donnée
            personnelle (consentement accordé puis retiré, un souvenir neutre effacé, mode confidentiel et
            mode&nbsp;100&nbsp;% local activés puis désactivés, purge manuelle). Votre navigateur télécharge le
            fichier et recalcule chaque empreinte SHA-256&nbsp;; rien n’est envoyé nulle part.</p>
        </div>
      </div>

      <div class="demo" data-registre="assets/preuves/registre-session-essai-2026-09-13.json"
           data-empreinte-finale="6dfc0287079f30400cf5a5a44530f7cd8500b24838ddaf62724ae7cca0bad25e">
        <p class="small muted">Activez JavaScript pour vérifier ce registre ici, ou
          <a href="assets/preuves/registre-session-essai-2026-09-13.json" download>téléchargez le fichier</a>
          et vérifiez-le vous-même avec la formule ci-dessous.</p>
      </div>
      <p class="demo-note">
        Empreinte finale publiée&nbsp;: <span class="mono" style="word-break:break-all">6dfc0287079f30400cf5a5a44530f7cd8500b24838ddaf62724ae7cca0bad25e</span>.
        Horodatages en temps universel&nbsp;: 14&nbsp;septembre 2026, 1&nbsp;h&nbsp;30&nbsp;UTC, soit le 13&nbsp;septembre
        à 21&nbsp;h&nbsp;30, heure de l’Est. Formule&nbsp;: SHA-256 de «&nbsp;empreinte précédente | created_at |
        event_type | data_type | agent | detail&nbsp;». Session jouée avec le code d’IRIS en développement, dont le
        module du registre est identique à celui de la version publiée 0.1.0. Cette session ne comprend aucun
        envoi en ligne. La vérification montre que le fichier est cohérent et identique à celui dont l’empreinte
        est publiée ici&nbsp;; à elle seule, elle ne dit pas qui l’a produit.
      </p>
```

Et, avant `</body>`, à côté de `site.js` :

```html
<script src="assets/registre-preuve.js?v=1" defer></script>
```

Pages traduites (`site/en`, `site/es`, `site/it`) : chemins `../assets/…`, et textes par attributs
`data-t-*` sur le conteneur. Noms disponibles : `data-t-chargement`, `data-t-calcul`,
`data-t-integre`, `data-t-alteree`, `data-t-raison-empreinte`, `data-t-raison-chainage`,
`data-t-ancre-ok`, `data-t-ancre-ko`, `data-t-sans-ancre`, `data-t-sans-empreinte`, `data-t-vide`,
`data-t-entrees`, `data-t-premiere`, `data-t-derniere`, `data-t-horodatage`, `data-t-heure-locale`,
`data-t-voir-entrees`, `data-t-empreinte`, `data-t-alterer`, `data-t-retablir`, `data-t-copie`,
`data-t-marque-alteree`, `data-t-telecharger`, `data-t-fichier-local`, `data-t-fichier-local-nom`,
`data-t-erreur-chargement`, `data-t-erreur-format`, `data-t-erreur-crypto`. Gabarits : `{k}`
nombre, `{n}` position, `{id}` identifiant, `{champ}`, `{avant}`, `{apres}`, `{detail}`. Exemple
anglais : `data-t-integre="Chain intact: {k} entries recomputed, each hash matches its content and the previous entry."`
`data-t-alterer="Tamper with an entry to see"`.

Option `data-fichier-local` (désactivée dans l'extrait) : ajoute un champ « Vérifier votre propre
registre exporté » ; le fichier choisi est lu dans le navigateur, jamais envoyé, et l'empreinte publiée
ne lui est pas appliquée. Le champ fichier garde l'apparence native du navigateur. Ne l'activer que si
l'export du registre est réellement accessible aux clients dans la version publiée.

## 6. Publier plus tard le registre d'une vraie session (Miguel)

1. **Session propre.** Le registre n'est jamais « nettoyable » : retoucher, retirer ou masquer une
   entrée casse la chaîne, et le fichier ne se vérifie plus. Donc, si le registre contient quoi que ce
   soit de privé, **on ne publie pas ce registre-là**. Deux possibilités :
   - utiliser un compte Windows dédié à la démonstration : l'application installée range son dossier
     de données dans le profil de chaque compte Windows (elle impose `--data-dir` au démarrage, une
     variable d'environnement ne suffit donc pas) ;
   - ou, sur le profil habituel, exporter d'abord une copie privée, puis « Effacer le registre »
     (Confidentialité). Attention : l'effacement est définitif et la chaîne repart de zéro.
2. **Faire la session** avec les lunettes, en n'utilisant que ce qu'on accepte de montrer.
3. **Relever l'empreinte.** Confidentialité → « Vérifier maintenant » : noter l'empreinte finale
   affichée (16 premiers caractères). **Immédiatement après**, sans autre action : « Exporter JSON ».
   Le `verification.last_hash` du fichier doit commencer par ces 16 caractères. (L'export ajoute
   ensuite sa propre entrée `register_exported` : l'empreinte affichée par IRIS après l'export est
   donc différente, c'est normal.)
4. **Relire chaque champ** `detail`, `agent` et `data_type`. Événements qui peuvent contenir des
   données personnelles ou des noms de fournisseurs :
   - `external_send` : `detail` = les 120 premiers caractères de la demande envoyée ; `agent` = nom
     technique du moteur (par exemple `vela`, `openrouter`, `claude`, `gpt`, `gemini`, `custom`) —
     **masque de marque** : un nom de fournisseur ne doit pas être publié ;
   - `glasses_connected` : nom et adresse Bluetooth des lunettes ;
   - `lunettes_photo` : chemin du fichier photo sur l'ordinateur (contient le nom d'utilisateur Windows) ;
   - `courriel_envoye` : adresses des destinataires ; événements `telephonie` et `communications` ;
   - `site_credentials_updated`, `site_credentials_removed`, `web_login` : noms de sites ;
   - `api_key_updated` / `api_key_removed` : `agent` = nom du service, `detail` = nom du fichier de clés ;
   - `agent_test`, `daily_summary`, `plan_activated`, `plan_demo`, `enregistrement_audio_*`, `cours_*`,
     `memory_range_deleted` : relire au cas par cas.
   Contrôle automatique conseillé : réutiliser la partie « Contrôle des données personnelles » du
   script du § 2 (chemins, courriels, adresses IP et matérielles, jetons), plus une recherche des
   noms de fournisseurs.
5. **Vérifier hors ligne** avec le script Python du § 4, puis dans la page en local.
6. **Publier** : déposer le fichier tel quel dans `site/assets/preuves/` (nom daté), ajouter un bloc
   `data-registre` avec `data-empreinte-finale`, inscrire l'empreinte finale et le SHA-256 du fichier
   dans ce document, augmenter le paramètre de cache du script si le module a changé. Dire sur la page
   ce que la session contient et ne contient pas (par exemple : « sans envoi en ligne »), et ne jamais
   qualifier de « vraie journée d'utilisation » une session préparée pour la démonstration.
