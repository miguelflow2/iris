"""Outils de veille : IRIS peut lancer, lister et arrêter une surveillance depuis une commande vocale."""
import py_compile
from pathlib import Path

RACINE = Path(__file__).resolve().parent
faits = []


def patch(rel, paires):
    p = RACINE / rel
    s = original = p.read_text(encoding="utf-8")
    for old, new in paires:
        assert old in s, f"introuvable dans {rel} : {old[:90]!r}"
        s = s.replace(old, new, 1)
    if s != original:
        p.write_text(s, encoding="utf-8")
        py_compile.compile(str(p), doraise=True)
        faits.append(f"MODIFIE  {rel}")


patch(
    "iris/tools.py",
    [
        # --- contexte : accès au service de veille
        ('    routines: Any = None', '    routines: Any = None\n    watches: Any = None  # WatchService : surveillance d\'une page dans la durée'),

        # --- déclaration des outils
        ('''    ToolSpec(
        "set_reminder",''',
         '''    ToolSpec(
        "create_watch",
        "Met en place une SURVEILLANCE DURABLE d'une page ou d'une conversation web (ex. un fil de discussion avec un "
        "fournisseur). IRIS la relit régulièrement, analyse les nouveaux messages au regard des critères donnés, et "
        "prévient l'utilisateur à la voix dès qu'ils sont remplis. À utiliser quand la demande contient « surveille », "
        "« garde un œil », « préviens-moi si », « en permanence ». IRIS ne peut jamais acheter ni répondre toute seule : "
        "elle prépare la décision et l'utilisateur confirme. Demande l'adresse exacte de la page si tu ne l'as pas.",
        _obj(
            {
                "name": {"type": "string", "description": "Nom court, ex. « fournisseur Alibaba »"},
                "url": {"type": "string", "description": "Adresse complète de la page à surveiller"},
                "criteria": {"type": "string", "description": "Ce qui doit déclencher l'alerte, avec les chiffres exacts"},
                "interval_min": {"type": "integer", "description": "Minutes entre deux vérifications (15 par défaut, 2 minimum)"},
                "site": {"type": "string", "description": "Nom d'un compte web enregistré à ouvrir avant de lire (facultatif)"},
            },
            ["name", "url", "criteria"],
        ),
    ),
    ToolSpec("list_watches", "Liste les surveillances en cours et leurs dernières alertes.", _obj({})),
    ToolSpec(
        "stop_watch",
        "Arrête une surveillance en cours, par son identifiant ou son nom.",
        _obj({"watch": {"type": "string", "description": "Identifiant ou nom de la veille"}}, ["watch"]),
    ),
    ToolSpec(
        "set_reminder",'''),

        # --- exécution
        ('''        if name == "remember":''',
         '''        if name in ("create_watch", "list_watches", "stop_watch"):
            if ctx.watches is None:
                return _err("La surveillance n'est pas disponible.")
            if name == "create_watch":
                try:
                    w = ctx.watches.create(
                        args.get("name", ""), args.get("url", ""), args.get("criteria", ""),
                        int(args.get("interval_min") or 15), args.get("site", ""),
                    )
                except ValueError as exc:
                    return _err(str(exc))
                return (
                    f"Surveillance « {w['name']} » lancée : je relis la page toutes les {w['interval_min']} minutes et "
                    "je te préviens dès que tes critères sont remplis. Je ne conclurai aucun achat sans ton accord."
                )
            if name == "list_watches":
                items = ctx.watches.list()
                if not items:
                    return "Aucune surveillance en cours."
                return "\\n".join(
                    f"- {w['name']} ({'active' if w['active'] else 'arrêtée'}, toutes les {w['interval_min']} min, "
                    f"{w['alerts']} alerte(s)) : {w['criteria'][:90]}"
                    for w in items
                )
            cible = (args.get("watch") or "").strip().lower()
            for w in ctx.watches.list():
                if cible in (w["id"].lower(), w["name"].lower()) or cible in w["name"].lower():
                    ctx.watches.stop(w["id"])
                    return f"Surveillance « {w['name']} » arrêtée."
            return _err("Surveillance introuvable. Demande « liste mes surveillances » pour voir les noms.")

        if name == "remember":'''),
    ],
)

# groupes d'outils : la veille n'est pas un outil d'écran ni de clavier, elle reste toujours disponible
patch(
    "iris/chat.py",
    [
        ("                    routines=self.routines, reminders=self.reminders,",
         "                    routines=self.routines, reminders=self.reminders, watches=getattr(self, 'watches', None),"),
    ],
)

print("\n".join(faits) or "rien")
