import React, { useEffect, useState } from 'react'
import { Field, SettingRow, Toggle, TopBar } from '../components/ui'
import { api, type IrisEvent } from '../lib/api'
import { useStore } from '../lib/store'

/* =========================================================================
   « Voix et écoute » : tout le côté voix de l'ancien écran Paramètres.
   Activation (mot, langue, variantes, mots d'arrêt, calibration),
   reconnaissance (modèle hors-ligne, moteur, écoute, dialogue), voix de
   synthèse (lecture, moteur, voix Windows, débit), voix premium (clé
   ElevenLabs — écran avancé où le nom du fournisseur est permis), raccourcis.
   Les champs texte suivent le motif brouillon/validation : édition locale,
   envoi au service quand le champ perd le focus.
   ========================================================================= */

type CleListe = 'wake_aliases' | 'stop_words' | 'mute_words'

function joindre(v: unknown): string {
  return Array.isArray(v) ? v.join(', ') : ''
}
function decouper(s: string): string[] {
  return s.split(',').map((x) => x.trim()).filter(Boolean)
}
function listesDepuis(settings: any): Record<CleListe, string> {
  return {
    wake_aliases: joindre(settings?.wake_aliases),
    stop_words: joindre(settings?.stop_words),
    mute_words: joindre(settings?.mute_words)
  }
}

