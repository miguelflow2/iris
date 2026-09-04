# -*- coding: utf-8 -*-
"""Génère le plan financier VELA / IRIS (lunettes + abonnements)."""
import os
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.comments import Comment

OUT = r"C:\Users\migue\Downloads\startup\iris\docs\finance\VELA-IRIS-plan-financier.xlsx"
os.makedirs(os.path.dirname(OUT), exist_ok=True)

FONT = "Arial"
BLUE = Font(name=FONT, color="0000FF", size=10)
BLACK = Font(name=FONT, color="000000", size=10)
GREEN = Font(name=FONT, color="008000", size=10)
BOLD = Font(name=FONT, bold=True, size=10)
TITLE = Font(name=FONT, bold=True, size=14)
H2 = Font(name=FONT, bold=True, size=11, color="FFFFFF")
YELLOW = PatternFill("solid", fgColor="FFFF00")
HEAD = PatternFill("solid", fgColor="0F6E56")
GREY = PatternFill("solid", fgColor="F2F2F2")
THIN = Side(style="thin", color="BFBFBF")
BOX = Border(top=THIN, bottom=THIN, left=THIN, right=THIN)

CAD = '#,##0.00 "$";(#,##0.00 "$");"-"'
CAD0 = '#,##0 "$";(#,##0 "$");"-"'
USD = '#,##0.00 "US$";(#,##0.00 "US$");"-"'
USD4 = '#,##0.0000 "US$";(#,##0.0000 "US$");"-"'
PCT = '0.0%;(0.0%);"-"'
NUM = '#,##0;(#,##0);"-"'
NUM2 = '#,##0.00;(#,##0.00);"-"'

wb = Workbook()
ws_readme = wb.active
ws_readme.title = "Lisez-moi"
ws_h = wb.create_sheet("Hypothèses")
ws_hw = wb.create_sheet("Coût lunettes")
ws_api = wb.create_sheet("Coût API par utilisateur")
ws_plans = wb.create_sheet("Abonnements")
ws_proj = wb.create_sheet("Projection 12 mois")

REF = {}  # nom -> référence absolue "'Feuille'!$C$5"


def ref(name):
    return REF[name]


def q(ws):
    return "'" + ws.title + "'"


def setw(ws, widths):
    for col, w in widths.items():
        ws.column_dimensions[col].width = w


def cell(ws, addr, value, font=BLACK, fmt=None, fill=None, bold=False, align=None, comment=None):
    c = ws[addr]
    c.value = value
    c.font = Font(name=FONT, bold=bold, size=10, color=font.color) if bold else font
    if fmt:
        c.number_format = fmt
    if fill:
        c.fill = fill
    if align:
        c.alignment = Alignment(horizontal=align, wrap_text=True, vertical="top")
    if comment:
        c.comment = Comment(comment, "IRIS")
    return c


def inp(ws, addr, value, fmt=None, key=False, name=None, comment=None):
    """Cellule d'entrée (bleu, fond jaune si clé)."""
    c = cell(ws, addr, value, font=BLUE, fmt=fmt, fill=YELLOW if key else None, comment=comment)
    c.border = BOX
    if name:
        REF[name] = f"{q(ws)}!${addr[0]}${addr[1:]}" if addr[1].isdigit() else _abs(ws, addr)
    return c


def _abs(ws, addr):
    col = "".join(ch for ch in addr if ch.isalpha())
    row = "".join(ch for ch in addr if ch.isdigit())
    return f"{q(ws)}!${col}${row}"


def formula(ws, addr, f, fmt=None, name=None, bold=False, font=BLACK, fill=None):
    c = cell(ws, addr, f, font=font, fmt=fmt, bold=bold, fill=fill)
    c.border = BOX
    if name:
        REF[name] = _abs(ws, addr)
    return c


def header(ws, row, cols, texts):
    for col, t in zip(cols, texts):
        c = ws[f"{col}{row}"]
        c.value = t
        c.font = H2
        c.fill = HEAD
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        c.border = BOX


def section(ws, row, text, span="A:F"):
    c = ws[f"A{row}"]
    c.value = text
    c.font = Font(name=FONT, bold=True, size=11, color="0F6E56")
    ws.row_dimensions[row].height = 18


def label(ws, addr, text, bold=False, wrap=False):
    c = ws[addr]
    c.value = text
    c.font = BOLD if bold else BLACK
    if wrap:
        c.alignment = Alignment(wrap_text=True, vertical="top")
    return c


# =====================================================================
# 1. HYPOTHÈSES
# =====================================================================
ws = ws_h
setw(ws, {"A": 46, "B": 16, "C": 16, "D": 16, "E": 16, "F": 60})
cell(ws, "A1", "VELA / IRIS — Hypothèses (toutes les entrées modifiables sont en bleu ; fond jaune = levier clé)", TITLE)
ws.merge_cells("A1:F1")

r = 3
section(ws, r, "1. Général")
r += 1
header(ws, r, "ABCDEF"[:2] + "F", ["Paramètre", "Valeur", "Source / note"])
header(ws, r, ["A", "B", "F"], ["Paramètre", "Valeur", "Source / note"])
r += 1
label(ws, f"A{r}", "Taux de change USD → CAD")
inp(ws, f"B{r}", 1.36, NUM2, key=True, name="fx")
label(ws, f"F{r}", "Hypothèse (Banque du Canada, ~1,36 en 2026). Tous les prix affichés en CAD sauf mention US$.")
r += 1
label(ws, f"A{r}", "Taxes de vente Québec (TPS 5 % + TVQ 9,975 %)")
inp(ws, f"B{r}", 0.14975, PCT, name="taxes")
label(ws, f"F{r}", "Revenu Québec. Les prix du modèle sont hors taxes ; le prix TTC est calculé à titre indicatif.")
r += 1
label(ws, f"A{r}", "Frais de paiement Stripe — % du montant")
inp(ws, f"B{r}", 0.029, PCT, name="stripe_pct")
label(ws, f"F{r}", "Stripe Canada : 2,9 % + 0,30 $ par transaction (cartes canadiennes).")
r += 1
label(ws, f"A{r}", "Frais de paiement Stripe — fixe par transaction (CAD)")
inp(ws, f"B{r}", 0.30, CAD, name="stripe_fix")
r += 1
label(ws, f"A{r}", "Palier de volume retenu pour le prix de vente (100 / 500 / 1000 / 5000)")
inp(ws, f"B{r}", 500, NUM, key=True, name="tier_sel")
label(ws, f"F{r}", "Le prix public est fixé sur ce palier ; la marge réelle s'améliore avec le volume.")
r += 1
label(ws, f"A{r}", "Marge brute cible sur les lunettes (hors abonnement)")
inp(ws, f"B{r}", 0.45, PCT, key=True, name="hw_margin")
label(ws, f"F{r}", "Standard électronique grand public : 35–50 %. Meta vend les Ray-Ban Meta ~379 US$ pour un coût matière estimé ~150 US$.")

# --- Matériel
r += 2
section(ws, r, "2. Matériel — lunettes K900 (SmartXY) — coûts unitaires")
r += 1
header(ws, r, ["A", "B", "C", "D", "E", "F"], ["Poste", "100 unités", "500 unités", "1 000 unités", "5 000 unités", "Source / note"])
r += 1
label(ws, f"A{r}", "Prix OEM K900 par unité (US$)")
for col, v in zip("BCDE", [145, 125, 110, 95]):
    inp(ws, f"{col}{r}", v, USD, key=True)
