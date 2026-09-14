import React, { useEffect, useRef, useState } from 'react'
import { CarteReglage, Holo, Markdown, TopBar } from '../components/ui'
import { IcoLecture, IcoStop, IcoTelecharger } from '../components/icons'
import { CarteLunettesRequises } from '../components/LunettesRequises'
import { api, estLunettesRequises, messageErreur, refusConsentement, type IrisEvent } from '../lib/api'
import { useStore } from '../lib/store'
import { CarteConsentement } from './AccessibiliteScreen'
import './AccessibiliteScreen.css'

/* =========================================================================
   « Sous-titres en direct » : ce qui se dit autour, en très grand texte.

   La reconnaissance tourne sur l'ordinateur (modèle hors ligne) à partir du
   micro qu'IRIS écoute : rien ne quitte l'appareil pour afficher les
   sous-titres. Les phrases finales s'affichent en blanc, la phrase en cours en
   gris. Le résumé (procès-verbal) est la seule action qui envoie la
   transcription au moteur, et seulement avec l'accord « transcription ».
   ========================================================================= */

interface Ligne {
  ts: number
  texte: string
}

const CLE_TAILLE = 'iris.sous_titres.taille'
const TAILLE_MIN = 20
const TAILLE_MAX = 72

function lireTaille(): number {
  try {
    const v = Number(window.localStorage.getItem(CLE_TAILLE))
    return v >= TAILLE_MIN && v <= TAILLE_MAX ? v : 36
  } catch {
    return 36
  }
}

