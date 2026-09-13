import React, { useState } from 'react'
import { BtnIcone } from '../../components/ui'
import { IcoLecture, IcoMicro, IcoMicroBarre, IcoPause, IcoStop } from '../../components/icons'
import { api } from '../../lib/api'
import { useStore } from '../../lib/store'
import { messageErreur } from './commun'

/* =========================================================================
   Barre vocale de l'onglet IA : l'état de l'écoute en un coup d'œil (pastille,
   vumètre, libellé, dernière phrase entendue ou panne), le remède contextuel
   quand l'écoute est en panne, la latence de la dernière réponse, et les
   quatre commandes (arrêter la lecture, couper/réactiver le micro, pause 10 min
   ou démarrer l'écoute, parler maintenant). Portée de l'ancienne ChatView.
   ========================================================================= */

/** Pastille d'écoute. Les classes historiques (`listening`, `talking`, `muted`) sont conservées,
 *  et une classe fine s'y ajoute (`wake`, `hearing`, `thinking`) pour distinguer les états. */
export function MicOrb({ state, muted, speaking }: { state: string; muted: boolean; speaking: boolean }): JSX.Element {
  const cls = muted
    ? 'muted'
    : speaking || state === 'speaking'
      ? 'talking'
      : state === 'off'
        ? 'idle'
        : state === 'processing'
          ? 'listening thinking'
          : state === 'command' || state === 'armed'
            ? 'listening hearing'
            : 'listening wake'
  const titre = muted
    ? 'Micro coupé'
    : speaking || state === 'speaking'
      ? 'IRIS parle'
      : state === 'off'
        ? 'Écoute arrêtée'
        : state === 'processing'
          ? 'IRIS réfléchit'
          : state === 'command' || state === 'armed'
            ? 'IRIS vous écoute'
            : 'IRIS est prête, dites le mot d’activation'
  return (
    <span className={`mic-orb ${cls}`} title={titre} aria-label={titre} role="img">
      <i />
      <b />
    </span>
  )
}

/** Niveau du micro en direct : on voit tout de suite si le micro capte trop faiblement,
 *  la première cause de commandes mal comprises. */
export function LevelMeter({ peak, active }: { peak: number; active: boolean }): JSX.Element | null {
  if (!active && !peak) return null
  const barres = 5
  const ratio = Math.min(1, peak / 9000)
  const allumees = Math.round(ratio * barres)
  return (
    <span className="level" title={`Niveau du micro : ${peak} sur 32767`}>
      {Array.from({ length: barres }, (_, i) => (
        <span key={i} className={i < allumees ? (peak > 22000 ? 'hot' : 'lit') : ''} style={{ height: 3 + (i + 1) * 3 }} />
      ))}
    </span>
  )
}