REF["oem_row"] = r
label(ws, f"F{r}", "HYPOTHÈSE À REMPLACER par le devis SmartXY (RFQ, Partie 10 du cahier des charges). Fourchette Alibaba 2026 pour des lunettes caméra 13 MP + audio : 45–205 US$ selon chipset ; le K900 (Android, MTK + BES, Sony 13 MP, 5 micros) se situe dans le haut de la fourchette.")
r += 1
label(ws, f"A{r}", "Quantité du palier")
for col, v in zip("BCDE", [100, 500, 1000, 5000]):
    inp(ws, f"{col}{r}", v, NUM)
REF["qty_row"] = r
r += 1
label(ws, f"A{r}", "Frais non récurrents OEM : firmware, logo, packaging (US$, total)")
inp(ws, f"B{r}", 15000, USD, key=True, name="nre")
label(ws, f"F{r}", "Hypothèse : personnalisation firmware (voyant, déclic sonore), gravure VELA, boîte. Amorti sur les unités du palier.")
r += 1
label(ws, f"A{r}", "Fret + assurance par unité (US$)")
inp(ws, f"B{r}", 6, USD, name="freight")
label(ws, f"F{r}", "Hypothèse : fret aérien groupé Shenzhen → Montréal, ~300 g emballé.")
r += 1
label(ws, f"A{r}", "Droits de douane et courtage (% du prix OEM)")
inp(ws, f"B{r}", 0.05, PCT, name="duty")
label(ws, f"F{r}", "Hypothèse prudente. Vérifier le code SH (9004 lunettes vs 8525 caméras) auprès de l'ASFC ; certains codes sont à 0 %.")
r += 1
label(ws, f"A{r}", "Emballage de vente + étui + câble (US$)")
inp(ws, f"B{r}", 8, USD, name="packaging")
r += 1
label(ws, f"A{r}", "Réserve garantie 1 an (% du prix OEM)")
inp(ws, f"B{r}", 0.04, PCT, name="warranty")
label(ws, f"F{r}", "Hypothèse : 4 % de taux de défaut couvert par remplacement.")
r += 1
label(ws, f"A{r}", "Préparation + expédition au client (CAD)")
inp(ws, f"B{r}", 12, CAD, name="fulfil")
label(ws, f"F{r}", "Postes Canada / Purolator colis léger au Québec, étiquette + main-d'œuvre.")
r += 1
label(ws, f"A{r}", "Retours et remboursements (% des ventes)")
inp(ws, f"B{r}", 0.03, PCT, name="returns")

# --- Concurrence
r += 2
section(ws, r, "3. Repères de prix concurrents (prix public, US$ hors taxes)")
r += 1
header(ws, r, ["A", "B", "F"], ["Produit", "Prix US$", "Source"])
comp = [
    ("Meta Glasses (sans marque Ray-Ban, juin 2026)", 299, "CNBC, 23 juin 2026 — cnbc.com/2026/06/23/meta-glasses-are-new-smart-glasses-starting-at-299.html"),
    ("Ray-Ban Meta (Gen 2/3)", 379, "TechCrunch, 31 mars 2026 — 'begin at $379'"),
    ("Ray-Ban Meta prescription (optique)", 499, "TechCrunch, 31 mars 2026"),
    ("Meta Ray-Ban Display (avec écran)", 799, "Meta.com / TechCrunch"),
    ("Snap Specs (AR, autonome)", 2195, "Tom's Guide 2026 — précommande"),
]
REF["comp_first"] = r + 1
for name, price, src in comp:
    r += 1
    label(ws, f"A{r}", name)
    inp(ws, f"B{r}", price, USD)
    label(ws, f"F{r}", src)
REF["comp_last"] = r

# --- API prices
r += 2
section(ws, r, "4. Prix des API (US$ par million de jetons) — modèles réellement câblés dans IRIS")
r += 1
header(ws, r, ["A", "B", "C", "D", "F"], ["Modèle", "Entrée", "Sortie", "Vision (image)", "Source (vérifié le 2 sept. 2026)"])
models = [
    ("OpenRouter — minimax/minimax-m3:free (défaut IRIS)", 0, 0, "OpenRouter, palier gratuit (limites de débit, bascule automatique). Aucun coût mais aucune garantie de disponibilité."),
    ("Google Gemini 2.5 Flash", 0.30, 2.50, "ai.google.dev/gemini-api/docs/pricing — modèle par défaut du connecteur Gemini d'IRIS."),
    ("Google Gemini 3.7 Flash", 0.75, 3.75, "ai.google.dev — DOUBLE au 1er janvier 2027 (1,50 / 7,50)."),
    ("Google Gemini 2.5 Pro", 1.25, 10.00, "ai.google.dev — prompts ≤ 200k jetons."),
    ("OpenAI GPT-5 mini", 0.25, 2.00, "openai.com/api/pricing (via pricepertoken.com) — défaut du connecteur GPT d'IRIS."),
    ("OpenAI GPT-5", 1.25, 10.00, "openai.com/api/pricing (via cloudzero.com)."),
    ("Anthropic Claude Haiku 4.5", 1.00, 5.00, "Référence tarifaire Anthropic (skill claude-api, cache 24 juin 2026)."),
    ("Anthropic Claude Sonnet 5", 2.00, 10.00, "Référence tarifaire Anthropic."),
    ("Anthropic Claude Opus 5 (défaut IRIS)", 5.00, 25.00, "Référence tarifaire Anthropic — modèle Claude par défaut dans config.py."),
    ("Anthropic Claude Fable 5.1", 10.00, 50.00, "Référence tarifaire Anthropic — réservé aux tâches complexes."),
]
REF["models_first"] = r + 1
for name, pin, pout, src in models:
    r += 1
    label(ws, f"A{r}", name)
    inp(ws, f"B{r}", pin, USD4)
    inp(ws, f"C{r}", pout, USD4)
    formula(ws, f"D{r}", f"=B{r}", USD4)
    label(ws, f"F{r}", src)
REF["models_last"] = r
r += 1
label(ws, f"A{r}", "Jetons par capture d'écran envoyée au modèle de vision")
inp(ws, f"B{r}", 1600, NUM, name="img_tokens")
label(ws, f"F{r}", "Ordre de grandeur pour une image 1 280×800 (≈ largeur×hauteur/750 chez Anthropic).")

# --- ElevenLabs
r += 2
section(ws, r, "5. ElevenLabs — voix d'IRIS (modèle eleven_flash_v2_5, voix « Mélanie »)")
r += 1
header(ws, r, ["A", "B", "C", "D", "F"], ["Plan", "Prix US$/mois", "Crédits/mois", "US$ / 1 000 crédits", "Source"])
el = [("Free", 0, 10000), ("Starter", 6, 30000), ("Creator", 22, 121000), ("Pro", 99, 600000), ("Scale", 299, 1800000), ("Business", 990, 6000000)]
REF["el_first"] = r + 1
for name, price, credits in el:
    r += 1
    label(ws, f"A{r}", name)
    inp(ws, f"B{r}", price, USD)
    inp(ws, f"C{r}", credits, NUM)
    formula(ws, f"D{r}", f"=IF(C{r}=0,0,B{r}/C{r}*1000)", USD4)
    label(ws, f"F{r}", "elevenlabs.io/pricing (2 sept. 2026). Creator : 11 US$ le premier mois.")
