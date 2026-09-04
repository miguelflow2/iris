import React, { useEffect, useState } from 'react'
import { Field, SettingRow, Toggle } from '../components/ui'
import { api, type IrisEvent } from '../lib/api'
import { useStore } from '../lib/store'

export function SettingsView(): JSX.Element {
  const [remote, setRemote] = useState<any>(null)
  const { settings, updateSettings, voice, toast, appInfo, status } = useStore()
  const [voices, setVoices] = useState<any[]>([])
  const [eleven, setEleven] = useState<any>(null)
  const [elevenKey, setElevenKey] = useState('')
  const [progress, setProgress] = useState<{ done: number; total: number } | null>(null)
  const [draft, setDraft] = useState<any>(settings)
  const [sites, setSites] = useState<any[]>([])
  const [siteForm, setSiteForm] = useState({ name: '', url: '', username: '', password: '' })
  // Calibration en cours : tant qu'elle tourne, IRIS enregistre comme variante toute phrase
  // entendue. Il faut donc pouvoir l'arrêter, et voir qu'elle tourne.
  const [calibRestant, setCalibRestant] = useState(0)
  const loadSites = () => api.get('/api/sites').then((r) => setSites(r.sites)).catch(() => undefined)

  useEffect(() => setDraft(settings), [settings])
  useEffect(() => { api.get('/api/remote').then(setRemote).catch(() => undefined) }, [settings?.remote_access])

  useEffect(() => {
    api.get('/api/voice/voices').then((r) => setVoices(r.voices)).catch(() => undefined)
    api.get('/api/voice/elevenlabs').then(setEleven).catch(() => undefined)
    loadSites()
    return api.on((e: IrisEvent) => {
      if (e.type === 'voice.model_progress') setProgress({ done: e.done, total: e.total })
      if (e.type === 'voice.model_ready') setProgress(null)
      if (e.type === 'voice.calibration') setCalibRestant(e.active ? Number(e.remaining) || 0 : 0)
    })
  }, [])

  if (!draft) return <div className="page" />
  const set = (patch: Record<string, unknown>) => updateSettings(patch).catch((err) => toast(String(err.message), 'error'))
  const commit = (key: string) => {
    if (draft[key] !== settings[key]) set({ [key]: draft[key] })
  }

  return (
    <div className="page">
      <h1>Paramètres</h1>
      <p className="lead">Personnalisez IRIS : mot d’activation, voix, contrôle de l’ordinateur, stockage.</p>

      <h2>Identité</h2>
      <div className="card grid-2">
        <Field label="Votre prénom" hint="Utilisé par l’IA pour s’adresser à vous.">
          <input className="input" value={draft.user_name} onChange={(e) => setDraft({ ...draft, user_name: e.target.value })} onBlur={() => commit('user_name')} />
        </Field>
        <Field label="Nom de l’assistante">
          <input className="input" value={draft.assistant_name} onChange={(e) => setDraft({ ...draft, assistant_name: e.target.value })} onBlur={() => commit('assistant_name')} />
        </Field>
      </div>
      {/* La présence a quitté le pied de la barre latérale (qui porte maintenant le mot
          d’activation) : c’est ici qu’on peut la lire en entier. */}
      {status?.presence ? (
        <p className="small muted" style={{ marginTop: 8 }}>
          Cet ordinateur : {status.presence.device_name}
          {status.presence.installed_days >= 1
            ? ` · installée depuis ${status.presence.installed_days} jour${status.presence.installed_days > 1 ? 's' : ''}`
            : ' · installée aujourd’hui'}
          {` · ${status.presence.sessions} démarrage${status.presence.sessions > 1 ? 's' : ''}`}
          {status.presence.last_interaction_ago ? ` · dernier échange ${status.presence.last_interaction_ago}` : ''}
        </p>
      ) : null}

      <h2>Voix et mot d’activation</h2>
      <div className="card">
        <div className="grid-2">
          <Field label="Mot d’activation" hint="Dites-le suivi de votre demande, ex. « Dis-moi Iris, ouvre mon navigateur ».">
            <input className="input" value={draft.wake_word} onChange={(e) => setDraft({ ...draft, wake_word: e.target.value })} onBlur={() => commit('wake_word')} />
          </Field>
          <Field label="Langue">
            <select className="select" value={draft.language} onChange={(e) => set({ language: e.target.value })}>
              <option value="fr-CA">Français (Canada)</option>
              <option value="fr-FR">Français (France)</option>
              <option value="en-US">English (US)</option>
            </select>
          </Field>
        </div>
        <Field label="Variantes acceptées du mot d’activation" hint="Séparées par des virgules. Si IRIS n’entend pas votre mot, ajoutez ici ce qu’elle affiche dans « Entendu : … ».">
          <input
            className="input"
            value={Array.isArray(draft.wake_aliases) ? draft.wake_aliases.join(', ') : ''}
            onChange={(e) => setDraft({ ...draft, wake_aliases: e.target.value.split(',').map((s: string) => s.trim()).filter(Boolean) })}
            onBlur={() => set({ wake_aliases: draft.wake_aliases })}
          />
        </Field>
        <Field label="Mots d’arrêt (coupent la parole d’IRIS)" hint="Séparés par des virgules. IRIS écoute pendant qu’elle parle : « stop » l’interrompt immédiatement.">
          <input className="input" value={Array.isArray(draft.stop_words) ? draft.stop_words.join(', ') : ''} onChange={(e) => setDraft({ ...draft, stop_words: e.target.value.split(',').map((s: string) => s.trim()).filter(Boolean) })} onBlur={() => set({ stop_words: draft.stop_words })} />
        </Field>
        <Field label="Mots pour couper le micro" hint="Ex. « muet » : IRIS dit « Micro coupé » puis n’écoute plus jusqu’à réactivation (bouton, Ctrl+Maj+M, barre système).">
          <input className="input" value={Array.isArray(draft.mute_words) ? draft.mute_words.join(', ') : ''} onChange={(e) => setDraft({ ...draft, mute_words: e.target.value.split(',').map((s: string) => s.trim()).filter(Boolean) })} onBlur={() => set({ mute_words: draft.mute_words })} />
        </Field>
        <SettingRow
          title="Calibrer le mot d’activation sur votre voix"
          desc={calibRestant > 0
            ? `Calibration en cours : ${calibRestant} répétition${calibRestant > 1 ? 's' : ''} attendue${calibRestant > 1 ? 's' : ''}. Tant qu’elle dure, chaque phrase entendue peut devenir une variante — arrêtez-la si vous parlez d’autre chose.`
            : "Dites votre mot d’activation 3 fois : IRIS apprend ce que la reconnaissance entend réellement et l’ajoute aux variantes acceptées."}
        >
          {calibRestant > 0 ? (
            <button className="btn sm danger" onClick={() => api.post('/api/voice/calibrate', { count: 0 }).then(() => { setCalibRestant(0); toast('Calibration arrêtée.', 'info') }).catch((e) => toast(e.message, 'error'))}>Arrêter la calibration</button>
          ) : (
            <button className="btn sm" onClick={() => api.post('/api/voice/calibrate', { count: 3 }).then((r) => toast(r.error || 'Dites le mot d’activation, 3 fois, en marquant une pause.', r.error ? 'error' : 'info')).catch((e) => toast(e.message, 'error'))}>Calibrer (3 répétitions)</button>
          )}
        </SettingRow>
        <SettingRow title="Reconnaissance vocale hors-ligne (Vosk)" desc={voice?.model_ready ? `Modèle installé : ${voice.model_info?.label}. Tout est traité sur l’appareil.` : `Modèle absent : ${voice?.model_info?.label || ''}. Sans lui, la voix nécessite la reconnaissance cloud (consentement « audio brut »).`}>
          {voice?.model_ready ? <span className="pill ok">installé</span> : progress ? (
            <div style={{ width: 180 }}>
              <div className="progress"><div style={{ width: `${progress.total ? Math.round((progress.done / progress.total) * 100) : 30}%` }} /></div>
              <div className="small muted">{Math.round(progress.done / 1e6)} Mo{progress.total ? ` / ${Math.round(progress.total / 1e6)} Mo` : ''}</div>
            </div>
          ) : (
            <button className="btn primary sm" onClick={() => api.post('/api/voice/model/download', {}).then(() => setProgress({ done: 0, total: 0 })).catch((e) => toast(e.message, 'error'))}>Télécharger le modèle</button>
          )}
        </SettingRow>
        <SettingRow title="Moteur de reconnaissance">
          <select className="select" style={{ width: 220 }} value={draft.stt_engine} onChange={(e) => set({ stt_engine: e.target.value })}>
            <option value="auto">Automatique (hors-ligne si possible)</option>
            <option value="vosk">Hors-ligne uniquement (Vosk)</option>
            <option value="google">Cloud (Google, avec consentement)</option>
          </select>
        </SettingRow>
        <SettingRow title="Démarrer l’écoute avec IRIS" desc="Le micro s’active au lancement (l’indicateur reste visible).">
          <Toggle on={draft.voice_autostart} onChange={(v) => set({ voice_autostart: v })} />
        </SettingRow>
        <SettingRow title="Accusé vocal (« Oui ? »)" desc="Quand le mot d’activation est dit seul, sans commande.">
          <Toggle on={draft.voice_ack} onChange={(v) => set({ voice_ack: v })} />
        </SettingRow>
        <SettingRow title="Dialogue de suivi" desc="Si IRIS pose une question, elle écoute la réponse sans mot d’activation.">
          <Toggle on={draft.voice_followup} onChange={(v) => set({ voice_followup: v })} />
        </SettingRow>
        <SettingRow title="Rapidité des réponses vocales" desc="Effort de raisonnement pour la voix. « Rapide » vise une réponse en moins de 5 secondes.">
          <select className="select" style={{ width: 180 }} value={draft.voice_effort} onChange={(e) => set({ voice_effort: e.target.value })}>
            <option value="low">Rapide</option>
            <option value="medium">Équilibré</option>
            <option value="high">Approfondi</option>
          </select>
        </SettingRow>
        <SettingRow title="Modèle dédié à la voix" desc="Vide = même modèle que l’agent. Indiquez un identifiant du fournisseur choisi (ex. minimax/minimax-m3:free sur OpenRouter, claude-sonnet-5 chez Anthropic).">
          <input className="input mono" style={{ width: 220 }} placeholder="ex. minimax/minimax-m3:free" value={draft.voice_model} onChange={(e) => setDraft({ ...draft, voice_model: e.target.value })} onBlur={() => commit('voice_model')} />
        </SettingRow>
        <SettingRow title="Lecture vocale des réponses" desc="Les réponses sont lues phrase par phrase pendant qu’elles arrivent (streaming).">
          <Toggle on={draft.tts_enabled} onChange={(v) => set({ tts_enabled: v })} />
        </SettingRow>
        <SettingRow title="Moteur de voix" desc={eleven ? `En cours : ${eleven.engine_in_use === 'elevenlabs' ? 'ElevenLabs (voix française naturelle)' : 'voix Windows'}${eleven.error ? ' · ' + eleven.error : ''}` : ''}>
          <select className="select" style={{ width: 260 }} value={draft.tts_engine} onChange={(e) => set({ tts_engine: e.target.value })}>
            <option value="auto">Automatique (ElevenLabs si configuré)</option>
            <option value="elevenlabs">ElevenLabs</option>
            <option value="windows">Voix Windows (hors-ligne)</option>
          </select>
        </SettingRow>
        <SettingRow title="Clé API ElevenLabs" desc={eleven?.configured ? `Clé chargée depuis le fichier .env (${eleven.env_file}).${eleven.subscription?.limit ? ` Quota : ${eleven.subscription.used} / ${eleven.subscription.limit} caractères ce mois-ci (palier ${eleven.subscription.tier}).` : ''}` : 'Aucune clé : ajoutez-la ici, elle sera écrite dans le fichier .env du dossier de données, jamais dans le code.'}>
          <input className="input mono" type="password" style={{ width: 220 }} placeholder={eleven?.configured ? '•••••• (remplacer)' : 'sk_…'} value={elevenKey} onChange={(e) => setElevenKey(e.target.value)} />
          <button className="btn sm" disabled={!elevenKey.trim()} onClick={() => api.post('/api/voice/elevenlabs/key', { api_key: elevenKey.trim() }).then(() => { setElevenKey(''); return api.get('/api/voice/elevenlabs?refresh=true') }).then(setEleven).then(() => toast('Clé ElevenLabs enregistrée dans .env', 'success')).catch((e) => toast(e.message, 'error'))}>Enregistrer</button>
        </SettingRow>
        {eleven?.configured ? (
          <>
            <SettingRow title="Voix ElevenLabs" desc="Les voix marquées « fr » parlent nativement français. Au palier gratuit, seules les voix de base sont utilisables : Sarah (fr) est recommandée ; les voix de bibliothèque comme Mélanie exigent un abonnement.">
              <select className="select" style={{ width: 300 }} value={draft.elevenlabs_voice_id} onChange={(e) => set({ elevenlabs_voice_id: e.target.value })}>
                {(eleven.voices || []).map((v: any) => (
                  <option key={v.voice_id} value={v.voice_id}>{v.name}{v.french ? ' · fr' : ''}{v.accent ? ` (${v.accent})` : ''}{v.paid_only ? ' — abonnement payant requis' : ''}</option>
                ))}
                {!(eleven.voices || []).some((v: any) => v.voice_id === draft.elevenlabs_voice_id) && draft.elevenlabs_voice_id ? <option value={draft.elevenlabs_voice_id}>{draft.elevenlabs_voice_id}</option> : null}
              </select>
            </SettingRow>
            <SettingRow title="Modèle ElevenLabs" desc="Flash v2.5 donne la réponse la plus rapide.">
              <select className="select" style={{ width: 300 }} value={draft.elevenlabs_model} onChange={(e) => set({ elevenlabs_model: e.target.value })}>
                {(eleven.models || []).map((m: any) => (
                  <option key={m.id} value={m.id}>{m.label}</option>
                ))}
              </select>
              <button className="btn sm" onClick={() => api.post('/api/voice/elevenlabs/test').then((r) => { if (r.error) toast(r.error, 'error') }).catch((e) => toast(e.message, 'error'))} title="Lit une phrase avec la voix et le modèle ElevenLabs choisis.">Écouter la voix ElevenLabs</button>
            </SettingRow>
          </>
        ) : null}
        <SettingRow title="Voix Windows (repli hors-ligne)" desc={voices.length ? `${voices.length} voix disponible${voices.length > 1 ? 's' : ''}. Pour une voix française, installez « Microsoft Hortense » ou « Caroline » dans Windows › Heure et langue › Voix.` : 'Aucune voix détectée.'}>
          <select className="select" style={{ width: 260 }} value={draft.tts_voice} onChange={(e) => set({ tts_voice: e.target.value })}>
            <option value="">Automatique</option>
            {voices.map((v) => (
              <option key={v.id} value={v.id}>{v.name}</option>
            ))}
          </select>
        </SettingRow>
        <SettingRow title="Débit de parole">
          <input type="range" min={120} max={260} value={draft.tts_rate} onChange={(e) => setDraft({ ...draft, tts_rate: Number(e.target.value) })} onMouseUp={() => commit('tts_rate')} />
          <span className="small muted">{draft.tts_rate}</span>
          <button className="btn sm" onClick={() => api.post('/api/voice/say', { text: `Bonjour, je suis ${draft.assistant_name}. Dites ${draft.wake_word} pour me parler.` })} title="Lit une phrase d’exemple avec la voix et le débit actuels.">Écouter un exemple</button>
        </SettingRow>
        <SettingRow title="Raccourcis clavier globaux" desc="Fonctionnent même quand IRIS est en arrière-plan.">
          <span className="small"><kbd>Ctrl</kbd>+<kbd>Maj</kbd>+<kbd>Espace</kbd> parler · <kbd>Ctrl</kbd>+<kbd>Maj</kbd>+<kbd>M</kbd> micro muet · <kbd>Ctrl</kbd>+<kbd>Maj</kbd>+<kbd>S</kbd> stop · <kbd>Ctrl</kbd>+<kbd>Maj</kbd>+<kbd>I</kbd> afficher IRIS</span>
        </SettingRow>
      </div>

      <h2>Contrôle de l’ordinateur</h2>
      <div className="card">
        <SettingRow title="Confirmation avant une commande" desc="IRIS n’agit que sur votre demande. Les commandes dangereuses (suppression, arrêt, droits…) demandent toujours confirmation en mode « dangereuses »." >
          <select className="select" style={{ width: 240 }} value={draft.confirm_commands} onChange={(e) => set({ confirm_commands: e.target.value })}>
            <option value="dangerous">Seulement les commandes dangereuses</option>
            <option value="always">Toujours</option>
            <option value="never">Jamais (fluidité maximale)</option>
          </select>
        </SettingRow>
        <SettingRow title="Contrôle complet de l’écran" desc="Souris, capture d’écran et lecture du texte à l’écran (OCR hors-ligne) : IRIS peut agir dans n’importe quelle application ou jeu. Dites par exemple « clique sur Jouer » ou « dans le jeu, appuie sur Entrée ».">
          <Toggle on={Boolean(draft.computer_use)} onChange={(v) => set({ computer_use: v })} />
        </SettingRow>
        <SettingRow title="Modèle de raisonnement" desc="Pour la création (jeux, sites, apps) et les tâches longues. Vide = modèle de l’agent. Un modèle payant (ex. anthropic/claude-sonnet-5 via OpenRouter) améliore nettement la qualité des plans.">
          <input className="input mono" style={{ width: 260 }} placeholder="ex. anthropic/claude-sonnet-5" value={draft.reasoning_model || ''} onChange={(e) => setDraft({ ...draft, reasoning_model: e.target.value })} onBlur={() => commit('reasoning_model')} />
        </SettingRow>
        <SettingRow title="Modèle vision (écran)" desc="Doit accepter les images. Gratuits : minimax/minimax-m3:free, google/gemma-4-31b-it:free. Vide = modèle de l’agent.">
          <input className="input mono" style={{ width: 260 }} placeholder="ex. google/gemma-4-31b-it:free" value={draft.vision_model || ''} onChange={(e) => setDraft({ ...draft, vision_model: e.target.value })} onBlur={() => commit('vision_model')} />
        </SettingRow>
        <SettingRow title="Recherche web par Claude" desc="Claude peut consulter le web côté serveur Anthropic pour répondre à jour (les requêtes de recherche transitent par Anthropic).">
          <Toggle on={draft.claude_web_search} onChange={(v) => set({ claude_web_search: v })} />
        </SettingRow>
        <SettingRow title="Effort de raisonnement (texte)" desc="Pour les conversations écrites.">
          <select className="select" style={{ width: 180 }} value={draft.claude_effort} onChange={(e) => set({ claude_effort: e.target.value })}>
            <option value="low">Rapide</option>
            <option value="medium">Équilibré</option>
            <option value="high">Approfondi</option>
          </select>
        </SettingRow>
        <SettingRow title="Afficher le raisonnement de Claude" desc="Résumé de la réflexion, déroulable sous chaque réponse écrite.">
          <Toggle on={draft.claude_thinking_display} onChange={(v) => set({ claude_thinking_display: v })} />
        </SettingRow>
        <SettingRow title="Messages renvoyés à l’IA" desc="Fenêtre d’historique par conversation.">
          <input type="number" className="input" style={{ width: 90 }} min={2} max={200} value={draft.history_window} onChange={(e) => setDraft({ ...draft, history_window: Number(e.target.value) })} onBlur={() => commit('history_window')} />
        </SettingRow>
      </div>

      <h2>Comptes web</h2>
      <div className="card col">
        <p className="small muted" style={{ margin: 0 }}>IRIS peut se connecter à vos sites (Omnivox, portails, intranets) et y naviguer à la voix : « Dis-moi Iris, connecte-toi à Omnivox et montre mes notes ». Le mot de passe est stocké dans le coffre Windows et rempli par IRIS elle-même : l’IA ne le voit jamais. Si le site affiche un contrôle de sécurité (captcha), résolvez-le dans la fenêtre du navigateur qu’IRIS ouvre ; la session est ensuite mémorisée.</p>
        <div className="grid-2">
          <Field label="Nom court (ex. omnivox)"><input className="input" value={siteForm.name} onChange={(e) => setSiteForm({ ...siteForm, name: e.target.value })} /></Field>
          <Field label="Adresse de la page de connexion"><input className="input mono" placeholder="https://…/Login" value={siteForm.url} onChange={(e) => setSiteForm({ ...siteForm, url: e.target.value })} /></Field>
          <Field label="Identifiant (matricule, courriel…)"><input className="input" value={siteForm.username} onChange={(e) => setSiteForm({ ...siteForm, username: e.target.value })} /></Field>
          <Field label="Mot de passe" hint="Saisi par vous, jamais affiché ni envoyé à l’IA."><input className="input" type="password" autoComplete="new-password" value={siteForm.password} onChange={(e) => setSiteForm({ ...siteForm, password: e.target.value })} /></Field>
        </div>
        <div className="row">
          <button className="btn primary sm" disabled={!siteForm.name.trim() || !siteForm.url.trim()} onClick={() => api.put(`/api/sites/${encodeURIComponent(siteForm.name.trim().toLowerCase())}`, { url: siteForm.url.trim(), username: siteForm.username.trim(), password: siteForm.password || undefined }).then(() => { setSiteForm({ name: '', url: '', username: '', password: '' }); loadSites(); toast('Compte enregistré dans le coffre.', 'success') }).catch((e) => toast(e.message, 'error'))}>Enregistrer le compte</button>
        </div>
        {sites.map((s) => (
          <div className="row between" key={s.name} style={{ borderTop: '1px solid var(--border)', paddingTop: 8 }}>
            <div>
              <div><strong>{s.label || s.name}</strong> <span className="small muted mono">{s.url}</span></div>
              <div className="small muted">Identifiant : {s.username || '—'} · {s.has_password ? 'mot de passe enregistré' : 'mot de passe manquant'}{s.profile ? ` · profil ${s.profile}` : ''}</div>
            </div>
            <div className="row">
              <button className="btn sm" onClick={() => api.post(`/api/sites/${s.name}/login`).then((r) => toast(r.status === 'logged_in' || r.status === 'already_logged_in' ? `Connecté à ${s.name}.` : `Connexion non confirmée (${r.status}).`, r.status.includes('logged_in') ? 'success' : 'error')).catch((e) => toast(e.message, 'error'))}>Tester la connexion</button>
              <button className="btn ghost sm" onClick={() => api.delete(`/api/sites/${s.name}`).then(loadSites)}>×</button>
            </div>
          </div>
        ))}
      </div>

      <h2>Mémoire</h2>
      <div className="card">
        <SettingRow title="Résumé automatique de la journée" desc="Chaque soir, IRIS résume décisions, promesses, chiffres et idées de la journée dans la mémoire.">
          <input className="input" style={{ width: 90 }} type="time" value={draft.daily_summary_time || '21:00'} onChange={(e) => set({ daily_summary_time: e.target.value })} />
          <Toggle on={Boolean(draft.daily_summary_enabled)} onChange={(v) => set({ daily_summary_enabled: v })} />
        </SettingRow>
      </div>
      <h2>Téléphone</h2>
      <div className="card col">
        <div className="row between wrap">
          <div style={{ maxWidth: 520 }}>
            <strong>Parler à IRIS depuis mon téléphone</strong>
            <div className="small muted">
              Ouvre IRIS aux appareils de votre réseau WiFi. Vos lunettes se connectent au téléphone,
              le téléphone parle à cet ordinateur : vous commandez IRIS même en étant ailleurs dans la maison.
            </div>
          </div>
          <label className="switch">
            <input
              type="checkbox"
              checked={Boolean(settings?.remote_access)}
              onChange={async (e) => {
                await updateSettings({ remote_access: e.target.checked })
                toast(e.target.checked
                  ? 'Accès téléphone activé. Redémarrez IRIS pour qu’il prenne effet.'
                  : 'Accès téléphone désactivé.', 'success')
                api.get('/api/remote').then(setRemote).catch(() => undefined)
              }}
            />
            <span />
          </label>
        </div>

        {settings?.remote_access ? (
          <>
            <div className="small" style={{ color: 'var(--warn)' }}>
              IRIS exécute des commandes sur cet ordinateur. N’activez ceci que sur un réseau de confiance,
              et <strong>n’ouvrez jamais de port sur votre routeur</strong> : pour y accéder de l’extérieur,
              il faut un tunnel privé.
            </div>
            {remote?.urls?.length ? (
              <div className="col" style={{ gap: 6 }}>
                <div className="small muted">Ouvrez cette adresse dans le navigateur de votre téléphone :</div>
                {remote.urls.map((u: any) => (
                  <div className="row between" key={u.ip}>
                    <code className="mono small" style={{ wordBreak: 'break-all' }}>{u.url}</code>
                    <button className="btn sm" onClick={() => { navigator.clipboard?.writeText(u.url); toast('Adresse copiée.', 'success') }}>Copier</button>
                  </div>
                ))}
                <div className="small muted">Le téléphone doit être sur le même WiFi. L’adresse contient votre jeton : ne la partagez pas.</div>
              </div>
            ) : (
              <div className="small muted">Redémarrez IRIS pour que l’accès réseau prenne effet.</div>
            )}
          </>
        ) : null}
      </div>



      <h2>Stockage</h2>
      <div className="card">
        <SettingRow title="Dossier de données" desc={status?.data_dir || ''}>
          <button className="btn sm" onClick={() => status?.data_dir && window.iris.openPath(status.data_dir)}>Ouvrir</button>
        </SettingRow>
        <SettingRow title="Détail technique (journal du service)" desc={appInfo?.logPath || ''}>
          <button className="btn sm" onClick={() => appInfo?.logPath && window.iris.openPath(appInfo.logPath)}>Ouvrir</button>
        </SettingRow>
        <SettingRow title="Version" desc={`IRIS ${appInfo?.version || ''} · service ${status?.version || ''} · ${status?.platform || ''}`}>
          <button className="btn ghost sm" onClick={() => set({ onboarded: false })}>Relancer l’assistant de démarrage</button>
        </SettingRow>
      </div>
    </div>
  )
}
