import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { Modal, Puces, TopBar } from '../components/ui'
import { api, messageErreur, type IrisEvent } from '../lib/api'
import { useStore } from '../lib/store'
import './AccessibiliteScreen.css'
import './ModeInviteScreen.css'

/* =========================================================================
   « Mode invité » : prêter IRIS (ou ses lunettes) sans qu'elle retienne la
   session.

   Ce que l'écran montre est ce que le service fait (backend/iris/mode_invite.py) :
   la mémoire est suspendue, une minuterie ramène IRIS à la normale, et à la
   sortie les conversations de la session sont effacées. La limite du service
   (ce que le mode ne fait PAS) est affichée telle quelle, juste sous
   l'interrupteur, pas en bas de page.

   Sortir du mode efface : l'écran le fait confirmer, puis dit combien de
   conversations et de messages ont été effacés, ou que l'effacement est
   incomplet quand le service le signale.

   Toujours accessible sans lunettes : c'est une protection de la vie privée.
   ========================================================================= */

interface EtatInvite {
  actif: boolean
  depuis: string | null
  jusqua: string | null
  minutes_restantes: number
  limite?: string
  effacees?: { conversations: number; messages: number; erreurs: number }
}

const MINUTES_MIN = 5
const MINUTES_MAX = 720
const DUREES = [15, 30, 60, 120, 240, 480, 720]

function libelleDuree(minutes: number): string {
  if (minutes < 60) return `${minutes} min`
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  return m ? `${h} h ${String(m).padStart(2, '0')}` : `${h} h`
}

function heure(iso: string | null | undefined): string {
  if (!iso) return ''
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleTimeString('fr-CA', { hour: '2-digit', minute: '2-digit' })
}

function restant(jusqua: string | null | undefined, maintenant: number): string {
  if (!jusqua) return ''
  const fin = new Date(jusqua).getTime()
  if (Number.isNaN(fin)) return ''
  const minutes = Math.max(0, Math.ceil((fin - maintenant) / 60000))
  if (minutes === 0) return 'moins d’une minute'
  return libelleDuree(minutes)
}

function pluriel(n: number, mot: string): string {
  return `${n} ${mot}${n > 1 ? 's' : ''}`
}

