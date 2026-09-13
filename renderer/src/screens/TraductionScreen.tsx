import React, { useCallback, useEffect, useRef, useState } from 'react'
import { useStore } from '../lib/store'
import { api, type IrisEvent } from '../lib/api'
import { Field, Holo, TopBar, Vide } from '../components/ui'
import { IcoOreille, IcoReunion, IcoTelephoneEcran } from '../components/icons'

/* =========================================================================
   « Traduction avec IA » (maquette IMG_0711) : trois grandes cartes. Seule
   l'interprétation simultanée a un support côté service (le mode traduction
   de l'écoute vocale) ; les deux autres sont « à venir ». La section « live »
   pilote le mode et affiche le fil des échanges reçus par WebSocket.
   ========================================================================= */

const LANGUES_DEFAUT: { code: string; nom: string }[] = [
  { code: 'en', nom: 'Anglais' },
  { code: 'es', nom: 'Espagnol' },
  { code: 'pt', nom: 'Portugais' },
  { code: 'it', nom: 'Italien' },
  { code: 'de', nom: 'Allemand' },
  { code: 'fr', nom: 'Français' }
]

const RAISONS: Record<string, string> = {
  demande: 'à votre demande',
  silence: 'après un long silence',
  erreur: 'après plusieurs échecs',
  traduction: 'relancée'
}

interface Echange {
  id: number
  genre: 'info' | 'entendu' | 'traduit'
  texte?: string
  langue?: string
  original?: string
  traduction?: string
  reponse_suggeree?: string
  reponse_traduite?: string
  latence?: number
}

const STYLE_CARTE: React.CSSProperties = {
  minHeight: 270,
  display: 'flex',
  flexDirection: 'column',
  alignItems: 'center',
  justifyContent: 'center',
  gap: 24,
  textAlign: 'center',
  border: 'none',
  color: 'var(--text)',
  width: '100%'
}
const STYLE_ICONE: React.CSSProperties = { width: 56, height: 56 }

function nomLangue(code: string, langues: { code: string; nom: string }[]): string {
  return langues.find((l) => l.code === code)?.nom || code
}