REF["el_last"] = r
r += 1
label(ws, f"A{r}", "Plan ElevenLabs souscrit (liste déroulante)")
inp(ws, f"B{r}", "Scale", key=True, name="el_plan")
dv = DataValidation(type="list", formula1=f"{q(ws)}!$A${REF['el_first']}:$A${REF['el_last']}", allow_blank=False)
ws.add_data_validation(dv)
dv.add(ws[f"B{r}"])
label(ws, f"F{r}", "Le plan détermine le coût marginal par caractère et le coût fixe mensuel. Scale = 1,8 M crédits ≈ 3,6 M caractères Flash.")
r += 1
label(ws, f"A{r}", "Coût fixe du plan choisi (US$/mois)")
formula(ws, f"B{r}", f"=INDEX($B${REF['el_first']}:$B${REF['el_last']},MATCH({ref('el_plan')},$A${REF['el_first']}:$A${REF['el_last']},0))", USD, name="el_fixed")
r += 1
label(ws, f"A{r}", "Crédits inclus dans le plan choisi")
formula(ws, f"B{r}", f"=INDEX($C${REF['el_first']}:$C${REF['el_last']},MATCH({ref('el_plan')},$A${REF['el_first']}:$A${REF['el_last']},0))", NUM, name="el_credits")
r += 1
label(ws, f"A{r}", "Coût marginal (US$ / 1 000 crédits)")
formula(ws, f"B{r}", f"=INDEX($D${REF['el_first']}:$D${REF['el_last']},MATCH({ref('el_plan')},$A${REF['el_first']}:$A${REF['el_last']},0))", USD4, name="el_unit")
label(ws, f"F{r}", "Le dépassement de quota est facturé à un tarif proche du tarif moyen du plan (Scale ≈ 0,17 US$/1 000 crédits).")
r += 1
label(ws, f"A{r}", "Crédits par caractère — eleven_flash_v2_5 / turbo")
inp(ws, f"B{r}", 0.5, NUM2, name="el_char")
label(ws, f"F{r}", "elevenlabs.io/pricing : Flash/Turbo v2.5 = 0,5 crédit par caractère (Multilingual v2 = 1 crédit).")
r += 1
label(ws, f"A{r}", "Voix alternative — OpenAI gpt-4o-mini-tts (US$ / 1 000 caractères)")
inp(ws, f"B{r}", 0.015, USD4, name="tts_alt")
label(ws, f"F{r}", "HYPOTHÈSE à vérifier sur openai.com/api/pricing (~0,015 US$/1 000 caractères, soit ~5 × moins cher qu'ElevenLabs Scale). Voix française moins naturelle : option de repli pour les plans d'entrée.")
r += 1
label(ws, f"A{r}", "Reconnaissance vocale cloud (US$ / minute audio)")
inp(ws, f"B{r}", 0.016, USD4, name="stt_min")
label(ws, f"F{r}", "IRIS utilise Vosk hors-ligne (0 $) par défaut ; Google STT (avec consentement) ≈ 0,016 US$/min — HYPOTHÈSE à vérifier sur cloud.google.com/speech-to-text/pricing.")
r += 1
label(ws, f"A{r}", "Part des requêtes traitées par la reconnaissance cloud")
inp(ws, f"B{r}", 0.3, PCT, name="stt_share")
label(ws, f"F{r}", "Hypothèse : 30 % (micro Bluetooth de qualité téléphone → bascule cloud).")

# --- Usage profiles
r += 2
section(ws, r, "6. Profils d'usage mensuels par utilisateur")
r += 1
header(ws, r, ["A", "B", "C", "D", "F"], ["Paramètre", "Léger", "Moyen", "Intensif", "Note"])
REF["prof_head"] = r
prof = [
    ("Requêtes vocales par jour", [8, 20, 40], NUM, "req_day", "Hypothèse. Un usage 'assistant au quotidien' tourne autour de 20–30 commandes/jour."),
    ("Jours d'utilisation par mois", [20, 26, 30], NUM, "days", ""),
    ("Jetons d'entrée par requête (prompt système + outils + historique)", [2500, 3000, 3500], NUM, "tok_in", "Le prompt système d'IRIS + définitions d'outils PC ≈ 2 000 jetons ; l'historique ajoute le reste."),
    ("Jetons de sortie par requête (réponse vocale courte, effort « low »)", [80, 120, 160], NUM, "tok_out", "≈ 80–130 mots parlés."),
    ("Caractères lus par ElevenLabs par requête", [150, 200, 260], NUM, "chars", "Moyenne entre confirmations courtes (« C'est fait ») et réponses de 2–3 phrases ; 200 caractères ≈ 13 s de parole. Premier poste de coût : à mesurer dans le compteur ElevenLabs."),
    ("Minutes audio dictées par requête", [0.1, 0.12, 0.15], NUM2, "audio_min", "7–12 s de parole par commande."),
    ("Part des requêtes avec capture d'écran (vision)", [0.05, 0.10, 0.20], PCT, "img_share", "Contrôle complet de l'écran (computer_use) : chaque boucle envoie une capture."),
]
for name, vals, fmt, key, note in prof:
    r += 1
    label(ws, f"A{r}", name)
    for col, v in zip("BCD", vals):
        inp(ws, f"{col}{r}", v, fmt, key=(key == "req_day"))
    REF[key + "_row"] = r
    label(ws, f"F{r}", note)

# --- Fixed provider subscriptions
r += 2
section(ws, r, "7. Coûts fixes mensuels de l'entreprise (US$ ou CAD selon la colonne)")
r += 1
header(ws, r, ["A", "B", "C", "F"], ["Poste", "US$/mois", "CAD/mois", "Note"])
fixed = [
    ("ElevenLabs — plan choisi", f"={ref('el_fixed')}", None, "Lié au plan de la section 5."),
    ("Claude Pro (compte développeur, Claude Code)", 20, None, "claude.ai — 20 US$/mois (17 US$ en annuel). Max : 100 ou 200 US$. NE PEUT PAS servir les clients : l'usage clients passe par l'API (prépayée, console.anthropic.com)."),
    ("ChatGPT Plus (compte développeur)", 20, None, "openai.com — 20 US$/mois. Même règle : l'API se paie à part."),
    ("Google AI Pro (compte développeur)", 19.99, None, "one.google.com — 19,99 US$/mois. L'API Gemini a un palier gratuit + facturation à l'usage."),
    ("Hébergement / domaine / courriel (site VELA, mises à jour de l'app)", 25, None, "Hypothèse : VPS léger + domaine. Le backend IRIS tourne en local chez l'utilisateur, pas de serveur d'inférence."),
    ("Outils : Stripe (abonnement 0), signature de code Windows, licences", 30, None, "Certificat de signature de code ~300 US$/an amorti."),
    ("Comptabilité / assurance responsabilité / frais bancaires", None, 150, "Hypothèse Québec, entreprise individuelle ou inc."),
    ("Marketing (publicités, contenu, échantillons)", None, 400, "Hypothèse de démarrage ; à ajuster selon le budget."),
]
REF["fixed_first"] = r + 1
for name, usd, cad, note in fixed:
    r += 1
    label(ws, f"A{r}", name)
    if usd is not None:
        if isinstance(usd, str):
            formula(ws, f"B{r}", usd, USD, font=GREEN)
        else:
            inp(ws, f"B{r}", usd, USD)
        formula(ws, f"C{r}", f"=B{r}*{ref('fx')}", CAD)
    else:
        inp(ws, f"C{r}", cad, CAD)
    label(ws, f"F{r}", note)
REF["fixed_last"] = r
r += 1
label(ws, f"A{r}", "Total coûts fixes (CAD/mois)", bold=True)
formula(ws, f"C{r}", f"=SUM(C{REF['fixed_first']}:C{REF['fixed_last']})", CAD, name="fixed_total", bold=True)
label(ws, f"A{r+1}", "Salaire fondateur (CAD/mois) — 0 au démarrage, à ajouter quand la trésorerie le permet")
inp(ws, f"C{r+1}", 0, CAD, key=True, name="salary")
REF["h_last"] = r + 1