function heure(ts: number): string {
  const d = new Date(ts * 1000)
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleTimeString('fr-CA', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

export function SousTitresScreen({ params: _params }: { params?: Record<string, any> }): JSX.Element {
  const { nav, settings, updateSettings, toast, presence, exigerLunettes, ecoute, rafraichirEcoute, setConsent } = useStore()
  const [lignes, setLignes] = useState<Ligne[]>([])
  const [partiel, setPartiel] = useState('')
  const [taille, setTaille] = useState<number>(lireTaille)
  const [occupe, setOccupe] = useState(false)
  const [erreur, setErreur] = useState('')
  const [resume, setResume] = useState<{ texte: string; local: boolean } | null>(null)
  const [resumeEnCours, setResumeEnCours] = useState(false)
  const [refusResume, setRefusResume] = useState<{ data_type: string; label: string; message: string } | null>(null)
  const zone = useRef<HTMLDivElement>(null)
  const suivreBas = useRef(true)

  const absentes = presence !== null && !presence.presentes
  const actif = Boolean(ecoute?.sous_titres)

  useEffect(() => {
    rafraichirEcoute().catch(() => undefined)
    api
      .get('/api/ecoute/transcription')
      .then((r) => setLignes(Array.isArray(r?.lignes) ? r.lignes : []))
      .catch(() => undefined)
    return api.on((e: IrisEvent) => {
      if (e.type !== 'ecoute.sous_titre') return
      if (typeof e.final === 'string' && e.final) {
        setLignes((l) => [...l, { ts: Number(e.ts) || Date.now() / 1000, texte: e.final }].slice(-2000))
        setPartiel('')
      } else if (typeof e.partiel === 'string') {
        setPartiel(e.partiel)
      }
    })
  }, [rafraichirEcoute])

  // Défilement vers le bas à chaque phrase, sauf si l'utilisateur est remonté lire plus haut.
  useEffect(() => {
    const el = zone.current
    if (el && suivreBas.current) el.scrollTop = el.scrollHeight
  }, [lignes, partiel, taille])

  const changerTaille = (v: number): void => {
    setTaille(v)
    try {
      window.localStorage.setItem(CLE_TAILLE, String(v))
    } catch {
      /* préférence non conservée */
    }
  }

  const demarrer = async (): Promise<void> => {
    if (!exigerLunettes('Sous-titres en direct')) return
    setOccupe(true)
    setErreur('')
    try {
      await api.post('/api/ecoute/sous-titres/demarrer')
      await rafraichirEcoute()
    } catch (err) {
      if (!estLunettesRequises(err)) setErreur(messageErreur(err))
    } finally {
      setOccupe(false)
    }
  }

  const arreter = async (): Promise<void> => {
    setOccupe(true)
    setErreur('')
    try {
      const r = await api.post('/api/ecoute/sous-titres/arreter')
      if (Array.isArray(r?.lignes)) setLignes(r.lignes)
      setPartiel('')
      await rafraichirEcoute()
    } catch (err) {
      setErreur(messageErreur(err))
    } finally {
      setOccupe(false)
    }
  }

  const basculerJournal = (v: boolean): void => {
    if (v && !exigerLunettes('Journal continu')) return
    updateSettings({ journal_continu: v }).catch((err: unknown) => toast(messageErreur(err), 'error'))
  }

  const exporter = async (): Promise<void> => {
    if (!lignes.length) {
      toast('Aucune phrase à exporter pour le moment.', 'info')
      return
    }
    const jour = new Date().toISOString().slice(0, 10)
    const contenu = lignes.map((l) => `${heure(l.ts)}  ${l.texte}`).join('\n') + '\n'
    try {
      const chemin = await window.iris.saveFile(`sous-titres-${jour}.txt`, contenu)
      if (chemin) toast('Transcription enregistrée.', 'success')
    } catch (err) {
      toast(messageErreur(err), 'error')
    }
  }

  const resumer = async (): Promise<void> => {
    if (!lignes.length) {
      toast('Aucune transcription à résumer.', 'info')
      return
    }
    if (!exigerLunettes('Résumer la conversation')) return
    setResumeEnCours(true)
    setRefusResume(null)
    try {
      const r = await api.post('/api/ecoute/resume', { lignes })
      setResume({ texte: String(r?.resume || ''), local: Boolean(r?.local) })
    } catch (err) {
      if (estLunettesRequises(err)) return
      const c = refusConsentement(err)
      if (c) setRefusResume(c)
      else toast(messageErreur(err), 'error')
    } finally {
      setResumeEnCours(false)
    }
  }

  const raison = ecoute?.raison || null
  const suspendue = ecoute?.memoire_suspendue || null

  return (
    <div className="ecran">
      <TopBar titre="Sous-titres en direct" />
      <div className="contenu">
        {absentes ? <CarteLunettesRequises /> : null}

        <div className="row wrap" style={{ gap: 10 }}>
          {actif ? (
            <Holo taille="petit" variante="rouge" disabled={occupe} onClick={arreter}><IcoStop /> Arrêter</Holo>
          ) : (
            <Holo taille="petit" disabled={occupe} onClick={demarrer}><IcoLecture /> Démarrer</Holo>
          )}
          <span className="pill" aria-live="polite">{actif ? 'Sous-titres actifs' : 'Arrêtés'}</span>
        </div>

        {erreur ? <div className="bloc-note erreur" role="alert">{erreur}</div> : null}
        {raison && raison !== erreur ? <div className="bloc-note attention">{raison}</div> : null}
        {ecoute && !ecoute.modele_pret ? (
          <div className="bloc-note attention">
            Le modèle de reconnaissance vocale hors ligne n’est pas installé : les sous-titres ne peuvent pas démarrer.{' '}
            <button type="button" className="btn sm" onClick={() => nav.ouvrir('reglages-voix')}>Ouvrir Voix et écoute</button>
          </div>
        ) : null}

        <div
          ref={zone}
          className="sous-titres-direct"
          style={{ fontSize: taille }}
          onScroll={(e) => {
            const el = e.currentTarget
            suivreBas.current = el.scrollHeight - el.scrollTop - el.clientHeight < 60
          }}
        >
          {lignes.length === 0 && !partiel ? (
            <div className="vide-direct">{actif ? 'En attente de paroles…' : 'Appuyez sur « Démarrer » : ce qui se dit autour s’affichera ici.'}</div>
          ) : null}
          <div role="log" aria-live="polite" aria-relevant="additions" aria-label="Sous-titres" className="col" style={{ gap: 10 }}>
            {lignes.map((l, i) => (
              <div key={`${l.ts}-${i}`} className="ligne">{l.texte}</div>
            ))}
          </div>
          {/* La phrase en cours change sans cesse : on ne l'annonce pas, seules les phrases finales le sont. */}
          {partiel ? <div className="partiel" aria-hidden="true">{partiel}</div> : null}
        </div>

        <div className="carte col" style={{ gap: 8 }}>
          <div className="curseur">
            <div className="entete">
              <label htmlFor="taille-sous-titres">Taille du texte</label>
              <output htmlFor="taille-sous-titres">{taille} px</output>
            </div>
            <input id="taille-sous-titres" type="range" min={TAILLE_MIN} max={TAILLE_MAX} step={2} value={taille} onChange={(e) => changerTaille(Number(e.target.value))} />
          </div>
        </div>

        <div className="row wrap" style={{ gap: 10 }}>
          <Holo taille="petit" variante="sombre" onClick={exporter}><IcoTelecharger /> Exporter</Holo>
          <Holo taille="petit" variante="sombre" disabled={resumeEnCours || !lignes.length} onClick={resumer}>
            {resumeEnCours ? 'Rédaction…' : 'Résumer (procès-verbal)'}
          </Holo>
        </div>

        {refusResume ? (
          <CarteConsentement
            refus={refusResume}
            onFermer={() => setRefusResume(null)}
            onAutoriser={async () => {
              try {
                await setConsent(refusResume.data_type, true)
              } catch (err) {
                toast(messageErreur(err), 'error')
                return
              }
              setRefusResume(null)
              resumer()
            }}
          />
        ) : null}

        {resume ? (
          <div className="carte sombre col" style={{ gap: 10 }} aria-live="polite">
            <h3 style={{ margin: 0 }}>Procès-verbal</h3>
            <Markdown text={resume.texte} />
            <div className="small muted" style={{ lineHeight: 1.45 }}>
              {resume.local ? 'Rédigé sur cet ordinateur.' : 'Rédigé par le moteur VELA à partir de la transcription.'} Relisez-le : la transcription contient des erreurs de
              reconnaissance, et le résumé peut en ajouter.
            </div>
          </div>
        ) : null}

        <CarteReglage
          titre="Journal continu"
          desc="Chaque phrase finale est aussi gardée dans le journal de la journée, chiffrée sur cet ordinateur et effacée selon la durée de conservation. Le son n’est jamais gardé. L’écoute reste active tant que ce réglage l’est."
          on={Boolean(settings?.journal_continu)}
          onChange={basculerJournal}
        />
        {settings?.journal_continu && suspendue ? (
          <div className="bloc-note attention">Mémorisation suspendue (mode invité ou zone sans mémoire) : le journal n’écrit rien en ce moment.</div>
        ) : null}

        <div className="carte">
          <h3>Ce qu’il faut savoir</h3>
          <ul className="liste-limites">
            <li>La reconnaissance se fait sur cet ordinateur, à partir du micro qu’IRIS écoute (celui des lunettes quand elles lui sont connectées).</li>
            <li>Des mots sont mal reconnus, surtout avec du bruit, plusieurs personnes qui parlent en même temps, un accent marqué ou des noms propres.</li>
            <li>Le texte suit la parole avec un délai, variable selon l’ordinateur.</li>
            <li>La transcription de cette session reste en mémoire vive tant qu’IRIS tourne ; elle n’est gardée sur le disque que si le journal continu est activé ou si un cours est en cours d’enregistrement (Mode cours).</li>
          </ul>
        </div>
      </div>
    </div>
  )
}