export function ModeInviteScreen({ params: _params }: { params?: Record<string, any> }): JSX.Element {
  const { settings, updateSettings, toast } = useStore()
  const [etat, setEtat] = useState<EtatInvite | null>(null)
  const [erreurEtat, setErreurEtat] = useState('')
  const [occupe, setOccupe] = useState<'activer' | 'desactiver' | 'relancer' | null>(null)
  const [erreur, setErreur] = useState('')
  const [bilan, setBilan] = useState<EtatInvite['effacees'] | null>(null)
  const [confirmer, setConfirmer] = useState(false)
  const [maintenant, setMaintenant] = useState(() => Date.now())

  const charger = useCallback(async (): Promise<void> => {
    try {
      setEtat(await api.get<EtatInvite>('/api/confiance/invite'))
      setErreurEtat('')
    } catch (err) {
      setErreurEtat(messageErreur(err))
    }
  }, [])

  useEffect(() => {
    charger().catch(() => undefined)
    return api.on((e: IrisEvent) => {
      // Activé ou terminé ailleurs : à la voix, par la minuterie ou depuis le téléphone.
      if (e.type === 'invite.etat' || e.type === 'ws.open') charger().catch(() => undefined)
    })
  }, [charger])

  const actif = Boolean(etat?.actif)

  useEffect(() => {
    if (!actif) return
    setMaintenant(Date.now())
    const t = window.setInterval(() => setMaintenant(Date.now()), 15000)
    return () => window.clearInterval(t)
  }, [actif])

  const duree = Math.min(MINUTES_MAX, Math.max(MINUTES_MIN, Number(settings?.mode_invite_minutes) || 120))
  const options = useMemo(() => {
    const liste = DUREES.includes(duree) ? DUREES : [...DUREES, duree].sort((a, b) => a - b)
    return liste.map((m) => ({ id: String(m), label: libelleDuree(m) }))
  }, [duree])

  const choisirDuree = (id: string): void => {
    const minutes = Number(id)
    if (!Number.isFinite(minutes) || minutes === duree) return
    updateSettings({ mode_invite_minutes: minutes }).catch((err: unknown) => toast(messageErreur(err), 'error'))
  }

  const activer = async (relancer = false): Promise<void> => {
    setOccupe(relancer ? 'relancer' : 'activer')
    setErreur('')
    setBilan(null)
    try {
      setEtat(await api.post<EtatInvite>('/api/confiance/invite/activer', { minutes: duree }))
      if (relancer) toast(`Minuterie repartie : ${libelleDuree(duree)}.`, 'success')
    } catch (err) {
      setErreur(messageErreur(err))
    } finally {
      setOccupe(null)
    }
  }

  const desactiver = async (): Promise<void> => {
    setConfirmer(false)
    setOccupe('desactiver')
    setErreur('')
    try {
      const r = await api.post<EtatInvite>('/api/confiance/invite/desactiver')
      setEtat(r)
      setBilan(r.effacees || null)
    } catch (err) {
      setErreur(messageErreur(err))
    } finally {
      setOccupe(null)
    }
  }

  const basculer = (): void => {
    if (occupe || !etat) return
    if (actif) setConfirmer(true)
    else activer().catch(() => undefined)
  }

  const mot: string = settings?.wake_word || 'Dis-moi Iris'

  return (
    <div className="ecran">
      <TopBar titre="Mode invité" />
      <div className="contenu">
        {erreurEtat ? <div className="bloc-note erreur" role="alert">{erreurEtat}</div> : null}

        {/* ------------------------------------------------------------ grand interrupteur */}
        <div className={`mi-carte ${actif ? 'actif' : ''}`}>
          <div className="mi-tete">
            <div className="mi-titres">
              <h2>Mode invité</h2>
              <p>{actif ? 'Mémoire suspendue ; les conversations de la session seront effacées à la fin.' : 'Prêtez IRIS : pas de nouveaux souvenirs, et les conversations de la session effacées à la fin.'}</p>
            </div>
            <button
              type="button"
              role="switch"
              aria-checked={actif}
              aria-label="Mode invité"
              className={`mi-interrupteur ${actif ? 'on' : ''}`}
              disabled={!etat || occupe !== null}
              onClick={basculer}
            >
              <span className="bille" aria-hidden="true" />
              <span className="texte">{occupe === 'activer' ? 'Activation…' : occupe === 'desactiver' ? 'Effacement…' : actif ? 'Activé' : 'Désactivé'}</span>
            </button>
          </div>

          {actif && etat ? (
            <div className="mi-temps" aria-live="polite">
              <div>
                <span className="etiquette">Temps restant</span>
                <span className="valeur">{restant(etat.jusqua, maintenant) || '—'}</span>
              </div>
              <div className="small">
                Actif depuis {heure(etat.depuis)}, jusqu’à {heure(etat.jusqua)}. À l’échéance, IRIS revient à la normale, efface la session et le dit à voix
                haute quand la voix est disponible.
              </div>
              <button type="button" className="btn sm" disabled={occupe !== null} onClick={() => activer(true)}>
                {occupe === 'relancer' ? 'Envoi…' : `Repartir pour ${libelleDuree(duree)}`}
              </button>
            </div>
          ) : null}
        </div>

        {etat?.limite ? (
          <div className="bloc-note attention">
            <strong>Ce que le mode fait et ne fait pas : </strong>
            {etat.limite}
          </div>
        ) : null}

        {erreur ? <div className="bloc-note erreur" role="alert">{erreur}</div> : null}
        {bilan ? (
          bilan.erreurs > 0 ? (
            <div className="bloc-note erreur" role="alert">
              Mode invité terminé, mais une partie de la session n’a pas pu être effacée ({pluriel(bilan.erreurs, 'erreur')}). Vérifiez l’historique des
              discussions et effacez à la main ce qui reste.
            </div>
          ) : (
            <div className="bloc-note ok" aria-live="polite">
              Mode invité terminé : {pluriel(bilan.conversations, 'conversation')} et {pluriel(bilan.messages, 'message')} de la session effacés. La mémoire
              reprend, sauf si une autre protection (zone sans mémoire) la suspend encore.
            </div>
          )
        ) : null}

        {/* ------------------------------------------------------------ durée */}
        <div className="carte col" style={{ gap: 10 }}>
          <h3 style={{ margin: 0 }}>Durée</h3>
          <div className="desc">Après ce délai, le mode invité se termine seul. La même durée s’applique quand vous l’activez à la voix.</div>
          <Puces options={options} valeur={String(duree)} onChange={choisirDuree} />
          {actif ? <div className="small muted">Une nouvelle durée compte à partir de « Repartir ».</div> : null}
        </div>

        {/* ------------------------------------------------------------ ce qui est suspendu */}
        <div className="carte">
          <h3>Pendant le mode invité</h3>
          <ul className="liste-limites">
            <li>Aucun nouveau souvenir, ni journal d’écoute, ni cours, ni photo décrite, ni reçu n’est enregistré.</li>
            <li>IRIS ne s’appuie pas sur vos souvenirs pour répondre : un invité ne les obtient pas en posant une question.</li>
            <li>À la fin, les conversations commencées pendant la session sont effacées, ainsi que les messages ajoutés aux conversations existantes.</li>
            <li>Un redémarrage d’IRIS ne met pas fin au mode : il reprend jusqu’à l’heure prévue.</li>
          </ul>
          <h3 style={{ marginTop: 16 }}>Ce qui n’est pas couvert</h3>
          <ul className="liste-limites">
            <li>Vos souvenirs déjà enregistrés restent visibles dans l’application (onglet Profil › Mémoire) : le mode ne les cache pas.</li>
            <li>Les rappels et les tâches créés pendant la session ne sont pas effacés à la fin.</li>
            <li>Ce qui a été envoyé ailleurs pendant la session (message, courriel, fichier exporté) n’est pas rappelé.</li>
          </ul>
        </div>

        {/* ------------------------------------------------------------ voix */}
        <div className="carte col" style={{ gap: 10 }}>
          <h3 style={{ margin: 0 }}>À la voix</h3>
          <div className="mi-phrases">
            <span>« {mot}, mode invité »</span>
            <span>« {mot}, fin du mode invité »</span>
          </div>
          <div className="small muted" style={{ lineHeight: 1.45 }}>
            Ces phrases passent avant tout le reste. IRIS ne sait pas qui parle dans les lunettes : « fin du mode invité » n’est
            acceptée à la voix que si le verrou vocal est actif, ce qui n’est pas encore offert. Aujourd’hui, le mode se termine
            depuis cet écran (ou l’application du téléphone) ou tout seul à l’heure prévue.
          </div>
        </div>
      </div>

      {confirmer ? (
        <Modal
          title="Terminer le mode invité ?"
          onClose={() => setConfirmer(false)}
          actions={
            <>
              <button type="button" className="btn ghost" onClick={() => setConfirmer(false)}>Continuer le mode invité</button>
              <button type="button" className="btn danger" onClick={() => desactiver()}>Terminer et effacer</button>
            </>
          }
        >
          <p>Les conversations de la session seront effacées de cet ordinateur. Cette action ne peut pas être annulée.</p>
        </Modal>
      ) : null}
    </div>
  )
}