for row in ws.iter_rows(min_row=1, max_row=REF["h_last"], min_col=6, max_col=6):
    for c in row:
        c.alignment = Alignment(wrap_text=True, vertical="top")
ws.freeze_panes = "B4"


def model_price(idx, col):
    """Référence au prix d'un modèle (idx 0-based dans la liste 'models'), col B=entrée, C=sortie."""
    return f"{q(ws_h)}!${col}${REF['models_first'] + idx}"


# =====================================================================
# 2. COÛT LUNETTES
# =====================================================================
ws = ws_hw
setw(ws, {"A": 52, "B": 16, "C": 16, "D": 16, "E": 16, "F": 50})
cell(ws, "A1", "Coût de revient et prix de vente des lunettes VELA (K900 + IRIS)", TITLE)
ws.merge_cells("A1:F1")
label(ws, "A2", "Toutes les valeurs sont calculées à partir de la feuille Hypothèses. Colonnes = palier de commande OEM.")

r = 4
header(ws, r, ["A", "B", "C", "D", "E", "F"], ["Poste (par unité)", "100 unités", "500 unités", "1 000 unités", "5 000 unités", "Formule / note"])
H = q(ws_h)
oem = REF["oem_row"]
qty = REF["qty_row"]
rows = {}


def hw_row(key, text, f_by_col, fmt, note="", bold=False, fill=None):
    global r
    r += 1
    label(ws, f"A{r}", text, bold=bold)
    for col in "BCDE":
        formula(ws, f"{col}{r}", f_by_col(col), fmt, bold=bold, fill=fill)
    if note:
        label(ws, f"F{r}", note, wrap=True)
    rows[key] = r


hw_row("qty", "Quantité commandée", lambda c: f"={H}!{c}{qty}", NUM)
hw_row("oem", "Prix OEM (US$)", lambda c: f"={H}!{c}{oem}", USD, "Devis SmartXY à insérer dans Hypothèses.")
hw_row("nre", "Frais non récurrents amortis (US$)", lambda c: f"={ref('nre')}/{c}{rows['qty']}", USD)
hw_row("freight", "Fret + assurance (US$)", lambda c: f"={ref('freight')}", USD)
hw_row("duty", "Douane + courtage (US$)", lambda c: f"={c}{rows['oem']}*{ref('duty')}", USD)
hw_row("pack", "Emballage, étui, câble (US$)", lambda c: f"={ref('packaging')}", USD)
hw_row("warr", "Réserve garantie (US$)", lambda c: f"={c}{rows['oem']}*{ref('warranty')}", USD)
hw_row("sub_usd", "Coût rendu entrepôt (US$)", lambda c: f"=SUM({c}{rows['oem']}:{c}{rows['warr']})", USD, bold=True)
hw_row("sub_cad", "Coût rendu entrepôt (CAD)", lambda c: f"={c}{rows['sub_usd']}*{ref('fx')}", CAD, "Conversion au taux de la feuille Hypothèses.")
hw_row("fulfil", "Préparation + expédition client (CAD)", lambda c: f"={ref('fulfil')}", CAD)
hw_row("cost", "COÛT DE REVIENT COMPLET (CAD, hors retours et paiement)", lambda c: f"={c}{rows['sub_cad']}+{c}{rows['fulfil']}", CAD, bold=True, fill=GREY)

r += 1
r += 1
section(ws, r, "Prix de vente")
hw_row("price_margin", "Prix HT nécessaire pour la marge cible (CAD)", lambda c: f"={c}{rows['cost']}/(1-{ref('hw_margin')}-{ref('returns')}-{ref('stripe_pct')})", CAD, "Formule : coût / (1 − marge cible − retours − frais Stripe %). La marge cible est nette des retours et des frais de paiement.")
hw_row("price_round", "Prix public recommandé HT (CAD, arrondi psychologique x49/x99)", lambda c: f"=CEILING({c}{rows['price_margin']},50)-1", CAD, bold=True, fill=YELLOW)
hw_row("price_ttc", "Prix TTC affiché au Québec (CAD)", lambda c: f"={c}{rows['price_round']}*(1+{ref('taxes')})", CAD)
hw_row("price_usd", "Équivalent US$ (pour comparer aux concurrents)", lambda c: f"={c}{rows['price_round']}/{ref('fx')}", USD)
hw_row("stripe", "Frais Stripe par vente (CAD)", lambda c: f"={c}{rows['price_round']}*{ref('stripe_pct')}+{ref('stripe_fix')}", CAD)
hw_row("ret_cost", "Coût des retours par vente (CAD)", lambda c: f"={c}{rows['price_round']}*{ref('returns')}", CAD)
hw_row("gp", "Marge brute par paire vendue (CAD)", lambda c: f"={c}{rows['price_round']}-{c}{rows['cost']}-{c}{rows['stripe']}-{c}{rows['ret_cost']}", CAD, bold=True)
hw_row("gp_pct", "Marge brute réelle (%)", lambda c: f"=IF({c}{rows['price_round']}=0,0,{c}{rows['gp']}/{c}{rows['price_round']})", PCT, bold=True)
hw_row("capital", "Capital à immobiliser pour la commande (CAD, rendu entrepôt)", lambda c: f"={c}{rows['sub_cad']}*{c}{rows['qty']}", CAD0, "Trésorerie nécessaire avant la première vente du palier (hors marketing).")

r += 2
section(ws, r, "Prix retenu (palier choisi dans Hypothèses)")
r += 1
label(ws, f"A{r}", "Palier choisi")
formula(ws, f"B{r}", f"={ref('tier_sel')}", NUM, font=GREEN)
r += 1
label(ws, f"A{r}", "Prix public HT retenu (CAD)", bold=True)
formula(ws, f"B{r}", f"=INDEX(B{rows['price_round']}:E{rows['price_round']},MATCH({ref('tier_sel')},B{rows['qty']}:E{rows['qty']},0))", CAD, name="hw_price", bold=True, fill=YELLOW)
r += 1
label(ws, f"A{r}", "Coût de revient complet retenu (CAD)")
formula(ws, f"B{r}", f"=INDEX(B{rows['cost']}:E{rows['cost']},MATCH({ref('tier_sel')},B{rows['qty']}:E{rows['qty']},0))", CAD, name="hw_cost")
r += 1
label(ws, f"A{r}", "Marge brute par paire retenue (CAD)")
formula(ws, f"B{r}", f"=INDEX(B{rows['gp']}:E{rows['gp']},MATCH({ref('tier_sel')},B{rows['qty']}:E{rows['qty']},0))", CAD, name="hw_gp")
r += 1
label(ws, f"A{r}", "Prix TTC retenu (CAD)")
formula(ws, f"B{r}", f"={ref('hw_price')}*(1+{ref('taxes')})", CAD)

r += 2
section(ws, r, "Positionnement face aux concurrents (convertis en CAD)")
r += 1
header(ws, r, ["A", "B", "C", "D"], ["Produit", "Prix US$", "Prix CAD", "Écart VELA vs concurrent"])
for i in range(REF["comp_first"], REF["comp_last"] + 1):
    r += 1
    formula(ws, f"A{r}", f"={H}!A{i}", font=GREEN)
    formula(ws, f"B{r}", f"={H}!B{i}", USD, font=GREEN)
    formula(ws, f"C{r}", f"=B{r}*{ref('fx')}", CAD)
    formula(ws, f"D{r}", f"=IF(C{r}=0,0,{ref('hw_price')}/C{r}-1)", PCT)
