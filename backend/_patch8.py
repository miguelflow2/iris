"""Exécution : outils restreints au contexte, descriptions non ambiguës, arrêt des boucles d'outils."""
import py_compile

# ================================================================ tools.py : descriptions + groupes
p = "iris/tools.py"
s = open(p, encoding="utf-8").read()

OLD = '''    ToolSpec(
        "open_url",
        "Ouvre une adresse web dans le navigateur par défaut (site, résultat de recherche, vidéo…).",
        _obj({"url": {"type": "string"}}, ["url"]),
    ),
    ToolSpec(
        "play_youtube",
        "Cherche une musique ou une vidéo sur YouTube et lance la première correspondance dans le navigateur (lecture automatique). "
        "Si l'utilisateur n'a pas précisé quoi écouter, demande-lui d'abord quelle musique il souhaite.",
        _obj({"query": {"type": "string", "description": "Titre, artiste ou description"}}, ["query"]),
    ),'''
NEW = '''    ToolSpec(
        "open_url",
        "Ouvre un SITE web par son adresse (ex. https://www.radio-canada.ca). "
        "NE L'UTILISE PAS pour une vidéo, une musique, une chanson ni une recherche YouTube : utilise play_youtube.",
        _obj({"url": {"type": "string"}}, ["url"]),
    ),
    ToolSpec(
        "play_youtube",
        "À utiliser pour TOUTE demande de vidéo, musique, chanson ou clip (« mets », « lance », « joue », « écoute »), "
        "même si l'utilisateur dit d'abord « ouvre YouTube » : cet outil cherche et lance directement la vidéo. "
        "Un seul appel suffit ; ne prends aucune capture d'écran ensuite. "
        "Si l'utilisateur n'a pas dit quoi écouter, demande-le-lui d'abord au lieu d'appeler l'outil.",
        _obj({"query": {"type": "string", "description": "Titre, artiste ou description"}}, ["query"]),
    ),'''
assert OLD in s
s = s.replace(OLD, NEW, 1)

OLD = '''def tool_specs(ctx: ToolContext) -> list[ToolSpec]:
    specs = list(TOOL_SPECS)
    if ctx.create_task is None:
        specs = [s for s in specs if s.name != "create_task"]
    return specs'''
NEW = '''# Groupes d'outils : tout exposer à chaque demande poussait le modèle vers la souris et les captures d'écran
# pour des tâches qui n'en ont aucun besoin (trace réelle : une simple demande YouTube a fini en clics à l'aveugle).
SCREEN_TOOLS = {"take_screenshot", "screen_info", "mouse_move", "mouse_click", "mouse_drag", "scroll", "find_on_screen", "click_text"}
KEYBOARD_TOOLS = {"type_text", "press_keys"}
WEB_TOOLS = {"web_open", "web_login", "web_read", "web_click", "web_fill", "web_screenshot"}


def tool_specs(ctx: ToolContext, *, screen: bool = True, keyboard: bool = True, web: bool = True) -> list[ToolSpec]:
    specs = list(TOOL_SPECS)
    if ctx.create_task is None:
        specs = [s for s in specs if s.name != "create_task"]
    exclus: set[str] = set()
    if not screen:
        exclus |= SCREEN_TOOLS
    if not keyboard:
        exclus |= KEYBOARD_TOOLS
    if not web:
        exclus |= WEB_TOOLS
    return [s for s in specs if s.name not in exclus]'''
assert OLD in s
s = s.replace(OLD, NEW, 1)

open(p, "w", encoding="utf-8").write(s)
py_compile.compile(p, doraise=True)
print("tools.py : descriptions + groupes")

# ================================================================ chat.py : n'exposer que ce qui sert
p = "iris/chat.py"
s = open(p, encoding="utf-8").read()

OLD = '''            if connector.supports_tools and (_has(low_text, WEB_KEYWORDS) or (self.web is not None and any(n in low_text for n in self.web.site_names()))):'''
NEW = '''            is_web = connector.supports_tools and (_has(low_text, WEB_KEYWORDS) or (self.web is not None and any(n in low_text for n in self.web.site_names())))
            if is_web:'''
assert OLD in s
s = s.replace(OLD, NEW, 1)

OLD = "            tools = tool_specs(ctx)"
assert OLD in s
NEW = '''            # On n'expose que les outils utiles à CETTE demande : le clavier et la souris ne servent qu'au
            # contrôle d'écran, les outils web qu'à la navigation. Un modèle gratuit avec 37 outils s'égare.
            besoin_clavier = is_screen or _has(low_text, ["tape ", "écris ", "ecris ", "appuie", "raccourci", "touche"])
            tools = tool_specs(ctx, screen=is_screen, keyboard=besoin_clavier, web=is_web)'''