export function BarreVoix({ transcript, latence }: { transcript: string; latence: number | null }): JSX.Element {
  const { voice, settings, ttsSpeaking, micLevel, updateSettings, toast, nav } = useStore()
  const [dlModel, setDlModel] = useState(false)

  const voiceState: string = voice?.state || 'off'
  const voiceLabel: Record<string, string> = {
    off: voice?.muted ? 'Micro coupé (muet)' : voice?.paused_until ? 'Écoute en pause (reprise automatique)' : 'Écoute arrêtée',
    wake: settings?.wake_word ? `Prête — dites « ${settings.wake_word} »` : 'Prête à vous écouter',
    armed: 'Mot d’activation détecté…',
    command: 'Je vous écoute',
    processing: 'IRIS réfléchit…',
    speaking: 'IRIS parle'
  }

  // Une panne d'écoute doit se lire, et se réparer, sans quitter l'écran. On n'affiche l'erreur
  // que si l'écoute est réellement arrêtée et qu'il ne s'agit pas d'une pause volontaire.
  const voiceError: string = voiceState === 'off' && !voice?.paused_until ? voice?.error || '' : ''
  const remede: { label: string; run: () => Promise<void> } | null = !voiceError
    ? null
    : settings?.privacy_mode
      ? {
          label: 'Quitter le mode confidentiel',
          run: async () => {
            await updateSettings({ privacy_mode: false })
            api.send({ type: 'voice.start' })
          }
        }
      : voice?.muted
        ? { label: 'Réactiver le micro', run: async () => void api.send({ type: 'voice.toggle_mute' }) }
        : voice?.model_ready === false
          ? {
              label: dlModel ? 'Téléchargement…' : 'Télécharger le modèle',
              run: async () => {
                setDlModel(true)
                try {
                  await api.post('/api/voice/model/download', {})
                } catch (err) {
                  toast(messageErreur(err), 'error')
                } finally {
                  setDlModel(false)
                }
              }
            }
          : { label: 'Ouvrir les réglages voix', run: async () => nav.ouvrir('reglages-voix') }

  const dataState = voice?.muted ? 'muted' : ttsSpeaking || voiceState === 'speaking' ? 'speaking' : voiceState

  return (
    <div className="barre-voix" data-state={dataState} style={{ flexWrap: 'wrap', rowGap: 6 }}>
      <div className="state">
        <MicOrb state={voiceState} muted={Boolean(voice?.muted)} speaking={Boolean(ttsSpeaking)} />
        <span className="label" aria-live="polite">{voiceLabel[voiceState] || voiceState}</span>
      </div>
      <LevelMeter peak={micLevel && Date.now() - micLevel.at < 2500 ? micLevel.peak : 0} active={voiceState === 'command'} />
      <div className="transcript" style={voiceError ? { color: '#ff8a80' } : undefined} title={voiceError || transcript || undefined}>
        {voiceError ? `⚠ ${voiceError}` : transcript ? `« ${transcript} »` : ''}
      </div>
      {remede ? (
        <button
          type="button"
          className="btn primary sm"
          disabled={dlModel}
          onClick={() => {
            remede.run().catch((err) => toast(messageErreur(err), 'error'))
          }}
        >
          {remede.label}
        </button>
      ) : null}
      {latence !== null && !voiceError ? <span className="pill" title="Temps de réponse de la dernière commande vocale">{latence}s</span> : null}
      <div className="actions">
        {ttsSpeaking ? (
          <BtnIcone title="Arrêter la lecture (ou dites « stop »)" aria-label="Arrêter la lecture" onClick={() => api.send({ type: 'tts.stop' })}>
            <IcoStop />
          </BtnIcone>
        ) : null}
        <BtnIcone
          title={voice?.muted ? 'Réactiver le micro (Ctrl+Maj+M)' : 'Couper le micro (Ctrl+Maj+M, ou dites « muet »)'}
          aria-label={voice?.muted ? 'Réactiver le micro' : 'Couper le micro'}
          style={voice?.muted ? { color: 'var(--red)' } : undefined}
          onClick={() => api.send({ type: 'voice.toggle_mute' })}
        >
          {voice?.muted ? <IcoMicro /> : <IcoMicroBarre />}
        </BtnIcone>
        <BtnIcone
          title={voiceState === 'off' ? (voice?.paused_until ? 'Reprendre l’écoute' : 'Démarrer l’écoute') : 'Pause de 10 minutes, puis l’écoute reprend seule'}
          aria-label={voiceState === 'off' ? 'Démarrer l’écoute' : 'Pause 10 min'}
          onClick={() => api.send(voiceState === 'off' ? { type: 'voice.start' } : { type: 'voice.pause', minutes: 10 })}
        >
          {voiceState === 'off' ? <IcoLecture /> : <IcoPause />}
        </BtnIcone>
        {/* Le geste de secours de la démonstration : il fonctionne même micro coupé ou écoute en pause. */}
        <BtnIcone plein title="Parler maintenant (Ctrl+Maj+Espace) — fonctionne même micro coupé ou écoute en pause" aria-label="Parler maintenant" onClick={() => api.send({ type: 'voice.push_to_talk' })}>
          <IcoMicro />
        </BtnIcone>
      </div>
    </div>
  )
}