r += 1
label(ws, f"A{r}", "VELA (prix HT retenu)", bold=True)
formula(ws, f"B{r}", f"={ref('hw_price')}/{ref('fx')}", USD, bold=True)
formula(ws, f"C{r}", f"={ref('hw_price')}", CAD, bold=True)
r += 2
label(ws, f"A{r}", "Lecture : VELA n'a pas d'écran ni de marque de lunetier ; le différenciateur est IRIS (confidentialité, contrôle du PC, agents au choix). Rester sous les Ray-Ban Meta (379 US$) et au-dessus des Meta Glasses (299 US$) est cohérent tant que le coût OEM reste ≤ 125 US$.", wrap=True)
ws.merge_cells(f"A{r}:F{r}")
ws.row_dimensions[r].height = 45
ws.freeze_panes = "B5"

# =====================================================================
# 3. COÛT API PAR UTILISATEUR
# =====================================================================
ws = ws_api
setw(ws, {"A": 56, "B": 16, "C": 16, "D": 16, "E": 50})
cell(ws, "A1", "Coût variable des API par utilisateur et par mois (CAD)", TITLE)
ws.merge_cells("A1:E1")
label(ws, "A2", "Trois profils d'usage (Hypothèses §6). Chaque ligne « modèle » donne le coût mensuel si TOUTES les requêtes passaient par ce modèle.")

r = 4
header(ws, r, ["A", "B", "C", "D", "E"], ["Poste", "Léger", "Moyen", "Intensif", "Note"])
arow = {}
PC = {"B": "B", "C": "C", "D": "D"}  # profile columns identical in Hypothèses


def api_row(key, text, f_by_col, fmt, note="", bold=False, fill=None):
    global r
    r += 1
    label(ws, f"A{r}", text, bold=bold)
    for col in "BCD":
        formula(ws, f"{col}{r}", f_by_col(col), fmt, bold=bold, fill=fill)
    if note:
        label(ws, f"E{r}", note, wrap=True)
    arow[key] = r


hr = lambda key, col: f"{H}!{col}{REF[key + '_row']}"
api_row("req", "Requêtes par mois", lambda c: f"={hr('req_day', c)}*{hr('days', c)}", NUM)
api_row("tin", "Jetons d'entrée par mois (texte)", lambda c: f"={c}{arow['req']}*{hr('tok_in', c)}", NUM)
api_row("timg", "Jetons d'entrée par mois (captures d'écran)", lambda c: f"={c}{arow['req']}*{hr('img_share', c)}*{ref('img_tokens')}", NUM)
api_row("tout", "Jetons de sortie par mois", lambda c: f"={c}{arow['req']}*{hr('tok_out', c)}", NUM)

r += 1
r += 1
section(ws, r, "A. Modèle de langage — coût mensuel selon le modèle (CAD)")
model_rows = {}
for i, (name, pin, pout, src) in enumerate(models):
    api_row(f"m{i}", name, lambda c, i=i: f"=(({c}{arow['tin']}+{c}{arow['timg']})*{model_price(i, 'B')}+{c}{arow['tout']}*{model_price(i, 'C')})/1000000*{ref('fx')}", CAD)
    model_rows[i] = r

r += 1
r += 1
section(ws, r, "B. Voix ElevenLabs (CAD)")
api_row("chars", "Caractères synthétisés par mois", lambda c: f"={c}{arow['req']}*{hr('chars', c)}", NUM)
api_row("credits", "Crédits ElevenLabs consommés", lambda c: f"={c}{arow['chars']}*{ref('el_char')}", NUM)
api_row("tts", "Coût ElevenLabs au tarif marginal du plan (CAD)", lambda c: f"={c}{arow['credits']}/1000*{ref('el_unit')}*{ref('fx')}", CAD, "Le plan a un coût fixe (Hypothèses §7) ; ici seulement le coût par caractère.", bold=True)
api_row("tts_alt", "Comparaison : même volume avec la voix OpenAI (CAD)", lambda c: f"={c}{arow['chars']}/1000*{ref('tts_alt')}*{ref('fx')}", CAD, "Levier n°1 si la marge des plans d'entrée est trop faible.")
api_row("users_el", "Utilisateurs couverts par les crédits du plan (indicatif)", lambda c: f"=IF({c}{arow['credits']}=0,0,{ref('el_credits')}/{c}{arow['credits']})", NUM, "Au-delà, dépassement facturé ou plan supérieur.")

r += 1
r += 1
section(ws, r, "C. Reconnaissance vocale (CAD)")
api_row("stt_min", "Minutes audio envoyées au cloud par mois", lambda c: f"={c}{arow['req']}*{hr('audio_min', c)}*{ref('stt_share')}", NUM2, "Le reste est traité hors-ligne par Vosk (gratuit).")
api_row("stt", "Coût reconnaissance cloud (CAD)", lambda c: f"={c}{arow['stt_min']}*{ref('stt_min')}*{ref('fx')}", CAD, bold=True)

r += 1
r += 1
section(ws, r, "D. Coût variable total par utilisateur selon la pile de modèles (CAD/mois)")
# stacks: name, list of (model_idx, share)
stacks = [
    ("Pile GRATUIT : OpenRouter gratuit + voix Windows (pas d'ElevenLabs)", [(0, 1.0)], False),
    ("Pile ESSENTIEL : Gemini 2.5 Flash 70 % + GPT-5 mini 30 % + ElevenLabs", [(1, 0.7), (4, 0.3)], True),
    ("Pile PRO : Claude Sonnet 5 60 % + Gemini 2.5 Flash 30 % + GPT-5 10 % + ElevenLabs", [(7, 0.6), (1, 0.3), (5, 0.1)], True),
    ("Pile ULTRA : Claude Opus 5 50 % + Claude Sonnet 5 30 % + GPT-5 20 % + ElevenLabs", [(8, 0.5), (7, 0.3), (5, 0.2)], True),
]
stack_rows = []
for name, mix, tts in stacks:
    parts = "+".join(f"{{c}}{model_rows[i]}*{s}" for i, s in mix)
    extra = f"+{{c}}{arow['tts']}+{{c}}{arow['stt']}" if tts else ""
    api_row(f"stack{len(stack_rows)}", name, lambda c, p=parts, e=extra: "=" + (p + e).replace("{c}", c), CAD, bold=True, fill=GREY)
    stack_rows.append(r)
REF["stack_rows"] = stack_rows
REF["api_stack_cols"] = {"Léger": "B", "Moyen": "C", "Intensif": "D"}
r += 2
label(ws, f"A{r}", "Lecture : la voix ElevenLabs est le premier poste de coût en usage intensif ; le modèle de langage ne pèse vraiment qu'avec Claude Opus 5. D'où l'intérêt de réserver Opus aux tâches longues (reasoning_model) et de garder un modèle rapide pour la voix (voice_model).", wrap=True)
ws.merge_cells(f"A{r}:E{r}")
ws.row_dimensions[r].height = 45
ws.freeze_panes = "B5"

# =====================================================================
# 4. ABONNEMENTS
# =====================================================================
ws = ws_plans
setw(ws, {"A": 46, "B": 22, "C": 22, "D": 22, "E": 22, "F": 44})
cell(ws, "A1", "Plans d'abonnement IRIS — prix, coût par abonné et marge (CAD, hors taxes)", TITLE)
ws.merge_cells("A1:F1")
label(ws, "A2", "Les prix mensuels sont des entrées (bleu). Le coût par abonné vient de la feuille Coût API selon le profil d'usage associé au plan.")

