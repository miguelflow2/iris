import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Field, Holo, Liste, Modal, Rangee, TopBar, Vide } from '../components/ui'
import { IcoCamera, IcoImage, IcoPlus, IcoPoubelle, IcoTelecharger } from '../components/icons'
import { CarteLunettesRequises } from '../components/LunettesRequises'
import { ApiError, api, messageErreur, type IrisEvent } from '../lib/api'
import { useStore } from '../lib/store'
import { BlocRefus, dateLisible, dureeLisible, dureeMesuree, IcoDegrade, lireRefus, pluriel, useTic, type Refus } from './CoursScreen'
import './AccessibiliteScreen.css'
import './CoursScreen.css'

/* =========================================================================
   « Reçus » : photographier un reçu, vérifier ce qu'IRIS en a lu, le corriger,
   retrouver ses dépenses par mois avec les taxes, exporter pour le tableur.

   Ce que fait le service (backend/iris/recus.py), dit à l'écran :
   - lecture du texte sur l'ordinateur d'abord ; le moteur VELA ne reçoit
     l'image qu'avec l'accord « Images jointes » ;
   - un champ illisible reste VIDE (jamais une valeur « probable ») ; la
     confiance ne dépasse jamais 95 % ; l'addition et les taux sont vérifiés
     quand c'est possible, sinon c'est dit ;
   - données et image chiffrées ; rien n'est enregistré en mémoire suspendue.

   Lunettes d'abord : ANALYSER un reçu exige les lunettes. Consulter,
   corriger, exporter et supprimer ses reçus reste toujours permis (Loi 25).
   ========================================================================= */

export const CATEGORIES_RECU = [
  'Alimentation',
  'Restaurant',
  'Transport',
  'Essence',
  'Fournitures de bureau',
  'Logiciels et abonnements',
  'Matériel',
  'Télécommunications',
  'Formation',
  'Santé',
  'Loisirs',
  'Autre'
]

interface LigneRecu {
  libelle: string
  montant: number | null
}

export interface Recu {
  id: string | null
  date: string | null
  commercant: string | null
  sous_total: number | null
  tps: number | null
  tvq: number | null
  tvh: number | null
  total: number | null
  devise: string
  categorie: string | null
  moyen_paiement: string | null
  lignes: LigneRecu[]
  confiance: number
  image_nom: string | null
  local: boolean
  cree_le: string
  corrige?: boolean
  controle?: { somme_ok?: boolean | null; taux_ok?: boolean | null; corrige_le?: string } | null
  note?: string | null
  enregistre?: boolean
  duree_ms?: number
}

interface Totaux {
  nombre: number
  devise: string
  sous_total: number
  tps: number
  tvq: number
  tvh: number
  total: number
  par_categorie: Record<string, number>
  autres_devises: Record<string, number>
  sans_total: number
}

type ChampMontant = 'sous_total' | 'tps' | 'tvq' | 'tvh' | 'total'
// Marque d'ordre des octets (U+FEFF) : Excel en a besoin pour lire les accents d'un CSV.
const BOM = String.fromCharCode(0xfeff)

const MONTANTS: { cle: ChampMontant; libelle: string }[] = [
  { cle: 'sous_total', libelle: 'Sous-total' },
  { cle: 'tps', libelle: 'TPS' },
  { cle: 'tvq', libelle: 'TVQ' },
  { cle: 'tvh', libelle: 'TVH' },
  { cle: 'total', libelle: 'Total' }
]

/** « 12,34 $ » ; un tiret pour un montant absent (jamais 0 à la place d'un champ illisible). */
export function formatMontant(valeur: number | null | undefined, devise = 'CAD'): string {
  if (valeur === null || valeur === undefined || !Number.isFinite(Number(valeur))) return '—'
  try {
    return new Intl.NumberFormat('fr-CA', { style: 'currency', currency: devise || 'CAD' }).format(Number(valeur))
  } catch {
    return `${Number(valeur).toFixed(2).replace('.', ',')} ${devise}`
  }
}