export function ReglagesVoixScreen({ params: _params }: { params?: Record<string, any> }): JSX.Element {
  const { settings, updateSettings, voice, toast } = useStore()
  const [draft, setDraft] = useState<any>(settings)
  // Les listes se tapent comme du texte (« stop, arrête, chut ») et ne deviennent des tableaux
  // qu'à la validation : découper à chaque frappe effacerait la virgule que l'on vient d'écrire.
  const [listes, setListes] = useState<Record<CleListe, string>>(() => listesDepuis(settings))
  const [voices, setVoices] = useState<any[]>([])
  const [eleven, setEleven] = useState<any>(null)
  const [elevenKey, setElevenKey] = useState('')
  const [elevenOccupe, setElevenOccupe] = useState(false)
  const [progress, setProgress] = useState<{ done: number; total: number } | null>(null)
  // Calibration en cours : tant qu'elle tourne, IRIS enregistre comme variante toute phrase
  // entendue. Il faut donc pouvoir l'arrêter, et voir qu'elle tourne.
  const [calibRestant, setCalibRestant] = useState(0)

  useEffect(() => {
    setDraft(settings)
    setListes(listesDepuis(settings))
  }, [settings])

  useEffect(() => {
    api.get('/api/voice/voices').then((r) => setVoices(Array.isArray(r?.voices) ? r.voices : [])).catch(() => undefined)
    api.get('/api/voice/elevenlabs').then(setEleven).catch(() => undefined)
    return api.on((e: IrisEvent) => {
      if (e.type === 'voice.model_progress') setProgress({ done: Number(e.done) || 0, total: Number(e.total) || 0 })
      if (e.type === 'voice.model_ready') setProgress(null)
      if (e.type === 'voice.calibration') setCalibRestant(e.active ? Number(e.remaining) || 0 : 0)
    })
  }, [])

  if (!draft) {
    return (
      <div className="ecran">
        <TopBar titre="Voix et écoute" />
      </div>
    )
  }

  const set = (patch: Record<string, unknown>): Promise<void> => updateSettings(patch).catch((err: Error) => toast(String(err.message), 'error'))
  const commit = (key: string): void => {
    if (draft[key] !== settings?.[key]) set({ [key]: draft[key] })
  }
  const commitListe = (cle: CleListe): void => {
    const valeur = decouper(listes[cle])
    if (JSON.stringify(valeur) !== JSON.stringify(settings?.[cle] || [])) set({ [cle]: valeur })
  }
  const erreur = (e: unknown): void => toast(e instanceof Error ? e.message : String(e), 'error')

  /* ---------------------------------------------------------------- calibration */
  const calibrer = (): void => {
    api
      .post('/api/voice/calibrate', { count: 3 })
      .then((r) => toast(r?.error || 'Dites le mot d’activation, 3 fois, en marquant une pause.', r?.error ? 'error' : 'info'))
      .catch(erreur)
  }
  const arreterCalibration = (): void => {
    api
      .post('/api/voice/calibrate', { count: 0 })
      .then(() => {
        setCalibRestant(0)
        toast('Calibration arrêtée.', 'info')
      })
      .catch(erreur)
  }

  /* ---------------------------------------------------------------- modèle hors-ligne */
  const telechargerModele = (): void => {
    api
      .post('/api/voice/model/download', {})
      .then(() => setProgress({ done: 0, total: 0 }))
      .catch(erreur)
  }
  const pourcentage = progress && progress.total ? Math.round((progress.done / progress.total) * 100) : null

  /* ---------------------------------------------------------------- voix de synthèse */
  const ecouterExemple = (): void => {
    api
      .post('/api/voice/say', { text: `Bonjour, je suis ${draft.assistant_name || 'IRIS'}. Dites ${draft.wake_word || 'Dis-moi Iris'} pour me parler.` })
      .catch(erreur)
  }
  const moteurEnCours: string = eleven
    ? eleven.engine_in_use === 'elevenlabs'
      ? 'voix naturelle (français)'
      : eleven.engine_in_use === 'piper'
        ? 'voix française hors-ligne'
        : 'voix Windows'
    : ''

  /* ---------------------------------------------------------------- voix premium (ElevenLabs) */
  const rechargerEleven = (): Promise<void> => {
    setElevenOccupe(true)
    return api
      .get('/api/voice/elevenlabs?refresh=true')
      .then(setEleven)
      .catch(erreur)
      .finally(() => setElevenOccupe(false))
  }
  const enregistrerCleEleven = (): void => {
    const cle = elevenKey.trim()
    if (!cle) return
    setElevenOccupe(true)
    api
      .post('/api/voice/elevenlabs/key', { api_key: cle })
      .then(() => {
        setElevenKey('')
        return api.get('/api/voice/elevenlabs?refresh=true')
      })
      .then((r) => {
        setEleven(r)
        toast('Clé de voix enregistrée.', 'success')
      })
      .catch(erreur)
      .finally(() => setElevenOccupe(false))
  }
  const ecouterEleven = (): void => {
    api
      .post('/api/voice/elevenlabs/test')
      .then((r) => {
        if (r?.error) toast(String(r.error), 'error')
      })
      .catch(erreur)
  }
  const voixEleven: any[] = Array.isArray(eleven?.voices) ? eleven.voices : []
  const modelesEleven: any[] = Array.isArray(eleven?.models) ? eleven.models : []

  return (
    <div className="ecran">
      <TopBar titre="Voix et écoute" />
      <div className="contenu">
        {/* ------------------------------------------------------------ activation */}
        <h3 className="section-sous">Activation</h3>
        <div className="carte col" style={{ gap: 14 }}>
          <Field label="Mot d’activation" hint={`Dites-le suivi de votre demande, ex. « ${draft.wake_word || 'Dis-moi Iris'}, ouvre mon navigateur ».`}>
            <input className="input" value={draft.wake_word || ''} onChange={(e) => setDraft({ ...draft, wake_word: e.target.value })} onBlur={() => commit('wake_word')} />
          </Field>
          <Field label="Langue">
            <select className="select" value={draft.language || 'fr-CA'} onChange={(e) => set({ language: e.target.value })}>
              <option value="fr-CA">Français (Canada)</option>
              <option value="fr-FR">Français (France)</option>
              <option value="en-US">English (US)</option>
            </select>
          </Field>
          <Field label="Variantes acceptées du mot d’activation" hint="Séparées par des virgules. Si IRIS n’entend pas votre mot, ajoutez ici ce qu’elle affiche dans « Entendu : … ».">
            <input className="input" value={listes.wake_aliases} onChange={(e) => setListes({ ...listes, wake_aliases: e.target.value })} onBlur={() => commitListe('wake_aliases')} />
          </Field>
          <Field label="Mots d’arrêt (coupent la parole d’IRIS)" hint="Séparés par des virgules. IRIS écoute pendant qu’elle parle : « stop » l’interrompt immédiatement.">
            <input className="input" value={listes.stop_words} onChange={(e) => setListes({ ...listes, stop_words: e.target.value })} onBlur={() => commitListe('stop_words')} />
          </Field>
          <Field label="Mots pour couper le micro" hint="Ex. « muet » : IRIS dit « Micro coupé » puis n’écoute plus jusqu’à réactivation (bouton, Ctrl+Maj+M, barre système).">
            <input className="input" value={listes.mute_words} onChange={(e) => setListes({ ...listes, mute_words: e.target.value })} onBlur={() => commitListe('mute_words')} />
          </Field>
          <SettingRow
            title="Calibrer le mot d’activation sur votre voix"
            desc={
              calibRestant > 0
                ? `Calibration en cours : ${calibRestant} répétition${calibRestant > 1 ? 's' : ''} attendue${calibRestant > 1 ? 's' : ''}. Tant qu’elle dure, chaque phrase entendue peut devenir une variante — arrêtez-la si vous parlez d’autre chose.`
                : 'Dites votre mot d’activation 3 fois : IRIS apprend ce que la reconnaissance entend réellement et l’ajoute aux variantes acceptées.'
            }
          >
            {calibRestant > 0 ? (
              <button type="button" className="btn sm danger" onClick={arreterCalibration}>Arrêter</button>
            ) : (
              <button type="button" className="btn sm" onClick={calibrer}>Apprendre ma façon de le dire (3 répétitions)</button>
            )}
          </SettingRow>
        </div>

        {/* ------------------------------------------------------------ reconnaissance */}
        <h3 className="section-sous">Reconnaissance</h3>
        <div className="carte">
          <SettingRow
            title="Reconnaissance vocale hors-ligne"
            desc={
              voice?.model_ready
                ? `Modèle installé : ${voice.model_info?.label || ''}. Tout est traité sur l’appareil.`
                : `Modèle absent : ${voice?.model_info?.label || ''}. Sans lui, la voix nécessite la reconnaissance en ligne (consentement « audio brut »).`
            }
          >
            {voice?.model_ready ? (
              <span className="pill ok">installé</span>
            ) : progress ? (
              <div style={{ width: 180 }}>
                <div className={`progress ${pourcentage === null ? 'indet' : ''}`}>
                  <div style={pourcentage === null ? undefined : { width: `${pourcentage}%` }} />
                </div>
                <div className="small muted" style={{ marginTop: 4 }}>
                  {pourcentage !== null ? `${pourcentage} % · ` : ''}
                  {Math.round(progress.done / 1e6)} Mo{progress.total ? ` / ${Math.round(progress.total / 1e6)} Mo` : ''}
                </div>
              </div>
            ) : (
              <button type="button" className="btn primary sm" onClick={telechargerModele}>Télécharger le modèle</button>
            )}
          </SettingRow>
          <SettingRow title="Moteur de reconnaissance">
            <select className="select" aria-label="Moteur de reconnaissance" style={{ width: 240 }} value={draft.stt_engine || 'auto'} onChange={(e) => set({ stt_engine: e.target.value })}>
              <option value="auto">Automatique (hors-ligne si possible)</option>
              <option value="vosk">Hors-ligne uniquement (sur l’appareil)</option>
              <option value="google">En ligne (avec consentement)</option>
            </select>
          </SettingRow>
          <SettingRow title="Démarrer l’écoute avec IRIS" desc="Le micro s’active au lancement (l’indicateur reste visible).">
            <Toggle on={Boolean(draft.voice_autostart)} onChange={(v) => set({ voice_autostart: v })} titre="Démarrer l’écoute avec IRIS" />
          </SettingRow>
          <SettingRow title="Accusé vocal (« Oui ? »)" desc="Quand le mot d’activation est dit seul, sans commande.">
            <Toggle on={Boolean(draft.voice_ack)} onChange={(v) => set({ voice_ack: v })} titre="Accusé vocal" />
          </SettingRow>
          <SettingRow title="Dialogue de suivi" desc="Si IRIS pose une question, elle écoute la réponse sans mot d’activation.">
            <Toggle on={Boolean(draft.voice_followup)} onChange={(v) => set({ voice_followup: v })} titre="Dialogue de suivi" />
          </SettingRow>
          <SettingRow title="Rapidité des réponses vocales" desc="Effort de raisonnement pour la voix. « Rapide » vise une réponse en moins de 5 secondes.">
            <select className="select" aria-label="Rapidité des réponses vocales" style={{ width: 160 }} value={draft.voice_effort || 'low'} onChange={(e) => set({ voice_effort: e.target.value })}>
              <option value="low">Rapide</option>
              <option value="medium">Équilibré</option>
              <option value="high">Approfondi</option>
            </select>
          </SettingRow>
          <SettingRow title="Modèle dédié à la voix" desc="Vide = même modèle que l’assistante. Usage avancé : indiquez un identifiant de modèle.">
            <input
              className="input mono"
              aria-label="Modèle dédié à la voix"
              style={{ width: 200 }}
              placeholder="identifiant de modèle"
              value={draft.voice_model || ''}
              onChange={(e) => setDraft({ ...draft, voice_model: e.target.value })}
              onBlur={() => commit('voice_model')}
            />
          </SettingRow>
        </div>

        {/* ------------------------------------------------------------ voix de synthèse */}
        <h3 className="section-sous">Voix de synthèse</h3>
        <div className="carte">
          <SettingRow title="Lecture vocale des réponses" desc="Les réponses sont lues phrase par phrase pendant qu’elles arrivent.">
            <Toggle on={Boolean(draft.tts_enabled)} onChange={(v) => set({ tts_enabled: v })} titre="Lecture vocale des réponses" />
          </SettingRow>
          <SettingRow title="Moteur de voix" desc={moteurEnCours ? `En cours : ${moteurEnCours}${eleven?.error ? ' · ' + eleven.error : ''}` : undefined}>
            <select className="select" aria-label="Moteur de voix" style={{ width: 240 }} value={draft.tts_engine || 'auto'} onChange={(e) => set({ tts_engine: e.target.value })}>
              <option value="auto">Automatique (voix naturelle si disponible)</option>
              <option value="elevenlabs">Voix naturelle</option>
              <option value="piper">Voix française hors-ligne</option>
              <option value="windows">Voix Windows (hors-ligne)</option>
            </select>
          </SettingRow>
          <SettingRow
            title="Voix Windows (repli hors-ligne)"
            desc={
              voices.length
                ? `${voices.length} voix disponible${voices.length > 1 ? 's' : ''}. Pour une voix française, installez « Microsoft Hortense » ou « Caroline » dans Windows › Heure et langue › Voix.`
                : 'Aucune voix détectée.'
            }
          >
            <select className="select" aria-label="Voix Windows (repli hors-ligne)" style={{ width: 220 }} value={draft.tts_voice || ''} onChange={(e) => set({ tts_voice: e.target.value })}>
              <option value="">Automatique</option>
              {voices.map((v) => (
                <option key={v.id} value={v.id}>{v.name}</option>
              ))}
            </select>
          </SettingRow>
          <div style={{ padding: '12px 0 4px' }}>
            <div className="row between">
              <div style={{ fontWeight: 600, fontSize: 16 }}>Débit de parole</div>
              <span className="small muted">{draft.tts_rate}</span>
            </div>
            <input
              type="range"
              min={120}
              max={260}
              aria-label="Débit de parole"
              value={Number(draft.tts_rate) || 185}
              onChange={(e) => setDraft({ ...draft, tts_rate: Number(e.target.value) })}
              onMouseUp={() => commit('tts_rate')}
              onKeyUp={() => commit('tts_rate')}
              onBlur={() => commit('tts_rate')}
              style={{ margin: '10px 0' }}
            />
            <div className="row">
              <button type="button" className="btn sm" onClick={ecouterExemple} title="Lit une phrase d’exemple avec la voix et le débit actuels.">Écouter un exemple</button>
            </div>
          </div>
        </div>

        {/* ------------------------------------------------------------ voix premium (clé personnelle) */}
        <h3 className="section-sous">Voix premium (clé ElevenLabs)</h3>
        <div className="carte col" style={{ gap: 12 }}>
          <div className="small muted" style={{ lineHeight: 1.45 }}>
            {eleven?.configured
              ? `Clé chargée depuis le fichier .env (${eleven.env_file}).${eleven.subscription?.limit ? ` Quota : ${eleven.subscription.used} / ${eleven.subscription.limit} caractères ce mois-ci (palier ${eleven.subscription.tier}).` : ''}`
              : 'Usage avancé : une clé de voix personnelle ElevenLabs, écrite dans le fichier .env du dossier de données, jamais dans le code. Non nécessaire — la voix naturelle est fournie par VELA.'}
          </div>
          <div className="row wrap" style={{ gap: 8 }}>
            {eleven?.configured ? <span className="pill ok">clé chargée</span> : <span className="pill">aucune clé</span>}
            {eleven?.engine_in_use ? <span className="pill">en cours : {moteurEnCours}</span> : null}
            {eleven?.error ? <span className="pill err">{String(eleven.error)}</span> : null}
          </div>
          <Field label="Clé ElevenLabs" hint="Saisie par vous, jamais affichée.">
            <input
              className="input mono"
              type="password"
              autoComplete="off"
              placeholder={eleven?.configured ? '•••••• (remplacer)' : 'clé de voix'}
              value={elevenKey}
              onChange={(e) => setElevenKey(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') enregistrerCleEleven()
              }}
            />
          </Field>
          <div className="row wrap">
            <button type="button" className="btn primary sm" disabled={!elevenKey.trim() || elevenOccupe} onClick={enregistrerCleEleven}>Enregistrer</button>
            <button type="button" className="btn sm" disabled={elevenOccupe} onClick={() => { rechargerEleven() }}>{elevenOccupe ? 'Actualisation…' : 'Actualiser'}</button>
          </div>
          {eleven?.configured ? (
            <>
              <Field label="Voix naturelle" hint="Les voix marquées « fr » parlent nativement français. Au palier gratuit, seules les voix de base sont utilisables : Sarah (fr) est recommandée ; les voix de bibliothèque comme Mélanie exigent un abonnement.">
                <select className="select" value={draft.elevenlabs_voice_id || ''} onChange={(e) => set({ elevenlabs_voice_id: e.target.value })}>
                  {voixEleven.map((v) => (
                    <option key={v.voice_id} value={v.voice_id}>
                      {v.name}{v.french ? ' · fr' : ''}{v.accent ? ` (${v.accent})` : ''}{v.paid_only ? ' — abonnement payant requis' : ''}
                    </option>
                  ))}
                  {draft.elevenlabs_voice_id && !voixEleven.some((v) => v.voice_id === draft.elevenlabs_voice_id) ? (
                    <option value={draft.elevenlabs_voice_id}>{draft.elevenlabs_voice_id}</option>
                  ) : null}
                </select>
              </Field>
              <Field label="Modèle de voix" hint="Flash v2.5 donne la réponse la plus rapide.">
                <select className="select" value={draft.elevenlabs_model || ''} onChange={(e) => set({ elevenlabs_model: e.target.value })}>
                  {modelesEleven.map((m) => (
                    <option key={m.id} value={m.id}>{m.label}</option>
                  ))}
                  {draft.elevenlabs_model && !modelesEleven.some((m) => m.id === draft.elevenlabs_model) ? (
                    <option value={draft.elevenlabs_model}>{draft.elevenlabs_model}</option>
                  ) : null}
                </select>
              </Field>
              <div className="row">
                <button type="button" className="btn sm" onClick={ecouterEleven} title="Lit une phrase avec la voix et le modèle choisis.">Écouter la voix</button>
              </div>
            </>
          ) : null}
        </div>

        {/* ------------------------------------------------------------ raccourcis */}
        <h3 className="section-sous">Raccourcis</h3>
        <div className="carte col" style={{ gap: 10 }}>
          <div className="small muted">Raccourcis clavier globaux : ils fonctionnent même quand IRIS est en arrière-plan.</div>
          <div className="row between"><span>Parler</span><span className="small"><kbd>Ctrl</kbd>+<kbd>Maj</kbd>+<kbd>Espace</kbd></span></div>
          <div className="row between"><span>Micro muet</span><span className="small"><kbd>Ctrl</kbd>+<kbd>Maj</kbd>+<kbd>M</kbd></span></div>
          <div className="row between"><span>Stop</span><span className="small"><kbd>Ctrl</kbd>+<kbd>Maj</kbd>+<kbd>S</kbd></span></div>
          <div className="row between"><span>Afficher IRIS</span><span className="small"><kbd>Ctrl</kbd>+<kbd>Maj</kbd>+<kbd>I</kbd></span></div>
        </div>
      </div>
    </div>
  )
}