r = 4
header(ws, r, ["A", "B", "C", "D", "E", "F"], ["", "GRATUIT", "ESSENTIEL", "PRO", "ULTRA", "Note"])
plan_cols = "BCDE"
r += 1
label(ws, f"A{r}", "Prix mensuel HT (CAD)", bold=True)
for col, v in zip(plan_cols, [0, 19.99, 29.99, 99.99]):
    inp(ws, f"{col}{r}", v, CAD, key=True)
prow_price = r
REF["plan_price_row"] = r
label(ws, f"F{r}", "Repère marché : ChatGPT Plus / Claude Pro / Google AI Pro = 20 US$ ≈ 27 CAD. PRO doit rester proche de ce repère ; ULTRA inclut Opus 5.", wrap=True)
r += 1
label(ws, f"A{r}", "Prix annuel HT (CAD) — 2 mois offerts")
for col in plan_cols:
    formula(ws, f"{col}{r}", f"={col}{prow_price}*10", CAD)
r += 1
label(ws, f"A{r}", "Profil d'usage associé (Léger / Moyen / Intensif)")
for col, v in zip(plan_cols, ["Léger", "Moyen", "Moyen", "Intensif"]):
    inp(ws, f"{col}{r}", v)
prow_prof = r
dv2 = DataValidation(type="list", formula1='"Léger,Moyen,Intensif"', allow_blank=False)
ws.add_data_validation(dv2)
for col in plan_cols:
    dv2.add(ws[f"{col}{prow_prof}"])
r += 1
label(ws, f"A{r}", "Pile de modèles (voir Coût API §D)")
for col, v in zip(plan_cols, ["Gratuit", "Essentiel", "Pro", "Ultra"]):
    cell(ws, f"{col}{r}", v, align="center")
r += 1
label(ws, f"A{r}", "Quota de requêtes vocales par mois")
for col, v in zip(plan_cols, [150, 500, 800, 1500]):
    inp(ws, f"{col}{r}", v, NUM)
prow_quota = r
label(ws, f"F{r}", "Plafond « fair use » à coder dans IRIS pour borner le coût d'un abonné intensif.", wrap=True)
r += 1
label(ws, f"A{r}", "Ce qui est inclus", bold=True)
incl = [
    "Modèles gratuits OpenRouter (minimax-m3:free), voix Windows, contrôle du PC, Vosk hors-ligne. Clés API personnelles possibles.",
    "Voix ElevenLabs « Mélanie », Gemini 2.5 Flash + GPT-5 mini, sites web enregistrés (Omnivox…), routines, rappels.",
    "Tout ESSENTIEL + Claude Sonnet 5 pour le raisonnement, vision de l'écran (computer_use), résumé quotidien, mémoire.",
    "Tout PRO + Claude Opus 5 pour les tâches longues, quota élevé, support prioritaire, accès anticipé aux nouveautés.",
]
for col, v in zip(plan_cols, incl):
    cell(ws, f"{col}{r}", v, align="left")
ws.row_dimensions[r].height = 110

r += 2
section(ws, r, "Coût et marge par abonné (CAD/mois)")
api_q = q(ws_api)
sr = REF["stack_rows"]
r += 1
label(ws, f"A{r}", "Coût API variable par abonné")
for i, col in enumerate(plan_cols):
    # profile column in Coût API chosen by MATCH on header row 4 (B..D = Léger/Moyen/Intensif)
    formula(ws, f"{col}{r}", f"=INDEX({api_q}!$B${sr[i]}:$D${sr[i]},1,MATCH({col}{prow_prof},{api_q}!$B$4:$D$4,0))", CAD, font=GREEN)
prow_api = r
REF["plan_api_row"] = r
r += 1
label(ws, f"A{r}", "Frais Stripe")
for col in plan_cols:
    formula(ws, f"{col}{r}", f"=IF({col}{prow_price}=0,0,{col}{prow_price}*{ref('stripe_pct')}+{ref('stripe_fix')})", CAD)
prow_stripe = r
r += 1
label(ws, f"A{r}", "Marge brute par abonné (CAD)", bold=True)
for col in plan_cols:
    formula(ws, f"{col}{r}", f"={col}{prow_price}-{col}{prow_api}-{col}{prow_stripe}", CAD, bold=True)
prow_gp = r
REF["plan_gp_row"] = r
r += 1
label(ws, f"A{r}", "Marge brute (%)", bold=True)
for col in plan_cols:
    formula(ws, f"{col}{r}", f"=IF({col}{prow_price}=0,0,{col}{prow_gp}/{col}{prow_price})", PCT, bold=True, fill=GREY)
r += 1
label(ws, f"A{r}", "Coût API si l'abonné consomme tout son quota (pire cas)")
for i, col in enumerate(plan_cols):
    # scale variable cost linearly with quota vs. profile requests
    formula(ws, f"{col}{r}", f"=IF({col}{prow_quota}=0,0,{col}{prow_api}*{col}{prow_quota}/INDEX({api_q}!$B${arow['req']}:$D${arow['req']},1,MATCH({col}{prow_prof},{api_q}!$B$4:$D$4,0)))", CAD)
prow_worst = r
r += 1
label(ws, f"A{r}", "Marge brute au pire cas (%)")
for col in plan_cols:
    formula(ws, f"{col}{r}", f"=IF({col}{prow_price}=0,0,({col}{prow_price}-{col}{prow_worst}-{col}{prow_stripe})/{col}{prow_price})", PCT)
label(ws, f"F{r}", "Doit rester positif : sinon baisser le quota ou monter le prix.", wrap=True)

r += 2
section(ws, r, "Offres groupées lunettes + abonnement")
r += 1
header(ws, r, ["A", "B", "C", "D", "F"], ["Offre", "Prix HT (CAD)", "Coût (CAD)", "Marge brute (CAD)", "Note"])
r += 1
label(ws, f"A{r}", "Lunettes seules")
formula(ws, f"B{r}", f"={ref('hw_price')}", CAD, font=GREEN)
formula(ws, f"C{r}", f"={ref('hw_cost')}", CAD, font=GREEN)
formula(ws, f"D{r}", f"=B{r}-C{r}-B{r}*({ref('stripe_pct')}+{ref('returns')})-{ref('stripe_fix')}", CAD)
r += 1
label(ws, f"A{r}", "Lunettes + 12 mois PRO (remise sur l'abonnement)")
inp(ws, f"F{r}", 0.20, PCT, comment="Remise appliquée aux 12 mois d'abonnement dans l'offre groupée.")
formula(ws, f"B{r}", f"=CEILING({ref('hw_price')}+D{prow_price}*12*(1-F{r}),10)-1", CAD)
formula(ws, f"C{r}", f"={ref('hw_cost')}+D{prow_api}*12", CAD)
formula(ws, f"D{r}", f"=B{r}-C{r}-B{r}*({ref('stripe_pct')}+{ref('returns')})-{ref('stripe_fix')}", CAD)
r += 1
label(ws, f"A{r}", "Lunettes + 12 mois ULTRA (remise sur l'abonnement)")
inp(ws, f"F{r}", 0.20, PCT)
formula(ws, f"B{r}", f"=CEILING({ref('hw_price')}+E{prow_price}*12*(1-F{r}),10)-1", CAD)
formula(ws, f"C{r}", f"={ref('hw_cost')}+E{prow_api}*12", CAD)
formula(ws, f"D{r}", f"=B{r}-C{r}-B{r}*({ref('stripe_pct')}+{ref('returns')})-{ref('stripe_fix')}", CAD)
r += 2
label(ws, f"A{r}", "Règle importante : les abonnements grand public ChatGPT Plus, Claude Pro et Google AI Pro couvrent ton usage personnel et le développement. Pour servir des clients, IRIS doit appeler les API (facturées à l'usage, prépayées) — ce sont ces coûts qui figurent ici. Revendre l'accès via un compte grand public viole les conditions d'utilisation.", wrap=True)
ws.merge_cells(f"A{r}:F{r}")
ws.row_dimensions[r].height = 60
ws.freeze_panes = "B5"