function versChamp(n: number | null | undefined): string {
  return n === null || n === undefined || !Number.isFinite(Number(n)) ? '' : Number(n).toFixed(2).replace('.', ',')
}

function moisDe(r: Recu): string {
  return (r.date || (r.cree_le || '').slice(0, 10) || '').slice(0, 7)
}

function libelleMois(cle: string): string {
  const [a, m] = cle.split('-').map(Number)
  if (!a || !m) return 'Date inconnue'
  const texte = new Date(a, m - 1, 1).toLocaleDateString('fr-CA', { month: 'long', year: 'numeric' })
  return texte.charAt(0).toUpperCase() + texte.slice(1)
}

/** Confiance de lecture, jamais présentée comme une certitude. */
function Confiance({ valeur }: { valeur: number }): JSX.Element {
  const pct = Math.round(Math.min(1, Math.max(0, Number(valeur) || 0)) * 100)
  const niveau = pct >= 80 ? 'haute' : pct >= 50 ? 'moyenne' : 'basse'
  return (
    <div className="col" style={{ gap: 4 }}>
      <div className={`q-confiance ${niveau}`}>
        <span>Confiance de lecture : {pct} %</span>
        <span className="barre" aria-hidden="true"><div style={{ width: `${pct}%` }} /></span>
      </div>
      <div className="q-note">
        {niveau === 'basse'
          ? 'Lecture incertaine : vérifiez et corrigez chaque champ avant de vous en servir.'
          : 'Vérifiez chaque montant avant de vous en servir : aucune lecture de reçu n’est certaine.'}
      </div>
    </div>
  )
}

function Controles({ recu }: { recu: Recu }): JSX.Element {
  const somme = recu.controle?.somme_ok
  const taux = recu.controle?.taux_ok
  return (
    <ul className="q-controles">
      <li className={somme === true ? 'ok' : somme === false ? 'ko' : ''}>
        {somme === true
          ? 'Sous-total + taxes = total : vérifié.'
          : somme === false
            ? 'Sous-total + taxes ne donnent pas le total : un montant est probablement mal lu.'
            : 'Addition non vérifiable : un montant manque.'}
      </li>
      <li className={taux === true ? 'ok' : taux === false ? 'ko' : ''}>
        {taux === true
          ? 'Taxes conformes aux taux connus (TPS 5 %, TVQ 9,975 %, TVH 13 à 15 %).'
          : taux === false
            ? 'Taxes différentes des taux connus : vérifiez-les.'
            : 'Taux non vérifiables (articles détaxés possibles, ou montants manquants).'}
      </li>
    </ul>
  )
}

interface Formulaire {
  date: string
  commercant: string
  categorie: string
  moyen_paiement: string
  devise: string
  sous_total: string
  tps: string
  tvq: string
  tvh: string
  total: string
  lignes: { libelle: string; montant: string }[]
}

function formulaireDe(r: Recu): Formulaire {
  return {
    date: r.date || '',
    commercant: r.commercant || '',
    categorie: r.categorie || 'Autre',
    moyen_paiement: r.moyen_paiement || '',
    devise: r.devise || 'CAD',
    sous_total: versChamp(r.sous_total),
    tps: versChamp(r.tps),
    tvq: versChamp(r.tvq),
    tvh: versChamp(r.tvh),
    total: versChamp(r.total),
    lignes: (r.lignes || []).map((l) => ({ libelle: l.libelle || '', montant: versChamp(l.montant) }))
  }
}