export function TraductionScreen({ params }: { params?: Record<string, any> }): JSX.Element {
  const { toast, settings, voice } = useStore()
  const [mode, setMode] = useState<'menu' | 'live'>(params?.mode === 'live' ? 'live' : 'menu')
  const [etat, setEtat] = useState<any>(null)
  const [langue, setLangue] = useState<string>('en')
  const [occupe, setOccupe] = useState(false)
  const [ecoute, setEcoute] = useState(false)
  const [fil, setFil] = useState<Echange[]>([])
  const compteur = useRef(1)
  const finFil = useRef<HTMLDivElement | null>(null)
  const wake: string = settings?.wake_word || 'Dis-moi Iris'

  const langues: { code: string; nom: string }[] = Array.isArray(etat?.langues) && etat.langues.length ? etat.langues : LANGUES_DEFAUT

  const ajouter = useCallback((e: Omit<Echange, 'id'>) => {
    setFil((f) => [...f, { ...e, id: compteur.current++ }])
  }, [])

  const chargerEtat = useCallback(async () => {
    try {
      const r = await api.get('/api/traduction/etat')
      setEtat(r)
      if (r?.actif && r?.langue_entendue) setLangue(String(r.langue_entendue))
    } catch {
      /* le service ne connaît pas encore cet état : on garde les langues par défaut */
    }
  }, [])

  // Au montage, puis chaque fois que l'écoute vocale démarre ou s'arrête : `ecoute` (GET
  // /api/traduction/etat) dit si quelqu'un entend vraiment l'interlocuteur.
  const ecouteVocaleEnDirect: boolean | undefined = typeof voice?.running === 'boolean' ? voice.running : undefined
  useEffect(() => {
    chargerEtat()
  }, [chargerEtat, ecouteVocaleEnDirect])

  // Fil des échanges : événements « voice.traduction » du service (local à l'écran).
  useEffect(() => {
    return api.on((e: IrisEvent) => {
      if (e.type !== 'voice.traduction') return
      switch (e.etat) {
        case 'ouvert':
          setEtat((p: any) => ({ ...(p || {}), actif: true, langue_entendue: e.langue, langue_entendue_nom: e.langue_nom, empechement: '' }))
          setMode('live')
          ajouter({ genre: 'info', texte: `Traduction ouverte · ${e.langue_nom || e.langue || ''}`.trim() })
          break
        case 'ecoute':
          setEcoute(true)
          break
        case 'entendu':
          setEcoute(false)
          ajouter({ genre: 'entendu', texte: String(e.texte || ''), langue: e.langue })
          break
        case 'traduit':
          if (e.ok === false) {
            ajouter({ genre: 'info', texte: String(e.raison || e.a_dire || 'Phrase non traduite.') })
          } else {
            ajouter({
              genre: 'traduit',
              original: e.original,
              traduction: String(e.traduction || e.a_dire || ''),
              reponse_suggeree: e.reponse_suggeree,
              reponse_traduite: e.reponse_traduite,
              latence: typeof e.latence === 'number' ? e.latence : undefined
            })
          }
          break
        case 'ferme':
          setEcoute(false)
          setEtat((p: any) => ({ ...(p || {}), actif: false }))
          ajouter({ genre: 'info', texte: `Traduction terminée${e.raison && RAISONS[e.raison] ? ` (${RAISONS[e.raison]})` : ''}` })
          break
        default:
          break
      }
    })
  }, [ajouter])

  useEffect(() => {
    finFil.current?.scrollIntoView({ block: 'end' })
  }, [fil.length])

  const demarrer = async (): Promise<void> => {
    if (occupe) return
    setOccupe(true)
    try {
      const r = await api.post('/api/traduction/demarrer', { langue })
      const actif = Boolean(r?.actif ?? r?.ouvert)
      if (!actif) {
        toast(r?.phrase || r?.empechement || 'La traduction n’a pas pu démarrer.', 'error')
      } else if (r?.ecoute === false) {
        // Armé mais sourd : le service le dit dans sa phrase ; on ne le fête pas en vert.
        toast(r?.phrase || 'Traduction armée, mais l’écoute vocale est arrêtée : démarrez-la pour qu’IRIS entende votre interlocuteur.', 'info')
        setEtat((p: any) => ({ ...(p || {}), ...r, actif: true }))
      } else {
        toast(r?.phrase || 'Traduction démarrée.', 'success')
        setEtat((p: any) => ({ ...(p || {}), ...r, actif: true }))
      }
      await chargerEtat()
    } catch (err) {
      toast(String((err as Error).message), 'error')
    } finally {
      setOccupe(false)
    }
  }

  const arreter = async (): Promise<void> => {
    if (occupe) return
    setOccupe(true)
    try {
      const r = await api.post('/api/traduction/arreter')
      toast(r?.phrase || 'Traduction arrêtée.', 'info')
      setEtat((p: any) => ({ ...(p || {}), actif: false }))
      setEcoute(false)
      await chargerEtat()
    } catch (err) {
      toast(String((err as Error).message), 'error')
    } finally {
      setOccupe(false)
    }
  }

  const aVenir = (): void => toast('Pas encore disponible dans cette version.', 'info')
  const actif = Boolean(etat?.actif)
  const live = mode === 'live' || actif
  const empechement: string = String(etat?.empechement || '')
  // Écoute vocale : le signal vivant du store (voice.state) d'abord, sinon l'instantané de l'état.
  const ecouteVocale: boolean | undefined = ecouteVocaleEnDirect ?? (typeof etat?.ecoute === 'boolean' ? etat.ecoute : undefined)
  const sourd = actif && ecouteVocale === false

  return (
    <div className="ecran">
      <TopBar titre="Traduction avec IA" />
      <div className="contenu">
        <div className="cartes-2">
          <button type="button" className="carte" style={STYLE_CARTE} onClick={aVenir} title="À venir">
            <h3 style={{ fontSize: 26, margin: 0 }}>Traduction par écran</h3>
            <IcoTelephoneEcran style={STYLE_ICONE} />
            <span className="pill warn">À venir</span>
          </button>
          <button type="button" className="carte" style={STYLE_CARTE} onClick={() => setMode('live')}>
            <h3 style={{ fontSize: 26, margin: 0 }}>Interprétation simultanée</h3>
            <IcoOreille style={STYLE_ICONE} />
          </button>
          <button type="button" className="carte" style={STYLE_CARTE} onClick={aVenir} title="À venir">
            <h3 style={{ fontSize: 26, margin: 0 }}>Procès-verbal de la réunion</h3>
            <IcoReunion style={STYLE_ICONE} />
            <span className="pill warn">À venir</span>
          </button>
        </div>

        {live ? (
          <>
            <div className="carte">
              <div className="row between wrap" style={{ marginBottom: 12 }}>
                <h3 style={{ margin: 0 }}>Interprétation simultanée</h3>
                {actif ? <span className="pill ok">En cours · {etat?.langue_entendue_nom || nomLangue(String(etat?.langue_entendue || langue), langues)}</span> : null}
                {sourd ? <span className="pill warn" title="Le mode est armé, mais aucun micro n’écoute votre interlocuteur.">Écoute vocale arrêtée</span> : null}
                {actif && !sourd && ecoute ? <span className="pill">À l’écoute</span> : null}
              </div>
              <Field label="Langue de votre interlocuteur">
                <select className="select" value={langue} disabled={actif || occupe} onChange={(e) => setLangue(e.target.value)}>
                  {langues.map((l) => (
                    <option key={l.code} value={l.code}>{l.nom}</option>
                  ))}
                </select>
              </Field>
              <div style={{ marginTop: 14 }}>
                {!actif ? (
                  <Holo onClick={demarrer} disabled={occupe}>Démarrer</Holo>
                ) : (
                  <Holo variante="rouge" onClick={arreter} disabled={occupe}>Arrêter</Holo>
                )}
              </div>
              <p className="muted small" style={{ marginTop: 12, lineHeight: 1.4 }}>
                Exige les lunettes VELA connectées et un moteur IA (indisponible en mode 100 % local).
              </p>
              {empechement ? (
                <div style={{ marginTop: 8 }}>
                  <span className="pill warn" style={{ whiteSpace: 'normal', lineHeight: 1.35 }}>{empechement}</span>
                </div>
              ) : null}
              <p className="muted small" style={{ marginTop: 8, lineHeight: 1.4 }}>
                Vous pouvez aussi dire : « {wake}, traduis ce qu’il dit en {nomLangue(langue, langues).toLowerCase()} ».
              </p>
            </div>

            {fil.length === 0 ? (
              <Vide icone={<IcoOreille style={{ color: 'var(--text-2)' }} />} texte="Aucun échange pour le moment" />
            ) : (
              <div className="fil">
                {fil.map((e) => {
                  if (e.genre === 'info') return <div key={e.id} className="date">{e.texte}</div>
                  if (e.genre === 'entendu') {
                    return (
                      <div key={e.id} className="message">
                        <div className="colonne-msg">
                          <div className="bulle" style={{ background: 'var(--surface)', color: 'var(--text)' }}>{e.texte}</div>
                          {e.langue ? <div className="meta"><span className="etiquette">{nomLangue(e.langue, langues)}</span></div> : null}
                        </div>
                      </div>
                    )
                  }
                  return (
                    <div key={e.id} className="message">
                      <div className="colonne-msg">
                        <div className="bulle ia">{e.traduction}</div>
                        {e.reponse_suggeree ? (
                          <div className="muted small" style={{ padding: '0 4px', lineHeight: 1.4 }}>
                            Réponse suggérée : {e.reponse_suggeree}
                            {e.reponse_traduite ? <> → {e.reponse_traduite}</> : null}
                          </div>
                        ) : null}
                        {typeof e.latence === 'number' ? <div className="meta">{e.latence.toFixed(1)} s</div> : null}
                      </div>
                    </div>
                  )
                })}
                <div ref={finFil} />
              </div>
            )}
          </>
        ) : null}
      </div>
    </div>
  )
}