s = s.replace(OLD, NEW, 1)

# demande de média sans objet : laisser le modèle poser la question au lieu de forcer un outil
OLD = "            is_action = source != \"task\" and connector.supports_tools and (_has(low_text, STRICT_ACTION) or is_build)"
NEW = '''            is_action = source != "task" and connector.supports_tools and (_has(low_text, STRICT_ACTION) or is_build)
            # « mets de la musique » sans titre : forcer un outil empêcherait IRIS de demander quoi lancer.
            if is_action and re.search(r"\\b(de la musique|une musique|une vid[ée]o|une chanson|un film|un clip)\\s*\\.?\\s*$", low_text):
                is_action = False'''
assert OLD in s
s = s.replace(OLD, NEW, 1)

open(p, "w", encoding="utf-8").write(s)
py_compile.compile(p, doraise=True)
print("chat.py : outils restreints au contexte")

# ================================================================ openai_compat.py : anti-boucle
p = "iris/connectors/openai_compat.py"
s = open(p, encoding="utf-8").read()

OLD = '''        force_first = bool(opts.force_tools and tool_defs and run_tool is not None)
        for _round in range(max(1, int(opts.max_rounds or MAX_TOOL_ROUNDS))):'''
NEW = '''        force_first = bool(opts.force_tools and tool_defs and run_tool is not None)
        # Anti-boucle : sans mémoire des appels précédents, un modèle bloqué refait indéfiniment la même action
        # (trace réelle : capture d'écran, clic, alt+tab, répétés jusqu'à l'arrêt de sécurité).
        vus: dict[str, int] = {}
        erreurs_suite = 0
        bloque = False
        for _round in range(max(1, int(opts.max_rounds or MAX_TOOL_ROUNDS))):'''
assert OLD in s
s = s.replace(OLD, NEW, 1)

OLD = '''                    yield Chunk("tool_use", data={"id": call_id, "name": c["name"], "input": args})
                    try:
                        raw = await run_tool(c["name"], args)
                        content, is_error = normalize_tool_result(raw)
                    except Exception as exc:
                        log.exception("outil %s en erreur", c["name"])
                        content, is_error = f"Erreur pendant l'exécution de l'outil : {exc}", True'''
NEW = '''                    yield Chunk("tool_use", data={"id": call_id, "name": c["name"], "input": args})
                    cle = c["name"] + json.dumps(args, sort_keys=True, ensure_ascii=False)
                    vus[cle] = vus.get(cle, 0) + 1
                    if vus[cle] >= 2:
                        # même appel, mêmes arguments : on ne le rejoue pas, on le dit au modèle
                        content = (
                            f"Tu viens de refaire exactement la même action ({c['name']}) sans nouveau résultat. "
                            "Ne la répète pas : change de méthode, ou explique à l'utilisateur ce qui bloque."
                        )
                        is_error = True
                        log.info("appel d'outil répété ignoré : %s", c["name"])
                        if vus[cle] >= 3:
                            bloque = True
                    else:
                        try:
                            raw = await run_tool(c["name"], args)
                            content, is_error = normalize_tool_result(raw)
                        except Exception as exc:
                            log.exception("outil %s en erreur", c["name"])
                            content, is_error = f"Erreur pendant l'exécution de l'outil : {exc}", True
                    erreurs_suite = erreurs_suite + 1 if is_error else 0
                    if erreurs_suite >= 3:
                        bloque = True'''
assert OLD in s
s = s.replace(OLD, NEW, 1)

OLD = '''                if image_followups:
                    payload.append({"role": "user", "content": [{"type": "text", "text": "Voici l'image renvoyée par l'outil :"}, *image_followups]})
                continue'''
NEW = '''                if image_followups:
                    payload.append({"role": "user", "content": [{"type": "text", "text": "Voici l'image renvoyée par l'outil :"}, *image_followups]})
                if bloque:
                    yield Chunk("error", text="Je n'arrive pas à aller plus loin : la même action échoue en boucle. Dis-moi autrement ce que tu veux faire.")
                    return
                continue'''
assert OLD in s
s = s.replace(OLD, NEW, 1)

OLD = '''        yield Chunk("error", text="Trop d'appels d'outils successifs, arrêt de sécurité.")'''
NEW = '''        yield Chunk("error", text="J'ai enchaîné trop d'actions sans y arriver. Reformule ta demande, ou dis-moi l'étape précise à faire.")'''
assert OLD in s
s = s.replace(OLD, NEW, 1)

open(p, "w", encoding="utf-8").write(s)
py_compile.compile(p, doraise=True)
print("openai_compat.py : anti-boucle + message honnete")
