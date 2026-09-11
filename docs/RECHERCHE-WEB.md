# Recherche web d'IRIS — API officielle, jamais de CAPTCHA

## Le problème qu'on a corrigé

`WebAgent.search()` (`backend/iris/web.py`) ouvrait autrefois une page de moteur
(`duckduckgo.com/html/?q=…`) dans le navigateur piloté et grattait le HTML. Les moteurs répondent
à ça par un contrôle anti-robot : Google et DuckDuckGo bloquent, Bing renvoie du hors-sujet. La
recherche d'IRIS n'était donc pas fiable — un problème pour les clients pros.

## La règle

IRIS ne résout **jamais** de CAPTCHA et ne contourne **jamais** une détection de robot. La bonne
solution n'est pas de mieux tromper les moteurs, c'est d'appeler une **API de recherche officielle**
(accès sanctionné, prévu pour l'usage automatisé, aucun mur de vérification).

## Comment ça marche maintenant

`WebAgent.search()` procède dans cet ordre :

1. **API de recherche** si une clé est configurée (module `backend/iris/recherche_web.py`).
   Aucun navigateur ne s'ouvre : il n'y a donc rien à bloquer côté anti-robot. Renvoie
   `{"query", "url", "text"}` — `text` = résultats formatés (titre + URL + extrait de chaque
   résultat, prêts pour le modèle), `url` = URL du premier résultat.
2. **Repli navigateur** si **aucune** clé n'est configurée : l'ancien comportement (grattage de
   DuckDuckGo), qui reste **fragile** — les moteurs peuvent le bloquer. Un avertissement est
   journalisé : « recherche API non configurée, repli navigateur (peut être bloqué par anti-robot) ».

La vraie fiabilité vient de l'API. Le repli n'est qu'un filet, pas la solution.

## Fournisseurs pris en charge

Le fournisseur est choisi **selon la clé présente** :

| Fournisseur | Variable d'environnement | Pourquoi |
|-------------|--------------------------|----------|
| **Tavily** (privilégié) | `TAVILY_API_KEY` | Optimisé pour l'IA : extraits déjà résumés, parfois une réponse directe. |
| **Brave Search** | `BRAVE_SEARCH_API_KEY` | Index web indépendant, bon repli. |

Si les deux clés sont présentes, **Tavily** l'emporte.

## Ce que Miguel doit fournir

Une seule clé suffit pour rendre la recherche fiable. Deux façons de la donner :

1. **Fichier `backend/.env`** (gitignoré ; jamais committé). Ajouter **l'une** des lignes :

   ```
   TAVILY_API_KEY=tvly-...          # clé Tavily (https://app.tavily.com — palier gratuit généreux)
   BRAVE_SEARCH_API_KEY=BSA...      # clé Brave (https://brave.com/search/api/)
   ```

2. **Coffre système** (`SecretStore`) sous l'entrée `recherche` :
   `secrets.set_api_key("recherche", "<clé>")`. Comme le coffre ne connaît qu'une entrée, on peut
   préfixer la valeur pour dire de quel fournisseur elle relève : `tavily:tvly-...` ou
   `brave:BSA...`. Sans préfixe, une clé commençant par `tvly-` est reconnue comme Tavily ; sinon
   Tavily est supposé (le fournisseur privilégié).

L'environnement l'emporte sur le coffre.

## Quand un SITE (pas la recherche) exige une vérification humaine

Ouvrir une page précise reste du ressort du navigateur piloté (`web_open` / `web_read`). Si une
page dresse un mur anti-robot / CAPTCHA, `web_read` le détecte et IRIS le **dit** honnêtement :

> « Ce site demande une vérification humaine (CAPTCHA / contrôle anti-robot). Je ne la résous pas
> moi-même : ouvre la page et fais la vérification, je continue ensuite. »

Aucune résolution de CAPTCHA n'est codée, nulle part.

## Tests

`backend/tests/test_recherche_web.py` couvre les chemins Tavily et Brave, la sélection du
fournisseur, le repli navigateur sans clé, et les erreurs typées — le tout **sans réseau** (couche
HTTP injectée). Lancer : `cd backend && .venv/Scripts/python -m pytest -q`.