# =====================================================================
# 5. PROJECTION 12 MOIS
# =====================================================================
ws = ws_proj
setw(ws, {"A": 44})
for i in range(2, 15):
    ws.column_dimensions[get_column_letter(i)].width = 13
cell(ws, "A1", "Projection 12 mois — ventes de lunettes + abonnements (CAD, hors taxes)", TITLE)
ws.merge_cells("A1:N1")

r = 3
section(ws, r, "Leviers (entrées)")
r += 1
label(ws, f"A{r}", "Part des acheteurs qui prennent un abonnement payant")
inp(ws, f"B{r}", 0.6, PCT, key=True, name="attach")
r += 1
label(ws, f"A{r}", "Répartition des abonnés payants : ESSENTIEL / PRO / ULTRA")
inp(ws, f"B{r}", 0.5, PCT, name="mix_ess")
inp(ws, f"C{r}", 0.4, PCT, name="mix_pro")
inp(ws, f"D{r}", 0.1, PCT, name="mix_ultra")
formula(ws, f"E{r}", f"=B{r}+C{r}+D{r}", PCT)
label(ws, f"F{r}", "← doit faire 100 %")
r += 1
label(ws, f"A{r}", "Désabonnement mensuel (churn)")
inp(ws, f"B{r}", 0.05, PCT, key=True, name="churn")
r += 1
label(ws, f"A{r}", "Abonnés logiciel seuls (sans lunettes) recrutés par mois, en % des lunettes vendues")
inp(ws, f"B{r}", 0.5, PCT, name="sw_only")
label(ws, f"F{r}", "IRIS fonctionne aussi sans lunettes (app Windows) : source d'abonnés supplémentaire.")

r += 2
MONTHS = 12
mcols = [get_column_letter(2 + i) for i in range(MONTHS)]  # B..M
TOT = get_column_letter(2 + MONTHS)  # N
header(ws, r, ["A"] + mcols + [TOT], ["Poste"] + [f"Mois {i+1}" for i in range(MONTHS)] + ["Total / fin"])
prow = {}


def proj_row(key, text, f_by_idx, fmt, total=None, bold=False, fill=None, is_input=False):
    global r
    r += 1
    prow[key] = r
    label(ws, f"A{r}", text, bold=bold)
    for i, col in enumerate(mcols):
        v = f_by_idx(i, col)
        if is_input:
            inp(ws, f"{col}{r}", v, fmt, key=True)
        else:
            formula(ws, f"{col}{r}", v, fmt, bold=bold, fill=fill)
    if total == "sum":
        formula(ws, f"{TOT}{r}", f"=SUM(B{r}:{mcols[-1]}{r})", fmt, bold=True)
    elif total == "last":
        formula(ws, f"{TOT}{r}", f"={mcols[-1]}{r}", fmt, bold=True)
    prow[key] = r


units = [5, 10, 15, 20, 30, 40, 50, 60, 80, 100, 120, 150]
proj_row("units", "Lunettes vendues (entrée)", lambda i, c: units[i], NUM, "sum", is_input=True)
proj_row("rev_hw", "Revenu lunettes", lambda i, c: f"={c}{prow['units']}*{ref('hw_price')}", CAD0, "sum")
proj_row("cogs_hw", "Coût des lunettes vendues (coût de revient + Stripe + retours)", lambda i, c: f"={c}{prow['units']}*({ref('hw_cost')}+{ref('hw_price')}*({ref('stripe_pct')}+{ref('returns')})+{ref('stripe_fix')})", CAD0, "sum")
proj_row("gp_hw", "Marge brute lunettes", lambda i, c: f"={c}{prow['rev_hw']}-{c}{prow['cogs_hw']}", CAD0, "sum", bold=True)

r += 1
PL = q(ws_plans)
pp = REF["plan_price_row"]
pa = REF["plan_api_row"]
plans_proj = [("ess", "ESSENTIEL", "C", "mix_ess"), ("pro", "PRO", "D", "mix_pro"), ("ultra", "ULTRA", "E", "mix_ultra")]
for key, name, pcol, mix in plans_proj:
    proj_row(f"new_{key}", f"Nouveaux abonnés {name}", lambda i, c, mix=mix: f"=ROUND({c}{prow['units']}*(1+{ref('sw_only')})*{ref('attach')}*{ref(mix)},0)", NUM, "sum")
    proj_row(f"sub_{key}", f"Abonnés {name} en fin de mois", lambda i, c, key=key: (f"={c}{prow['new_'+key]}" if i == 0 else f"=ROUND({mcols[i-1]}{prow['sub_'+key]}*(1-{ref('churn')}),0)+{c}{prow['new_'+key]}"), NUM, "last")
proj_row("sub_tot", "Total abonnés payants", lambda i, c: f"={c}{prow['sub_ess']}+{c}{prow['sub_pro']}+{c}{prow['sub_ultra']}", NUM, "last", bold=True)
proj_row("rev_sub", "Revenu abonnements", lambda i, c: f"={c}{prow['sub_ess']}*{PL}!$C${pp}+{c}{prow['sub_pro']}*{PL}!$D${pp}+{c}{prow['sub_ultra']}*{PL}!$E${pp}", CAD0, "sum")
proj_row("api", "Coût API (ElevenLabs, Gemini, OpenAI, Claude)", lambda i, c: f"={c}{prow['sub_ess']}*{PL}!$C${pa}+{c}{prow['sub_pro']}*{PL}!$D${pa}+{c}{prow['sub_ultra']}*{PL}!$E${pa}", CAD0, "sum")
proj_row("stripe_sub", "Frais Stripe abonnements", lambda i, c: f"={c}{prow['rev_sub']}*{ref('stripe_pct')}+{c}{prow['sub_tot']}*{ref('stripe_fix')}", CAD0, "sum")
proj_row("gp_sub", "Marge brute abonnements", lambda i, c: f"={c}{prow['rev_sub']}-{c}{prow['api']}-{c}{prow['stripe_sub']}", CAD0, "sum", bold=True)

r += 1
proj_row("rev", "REVENU TOTAL", lambda i, c: f"={c}{prow['rev_hw']}+{c}{prow['rev_sub']}", CAD0, "sum", bold=True, fill=GREY)
proj_row("gp", "MARGE BRUTE TOTALE", lambda i, c: f"={c}{prow['gp_hw']}+{c}{prow['gp_sub']}", CAD0, "sum", bold=True, fill=GREY)
proj_row("fixed", "Coûts fixes (Hypothèses §7) + salaire", lambda i, c: f"={ref('fixed_total')}+{ref('salary')}", CAD0, "sum")
proj_row("ebitda", "RÉSULTAT MENSUEL avant impôts", lambda i, c: f"={c}{prow['gp']}-{c}{prow['fixed']}", CAD0, "sum", bold=True, fill=GREY)
proj_row("cum", "Trésorerie cumulée (hors achat du stock initial)", lambda i, c: (f"={c}{prow['ebitda']}" if i == 0 else f"={mcols[i-1]}{prow['cum']}+{c}{prow['ebitda']}"), CAD0, "last", bold=True)