/** Carte éditable d'un reçu : image, confiance, contrôles, tous les champs, enregistrer, supprimer. */
function EditeurRecu({ recu, onChange, onSupprime }: { recu: Recu; onChange: (r: Recu) => void; onSupprime: () => void }): JSX.Element {
  const { toast } = useStore()
  const [f, setF] = useState<Formulaire>(() => formulaireDe(recu))
  const [erreur, setErreur] = useState('')
  const [occupe, setOccupe] = useState(false)
  const [image, setImage] = useState<string | null>(null)
  const [imageErreur, setImageErreur] = useState('')

  useEffect(() => {
    setF(formulaireDe(recu))
    setErreur('')
  }, [recu])

  // L'image est déchiffrée par le service et servie avec le jeton : jamais d'URL nue.
  useEffect(() => {
    setImage(null)
    setImageErreur('')
    if (!recu.id || !recu.image_nom) return
    let courant = true
    let url: string | null = null
    api
      .blob(`/api/recus/${encodeURIComponent(recu.id)}/image`)
      .then((b) => {
        url = URL.createObjectURL(b)
        if (courant) setImage(url)
        else URL.revokeObjectURL(url)
      })
      .catch((err) => {
        if (courant) setImageErreur(messageErreur(err))
      })
    return () => {
      courant = false
      if (url) URL.revokeObjectURL(url)
    }
  }, [recu.id, recu.image_nom])

  const initial = useMemo(() => formulaireDe(recu), [recu])
  const modifiable = Boolean(recu.id) && recu.enregistre !== false

  const patch = useMemo(() => {
    const p: Record<string, unknown> = {}
    for (const cle of ['date', 'commercant', 'categorie', 'moyen_paiement', 'devise'] as const) {
      if (f[cle].trim() !== initial[cle].trim()) p[cle] = f[cle].trim()
    }
    for (const { cle } of MONTANTS) {
      if (f[cle].trim() !== initial[cle].trim()) p[cle] = f[cle].trim()
    }
    const lignes = f.lignes.filter((l) => l.libelle.trim() || l.montant.trim()).map((l) => ({ libelle: l.libelle.trim(), montant: l.montant.trim() }))
    const avant = initial.lignes.map((l) => ({ libelle: l.libelle.trim(), montant: l.montant.trim() }))
    if (JSON.stringify(lignes) !== JSON.stringify(avant)) p.lignes = lignes.map((l) => ({ libelle: l.libelle, montant: l.montant || null }))
    return p
  }, [f, initial])
  const aModifier = Object.keys(patch).length > 0

  const enregistrer = async (): Promise<void> => {
    if (!recu.id || !aModifier || occupe) return
    setOccupe(true)
    setErreur('')
    try {
      const r: Recu = await api.patch(`/api/recus/${encodeURIComponent(recu.id)}`, patch)
      onChange(r)
      toast('Corrections enregistrées.', 'success')
    } catch (err) {
      setErreur(messageErreur(err))
    } finally {
      setOccupe(false)
    }
  }

  const supprimer = async (): Promise<void> => {
    if (!recu.id || occupe) return
    if (!window.confirm('Supprimer ce reçu et sa photo de cet ordinateur ? Cette action est définitive.')) return
    setOccupe(true)
    try {
      await api.delete(`/api/recus/${encodeURIComponent(recu.id)}`)
      toast('Reçu supprimé.', 'success')
      onSupprime()
    } catch (err) {
      setErreur(messageErreur(err))
      setOccupe(false)
    }
  }

  const champ = (cle: keyof Omit<Formulaire, 'lignes'>, valeur: string): void => setF((x) => ({ ...x, [cle]: valeur }))

  return (
    <div className="col" style={{ gap: 14 }}>
      {image ? <img className="q-recu-image" src={image} alt="Photo du reçu" /> : null}
      {imageErreur ? <div className="q-note">Photo du reçu indisponible : {imageErreur}</div> : null}

      <Confiance valeur={recu.confiance} />
      <Controles recu={recu} />
      <div className="q-meta">
        <span className={`etiquette-locale ${recu.local ? 'local' : 'moteur'}`}>{recu.local ? 'Lu sur cet ordinateur' : 'Lu par le moteur VELA'}</span>
        {recu.corrige ? <span className="pill">Corrigé à la main</span> : null}
        {typeof recu.duree_ms === 'number' ? <span>Analyse : {dureeMesuree(recu.duree_ms)}</span> : null}
        {recu.cree_le ? <span>Enregistré le {dateLisible(recu.cree_le)}</span> : null}
      </div>
      {recu.note ? <div className="bloc-note attention">{recu.note}</div> : null}
      {recu.enregistre === false ? (
        <div className="bloc-note attention">Ce reçu a été lu mais n’a pas été enregistré : il disparaîtra en quittant cet écran.</div>
      ) : null}

      <div className="q-grille-2">
        <Field label="Date d’achat">
          <input className="input" type="date" value={f.date} disabled={!modifiable} onChange={(e) => champ('date', e.target.value)} />
        </Field>
        <Field label="Commerçant">
          <input className="input" value={f.commercant} maxLength={120} disabled={!modifiable} onChange={(e) => champ('commercant', e.target.value)} />
        </Field>
        <Field label="Catégorie" hint="Une suggestion d’IRIS : corrigez-la au besoin.">
          <select className="select" value={f.categorie} disabled={!modifiable} onChange={(e) => champ('categorie', e.target.value)}>
            {CATEGORIES_RECU.map((c) => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>
        </Field>
        <Field label="Moyen de paiement">
          <input className="input" value={f.moyen_paiement} maxLength={40} placeholder="Ex. : Débit, Visa" disabled={!modifiable} onChange={(e) => champ('moyen_paiement', e.target.value)} />
        </Field>
        <Field label="Devise" hint="Code à 3 lettres (CAD, USD…).">
          <input className="input" value={f.devise} maxLength={3} disabled={!modifiable} onChange={(e) => champ('devise', e.target.value.toUpperCase())} />
        </Field>
      </div>

      <div className="q-grille-2">
        {MONTANTS.map(({ cle, libelle }) => (
          <Field key={cle} label={libelle}>
            <input
              className="input"
              inputMode="decimal"
              value={f[cle]}
              placeholder="illisible"
              disabled={!modifiable}
              onChange={(e) => champ(cle, e.target.value)}
            />
          </Field>
        ))}
      </div>
      <div className="q-note">Un champ vide est un montant qu’IRIS n’a pas pu lire : il n’est jamais remplacé par une valeur devinée.</div>

      <div className="col" style={{ gap: 8 }}>
        <div style={{ fontWeight: 700 }}>Articles ({f.lignes.length})</div>
        <div className="q-lignes-recu">
          {f.lignes.map((l, i) => (
            <div key={i} className="q-ligne-recu">
              <input
                className="input"
                aria-label={`Article ${i + 1}`}
                value={l.libelle}
                maxLength={120}
                disabled={!modifiable}
                onChange={(e) => setF((x) => ({ ...x, lignes: x.lignes.map((y, j) => (j === i ? { ...y, libelle: e.target.value } : y)) }))}
              />
              <input
                className="input"
                aria-label={`Montant de l’article ${i + 1}`}
                inputMode="decimal"
                value={l.montant}
                disabled={!modifiable}
                onChange={(e) => setF((x) => ({ ...x, lignes: x.lignes.map((y, j) => (j === i ? { ...y, montant: e.target.value } : y)) }))}
              />
              <button
                type="button"
                className="btn icon"
                aria-label={`Retirer l’article ${i + 1}`}
                disabled={!modifiable}
                onClick={() => setF((x) => ({ ...x, lignes: x.lignes.filter((_y, j) => j !== i) }))}
              >
                <IcoPoubelle width={18} height={18} />
              </button>
            </div>
          ))}
        </div>
        {modifiable ? (
          <Holo taille="mini" variante="sombre" style={{ alignSelf: 'flex-start' }} onClick={() => setF((x) => ({ ...x, lignes: [...x.lignes, { libelle: '', montant: '' }] }))}>
            <IcoPlus /> Ajouter un article
          </Holo>
        ) : null}
      </div>

      {erreur ? <div className="bloc-note erreur" role="alert">{erreur}</div> : null}
      {modifiable ? (
        <div className="q-actions">
          <Holo taille="petit" disabled={!aModifier || occupe} onClick={enregistrer}>{occupe ? 'Enregistrement…' : 'Enregistrer les corrections'}</Holo>
          {aModifier ? (
            <Holo taille="petit" variante="sombre" disabled={occupe} onClick={() => setF(initial)}>Annuler</Holo>
          ) : null}
          <Holo taille="petit" variante="contour" disabled={occupe} onClick={supprimer}><IcoPoubelle /> Supprimer</Holo>
        </div>
      ) : null}
    </div>
  )
}

type Sommes = { devise: string } & Record<ChampMontant, number>

/** Champs présents sur au moins un reçu de la devise : un total sans aucune valeur lue s'affiche « — », jamais « 0,00 $ ». */
function champsPresents(recus: Recu[], devise: string): Record<ChampMontant, boolean> {
  const presents = { sous_total: false, tps: false, tvq: false, tvh: false, total: false }
  for (const r of recus) {
    if ((r.devise || 'CAD') !== devise) continue
    for (const { cle } of MONTANTS) if (r[cle] !== null && r[cle] !== undefined) presents[cle] = true
  }
  return presents
}

function GrilleTotaux({ t, presents, titre }: { t: Sommes; presents: Record<ChampMontant, boolean>; titre?: string }): JSX.Element {
  const valeur = (c: ChampMontant): string => (presents[c] ? formatMontant(t[c], t.devise) : '—')
  return (
    <div className="q-totaux" role="group" aria-label={titre}>
      {[...MONTANTS.filter((m) => m.cle === 'total'), ...MONTANTS.filter((m) => m.cle !== 'total')].map(({ cle, libelle }) => (
        <div key={cle} className={`q-total ${cle === 'total' ? 'principal' : ''}`}>
          <div className="libelle">{libelle}</div>
          <div className="valeur">{valeur(cle)}</div>
        </div>
      ))}
    </div>
  )
}

export function RecusScreen({ params: _params }: { params?: Record<string, any> }): JSX.Element {
  const { toast, presence, exigerLunettes, invite, zone } = useStore()
  const [recus, setRecus] = useState<Recu[] | null>(null)
  const [totaux, setTotaux] = useState<Totaux | null>(null)
  const [limite, setLimite] = useState('')
  const [retention, setRetention] = useState(0)
  const [erreurListe, setErreurListe] = useState('')
  const [debut, setDebut] = useState('')
  const [fin, setFin] = useState('')
  const [analyse, setAnalyse] = useState<{ source: 'lunettes' | 'image'; depuis: number } | null>(null)
  const [refus, setRefus] = useState<(Refus & { source: 'lunettes' | 'image'; camera: boolean }) | null>(null)
  const [dernier, setDernier] = useState<Recu | null>(null)
  const [selection, setSelection] = useState<Recu | null>(null)
  const vivant = useRef(true)
  const tic = useTic(Boolean(analyse))

  const absentes = presence !== null && !presence.presentes

  const charger = useCallback(async () => {
    const p = new URLSearchParams()
    if (debut) p.set('debut', debut)
    if (fin) p.set('fin', fin)
    try {
      const r = await api.get(`/api/recus${p.toString() ? `?${p.toString()}` : ''}`)
      if (!vivant.current) return
      setRecus(Array.isArray(r?.recus) ? r.recus : [])
      setTotaux(r?.totaux || null)
      setLimite(typeof r?.limite === 'string' ? r.limite : '')
      setRetention(Number(r?.retention_jours) || 0)
      setErreurListe('')
    } catch (err) {
      if (vivant.current) setErreurListe(messageErreur(err))
    }
  }, [debut, fin])

  useEffect(() => {
    vivant.current = true
    return () => {
      vivant.current = false
    }
  }, [])

  useEffect(() => {
    charger()
    // « Garde ce reçu » dit à la voix, ou un reçu analysé depuis le téléphone : la liste suit.
    return api.on((e: IrisEvent) => {
      if (e.type === 'recu.nouveau') charger()
    })
  }, [charger])

  const analyser = async (source: 'lunettes' | 'image'): Promise<void> => {
    if (analyse) return
    if (!exigerLunettes('Reçus')) return
    let image: { media_type: string; data: string } | null = null
    if (source === 'image') {
      try {
        const img = await window.iris.pickImage()
        if (!img) return
        image = { media_type: img.media_type, data: img.data }
      } catch (err) {
        toast(messageErreur(err), 'error')
        return
      }
    }
    setAnalyse({ source, depuis: Date.now() })
    setRefus(null)
    setDernier(null)
    try {
      const r: Recu = await api.post('/api/recus/analyser', { source, image })
      if (!vivant.current) return
      setDernier(r)
      if (r.enregistre !== false) charger()
    } catch (err) {
      if (!vivant.current) return
      const x = lireRefus(err)
      if (x) setRefus({ ...x, source, camera: source === 'lunettes' && err instanceof ApiError && err.status === 409 })
    } finally {
      if (vivant.current) setAnalyse(null)
    }
  }

  const exporter = async (): Promise<void> => {
    const p = new URLSearchParams({ format: 'csv' })
    if (debut) p.set('debut', debut)
    if (fin) p.set('fin', fin)
    try {
      const b = await api.blob(`/api/recus/export?${p.toString()}`)
      let texte = await b.text()
      // Le service ajoute une marque d'ordre des octets pour qu'Excel lise les accents ; la lecture du blob l'enlève.
      if (!texte.startsWith(BOM)) texte = BOM + texte
      const nom = `iris-recus${debut ? `-${debut}` : ''}${fin ? `-${fin}` : ''}.csv`
      const chemin = await window.iris.saveFile(nom, texte)
      if (chemin) toast('Reçus exportés en CSV.', 'success')
    } catch (err) {
      toast(messageErreur(err), 'error')
    }
  }

  const mois = useMemo(() => {
    const groupes = new Map<string, Recu[]>()
    for (const r of recus || []) {
      const cle = moisDe(r)
      groupes.set(cle, [...(groupes.get(cle) || []), r])
    }
    const devise = totaux?.devise || 'CAD'
    return Array.from(groupes.entries())
      .sort(([a], [b]) => b.localeCompare(a))
      .map(([cle, liste]) => {
        const somme: Sommes = { devise, sous_total: 0, tps: 0, tvq: 0, tvh: 0, total: 0 }
        let autres = 0
        for (const r of liste) {
          if ((r.devise || 'CAD') !== devise) {
            autres += 1
            continue
          }
          for (const { cle: c } of MONTANTS) somme[c] += Number(r[c]) || 0
        }
        for (const { cle: c } of MONTANTS) somme[c] = Math.round(somme[c] * 100) / 100
        return { cle, liste, somme, autres, presents: champsPresents(liste, devise) }
      })
  }, [recus, totaux?.devise])

  const secondesAnalyse = analyse ? Math.max(0, Math.round((tic - analyse.depuis) / 1000)) : 0

  return (
    <div className="ecran">
      <TopBar titre="Reçus" />
      <div className="contenu">
        {absentes ? <CarteLunettesRequises fonction="Photographier un reçu" /> : null}
        {invite?.actif || zone?.dans_zone ? (
          <div className="bloc-note attention">
            Mémoire suspendue ({invite?.actif ? 'mode invité' : `zone sans mémoire${zone?.zone_nom ? ` : ${zone.zone_nom}` : ''}`}) : un reçu analysé
            maintenant sera lu, mais ni enregistré ni corrigeable.
          </div>
        ) : null}

        {/* ------------------------------------------------------------ photographier */}
        <div className="carte col" style={{ gap: 12 }}>
          <h3 style={{ margin: 0 }}>Photographier un reçu</h3>
          <div className="q-grille-2">
            <Holo disabled={Boolean(analyse)} onClick={() => analyser('image')}>
              <IcoImage /> {analyse?.source === 'image' ? 'Lecture…' : 'Choisir une image'}
            </Holo>
            <Holo variante="sombre" disabled={Boolean(analyse)} onClick={() => analyser('lunettes')}>
              <IcoCamera /> {analyse?.source === 'lunettes' ? 'Photo en cours…' : 'Photo des lunettes'}
            </Holo>
          </div>
          <div className="q-note">
            La caméra des lunettes n’est pas encore activée dans IRIS (protocole en cours de confirmation) : en attendant, prenez la photo
            avec votre téléphone et choisissez-la ici. Posez le reçu à plat, bien éclairé.
          </div>
          {analyse ? (
            <div className="col" style={{ gap: 6 }} aria-live="polite">
              <div style={{ fontWeight: 700 }}>Lecture du reçu… <span className="muted">{dureeLisible(secondesAnalyse)}</span></div>
              <div className="progress indet"><div /></div>
            </div>
          ) : null}
          {refus ? (
            <>
              <BlocRefus refus={refus} onFermer={() => setRefus(null)} onReessayer={() => analyser(refus.source)} />
              {refus.camera ? <div className="q-note">En attendant, choisissez « Choisir une image » avec une photo prise par votre téléphone.</div> : null}
            </>
          ) : null}
        </div>

        {dernier ? (
          <div className="carte col" style={{ gap: 12 }} aria-live="polite">
            <div className="row between" style={{ gap: 10 }}>
              <h3 style={{ margin: 0 }}>{dernier.commercant || 'Reçu analysé'}</h3>
              <strong style={{ fontSize: 22 }}>{formatMontant(dernier.total, dernier.devise)}</strong>
            </div>
            <EditeurRecu
              recu={dernier}
              onChange={(r) => {
                setDernier(r)
                charger()
              }}
              onSupprime={() => {
                setDernier(null)
                charger()
              }}
            />
          </div>
        ) : null}

        {/* ------------------------------------------------------------ mes reçus */}
        <h2 className="section-sous">Mes reçus</h2>
        <div className="carte col" style={{ gap: 12 }}>
          <div className="plage-dates">
            <Field label="Du">
              <input className="input" type="date" value={debut} max={fin || undefined} onChange={(e) => setDebut(e.target.value)} />
            </Field>
            <Field label="Au">
              <input className="input" type="date" value={fin} min={debut || undefined} onChange={(e) => setFin(e.target.value)} />
            </Field>
          </div>
          {totaux ? (
            <>
              <div style={{ fontWeight: 700 }}>
                {pluriel(totaux.nombre, 'reçu')} en {totaux.devise}
                {debut || fin ? ' sur la période' : ''}
              </div>
              <GrilleTotaux t={totaux} presents={champsPresents(recus || [], totaux.devise)} titre="Totaux de la période" />
              {totaux.sans_total ? <div className="q-note">{pluriel(totaux.sans_total, 'reçu')} sans total lisible : non compté dans le total.</div> : null}
              {Object.keys(totaux.autres_devises || {}).length ? (
                <div className="q-note">
                  Autres devises, jamais converties :{' '}
                  {Object.entries(totaux.autres_devises).map(([d, v]) => formatMontant(v, d)).join(' ; ')}
                </div>
              ) : null}
            </>
          ) : null}
          <div className="q-actions">
            <Holo taille="petit" variante="sombre" disabled={!recus?.length} onClick={exporter}><IcoTelecharger /> Exporter en CSV</Holo>
            {debut || fin ? (
              <Holo
                taille="petit"
                variante="contour"
                onClick={() => {
                  setDebut('')
                  setFin('')
                }}
              >
                Toutes les dates
              </Holo>
            ) : null}
          </div>
          <div className="q-note">Le CSV s’ouvre dans un tableur (date, commerçant, catégorie, sous-total, TPS, TVQ, TVH, total, devise, moyen de paiement).</div>
        </div>

        {erreurListe ? <div className="bloc-note erreur" role="alert">{erreurListe}</div> : null}
        {recus === null && !erreurListe ? <div className="empty">Chargement…</div> : null}
        {recus !== null && recus.length === 0 ? (
          <Vide
            icone={<IcoDegrade glyphe="recu" />}
            texte={debut || fin ? 'Aucun reçu sur cette période' : 'Aucun reçu pour l’instant'}
            petit="Photographiez un reçu : IRIS en lit les montants et les taxes, et vous les vérifiez."
          />
        ) : null}

        {mois.map(({ cle, liste, somme, autres, presents }) => (
          <section key={cle} className="q-mois" aria-label={libelleMois(cle)}>
            <h3 className="q-titre-groupe">{libelleMois(cle)} · {pluriel(liste.length, 'reçu')}</h3>
            <GrilleTotaux t={somme} presents={presents} titre={`Totaux de ${libelleMois(cle)}`} />
            {autres ? <div className="q-note">{pluriel(autres, 'reçu')} dans une autre devise, hors de ces totaux.</div> : null}
            <Liste>
              {liste.map((r, i) => (
                <Rangee
                  key={r.id || `${cle}-${i}`}
                  compacte
                  titre={r.commercant || 'Commerçant illisible'}
                  sous={
                    <>
                      {r.date ? dateLisible(r.date + 'T12:00:00', false) : `Enregistré le ${dateLisible(r.cree_le, false)}`} · {r.categorie || 'Autre'} · confiance{' '}
                      {Math.round((Number(r.confiance) || 0) * 100)} %
                      {r.corrige ? <span className="q-pastilles"><span className="pill">Corrigé</span></span> : null}
                    </>
                  }
                  valeur={formatMontant(r.total, r.devise)}
                  onClick={() => setSelection(r)}
                />
              ))}
            </Liste>
          </section>
        ))}

        {/* ------------------------------------------------------------ limites */}
        <div className="carte">
          <h3>Ce qu’il faut savoir</h3>
          <ul className="liste-limites">
            {limite ? <li>{limite}</li> : null}
            <li>Le texte du reçu est lu sur cet ordinateur. L’image n’est envoyée au moteur VELA que si « Images jointes » est autorisé ; sinon une lecture à règles, faite sur l’ordinateur, prend le relais, et la carte le dit.</li>
            <li>Les taux vérifiés sont la TPS (5 %), la TVQ (9,975 %) et la TVH (13 %, 14 % ou 15 %). Une date comme 03/04/2026 est ambiguë : elle est lue jour/mois, vérifiez-la.</li>
            <li>Les reçus et leurs photos sont chiffrés sur cet ordinateur. {recus !== null ? `Conservation : ${retention ? `${retention} jours` : 'sans limite de durée'} (réglée dans Confidentialité).` : ''}</li>
            <li>En mode invité ou dans une zone sans mémoire, un reçu peut être lu mais n’est pas enregistré.</li>
          </ul>
        </div>
      </div>

      {selection ? (
        <Modal title={selection.commercant || 'Reçu'} onClose={() => setSelection(null)}>
          <EditeurRecu
            recu={selection}
            onChange={(r) => {
              setSelection(r)
              charger()
            }}
            onSupprime={() => {
              setSelection(null)
              charger()
            }}
          />
        </Modal>
      ) : null}
    </div>
  )
}
