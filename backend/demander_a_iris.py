"""Poser une question a IRIS depuis l'exterieur, et lire ce qu'elle repond.

Sert a l'observer telle qu'elle est vraiment, sans passer par son interface : on envoie une
demande, on attend, on relit toute la conversation — y compris les outils qu'elle a appeles.

    python demander_a_iris.py "ta question"
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8765"
JETON = open(os.path.join(os.environ["APPDATA"], "IRIS", "iris-data", "remote-token")).read().strip()


def appeler(chemin, corps=None, methode=None):
    donnees = json.dumps(corps).encode() if corps is not None else None
    requete = urllib.request.Request(
        BASE + chemin, data=donnees,
        headers={"Authorization": "Bearer " + JETON, "Content-Type": "application/json"},
        method=methode or ("POST" if donnees is not None else "GET"),
    )
    try:
        with urllib.request.urlopen(requete, timeout=180) as reponse:
            return json.loads(reponse.read().decode())
    except urllib.error.HTTPError as exc:
        return {"erreur": exc.code, "detail": exc.read().decode()[:400]}


question = sys.argv[1] if len(sys.argv) > 1 else "Bonjour, tu m'entends ?"

conv = appeler("/api/conversations", {})
if "erreur" in conv:
    print("Impossible de creer la conversation :", conv)
    sys.exit(1)
cid = conv["id"]
print("Conversation {}".format(cid))
print("\n>>> MIGUEL : {}\n".format(question), flush=True)

envoi = appeler("/api/conversations/{}/messages".format(cid), {"text": question, "images": [], "agent": "auto"})
if "erreur" in envoi:
    print("Envoi refuse :", envoi)
    sys.exit(1)

# La reponse arrive en flux : on relit la conversation jusqu'a ce qu'elle se stabilise.
vus = 0
stable = 0
for _ in range(90):
    time.sleep(2)
    detail = appeler("/api/conversations/{}".format(cid))
    messages = detail.get("messages", []) if isinstance(detail, dict) else []
    if len(messages) == vus:
        stable += 1
        if stable >= 4 and vus > 1:
            break
    else:
        stable = 0
        vus = len(messages)

detail = appeler("/api/conversations/{}".format(cid))
for message in detail.get("messages", []):
    role = message.get("role")
    if role == "user":
        continue
    print("<<< IRIS ({}) :".format(message.get("agent") or message.get("model") or "?"), flush=True)
    texte = (message.get("text") or "").strip()
    print(texte or "(aucun texte)", flush=True)
    outils = message.get("tools") or []
    if outils:
        print("\n    --- outils appeles ---", flush=True)
        for outil in outils:
            nom = outil.get("name") or outil.get("tool") or "?"
            args = json.dumps(outil.get("args") or outil.get("input") or {}, ensure_ascii=False)[:200]
            sortie = str(outil.get("result") or outil.get("output") or "")[:300]
            print("    {} {}".format(nom, args), flush=True)
            if sortie:
                print("      -> {}".format(sortie), flush=True)
    print(flush=True)