r += 2
section(ws, r, "Indicateurs")
r += 1
label(ws, f"A{r}", "Premier mois rentable (résultat mensuel ≥ 0)")
formula(ws, f"B{r}", f'=IFERROR(MATCH(TRUE,INDEX(B{prow["ebitda"]}:{mcols[-1]}{prow["ebitda"]}>=0,0),0),"> 12 mois")', NUM)
r += 1
label(ws, f"A{r}", "Ventes de lunettes par mois pour couvrir les coûts fixes (sans abonnement)")
formula(ws, f"B{r}", f"=IF({ref('hw_gp')}<=0,0,ROUNDUP(({ref('fixed_total')}+{ref('salary')})/{ref('hw_gp')},0))", NUM)
r += 1
label(ws, f"A{r}", "Abonnés PRO nécessaires pour couvrir les coûts fixes (sans lunettes)")
formula(ws, f"B{r}", f"=IF({PL}!$D${REF['plan_gp_row']}<=0,0,ROUNDUP(({ref('fixed_total')}+{ref('salary')})/{PL}!$D${REF['plan_gp_row']},0))", NUM)
r += 1
label(ws, f"A{r}", "Stock initial à financer (palier choisi, CAD)")
formula(ws, f"B{r}", f"=INDEX('Coût lunettes'!B{rows['capital']}:E{rows['capital']},MATCH({ref('tier_sel')},'Coût lunettes'!B{rows['qty']}:E{rows['qty']},0))", CAD0)
r += 1
label(ws, f"A{r}", "Revenu annuel récurrent (ARR) en fin de mois 12")
formula(ws, f"B{r}", f"={mcols[-1]}{prow['rev_sub']}*12", CAD0)
ws.freeze_panes = "B10"

# =====================================================================
# 0. LISEZ-MOI
# =====================================================================
ws = ws_readme
setw(ws, {"A": 120})
cell(ws, "A1", "VELA / IRIS — Plan financier : prix des lunettes et plans d'abonnement", TITLE)
lines = [
    "Version du 2 septembre 2026. Devise : dollars canadiens (CAD) sauf mention US$. Prix hors taxes (TPS/TVQ calculées à part).",
    "",
    "COMMENT LIRE LE CLASSEUR",
    "• Texte bleu = valeur à saisir. Fond jaune = levier clé qui change tout le modèle (taux de change, prix OEM, marge cible, prix des plans, ventes mensuelles).",
    "• Texte noir = formule. Texte vert = renvoi vers une autre feuille. Ne pas écraser les formules.",
    "• Feuille Hypothèses : toutes les entrées, avec source ou mention « hypothèse ». Feuille Coût lunettes : coût de revient par palier OEM et prix public recommandé.",
    "• Feuille Coût API par utilisateur : ce qu'un abonné coûte réellement en ElevenLabs, Gemini, OpenAI et Claude selon son usage.",
    "• Feuille Abonnements : plans GRATUIT / ESSENTIEL / PRO / ULTRA, marge par abonné, pire cas au quota, offres groupées.",
    "• Feuille Projection 12 mois : ventes, abonnés, résultat et trésorerie mois par mois, seuil de rentabilité.",
    "",
    "CE QUI EST VÉRIFIÉ (2 septembre 2026)",
    "• ElevenLabs : Free 10 000 crédits ; Starter 6 US$ / 30 000 ; Creator 22 US$ / 121 000 ; Pro 99 US$ / 600 000 ; Scale 299 US$ / 1,8 M ; Business 990 US$ / 6 M. Flash v2.5 = 0,5 crédit par caractère. (elevenlabs.io/pricing)",
    "• Gemini API : 2.5 Flash 0,30 / 2,50 US$ par M jetons ; 3.7 Flash 0,75 / 3,75 (double au 1er janvier 2027) ; 2.5 Pro 1,25 / 10. (ai.google.dev/gemini-api/docs/pricing)",
    "• OpenAI API : GPT-5 mini 0,25 / 2,00 ; GPT-5 1,25 / 10. (openai.com/api/pricing via pricepertoken.com, cloudzero.com)",
    "• Anthropic API : Haiku 4.5 1 / 5 ; Sonnet 5 2 / 10 ; Opus 5 5 / 25 ; Fable 5.1 10 / 50. (référence tarifaire Anthropic, cache du 24 juin 2026)",
    "• Abonnements grand public : ChatGPT Plus 20 US$, Claude Pro 20 US$ (Max 100/200), Google AI Pro 19,99 US$. Ils servent au développement, pas à revendre l'accès aux clients.",
    "• Concurrence : Meta Glasses 299 US$ (juin 2026), Ray-Ban Meta 379 US$, Ray-Ban Display 799 US$, Snap Specs 2 195 US$.",
    "",
    "CE QUI EST UNE HYPOTHÈSE À CONFIRMER",
    "• Prix OEM du K900 (145 → 95 US$ selon volume) : SmartXY n'affiche pas de prix ; envoyer la RFQ (Partie 10 du cahier des charges) et remplacer la ligne dans Hypothèses §2.",
    "• Frais non récurrents (15 000 US$), fret, douane (5 %), garantie (4 %), retours (3 %) : ordres de grandeur prudents.",
    "• Profils d'usage (requêtes/jour, jetons, caractères) : à recaler après 1 mois de données réelles d'IRIS (journal des conversations et compteur ElevenLabs).",
    "• Reconnaissance vocale cloud 0,016 US$/min : à vérifier ; par défaut IRIS utilise Vosk hors-ligne (gratuit).",
    "• Le modèle ne couvre ni l'impôt, ni l'inflation, ni la TVQ/TPS à remettre, ni le coût de l'application mobile (Phase 2).",
    "",
    "RECOMMANDATIONS CLÉS (voir les feuilles pour les chiffres calculés)",
    "1. Fixer le prix public des lunettes sur le palier 500 unités et viser 45 % de marge brute : cela place VELA entre les Meta Glasses (299 US$) et les Ray-Ban Meta (379 US$).",
    "2. Le plan PRO (29,99 CAD ≈ 22 US$) est le cœur de l'offre : au repère des 20 US$ des assistants IA, avec Claude Sonnet 5 et ElevenLabs. ESSENTIEL (19,99) couvre la voix ElevenLabs avec Gemini/GPT mini ; ULTRA (99,99) absorbe les gros consommateurs d'Opus 5.",
    "2b. La voix ElevenLabs est le premier coût variable (≈ 0,17 US$ par 1 000 crédits, soit ≈ 11–12 CAD/mois pour un usage moyen) — bien plus que le modèle de langage. Si la marge d'ESSENTIEL est trop faible, basculer ce plan sur une voix moins chère (ligne « Voix alternative » dans Hypothèses) ou réduire la longueur des réponses vocales.",
    "3. Souscrire ElevenLabs Creator au démarrage, passer à Scale dès ~40 abonnés payants (la feuille Coût API indique combien d'utilisateurs chaque plan couvre).",
    "4. Coder les quotas mensuels dans IRIS (ligne « Quota » de la feuille Abonnements) : c'est ce qui garantit une marge positive même au pire cas.",
    "5. Ne pas commander 500 unités avant validation du MVP sur échantillons (cahier des charges, Partie 10) ; le capital à immobiliser par palier est calculé dans Coût lunettes.",
]
for i, t in enumerate(lines, start=3):
    c = ws[f"A{i}"]
    c.value = t
    c.font = BOLD if t.isupper() or (t[:1].isdigit() and False) else BLACK
    c.alignment = Alignment(wrap_text=True, vertical="top")

for w in wb.worksheets:
    for row in w.iter_rows():
        for c in row:
            if c.font is None or c.font.name != FONT:
                f = c.font
                c.font = Font(name=FONT, bold=f.bold, size=f.size or 10, color=f.color)

wb.save(OUT)
print("saved", OUT)
