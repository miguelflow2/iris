import React, { useEffect, useState } from 'react'
import { Ring } from '../components/Ring'
import { Toggle } from '../components/ui'
import { api } from '../lib/api'
import { useStore } from '../lib/store'

export function Onboarding(): JSX.Element {
  const { settings, updateSettings, consent, setConsent, refreshAgents, refreshStatus, toast, voice } = useStore()
  const [step, setStep] = useState(0)
  const [name, setName] = useState(settings?.user_name || '')
  const [wake, setWake] = useState(settings?.wake_word || 'Dis-moi Iris')
  const [key, setKey] = useState('')
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<string | null>(null)
  const [downloading, setDownloading] = useState(false)

  const steps = ['Bienvenue', 'OpenRouter', 'Consentement', 'Audio', 'Voix']
  const [devices, setDevices] = useState<{ devices: string[]; outputs: string[] }>({ devices: [], outputs: [] })
  useEffect(() => {
    api.get('/api/voice/devices').then(setDevices).catch(() => undefined)
  }, [])
  const isHandsFree = (n: string) => /hands-free|mains libres/i.test(n)

  const connectClaude = async () => {
    setTesting(true)
    setTestResult(null)
    try {
      await api.put('/api/agents/openrouter', { active: true, api_key: key.trim() })
      const res = await api.post('/api/agents/openrouter/test')
      setTestResult(res.message)
      await refreshAgents()
      await refreshStatus()
      if (res.ok) setKey('')
    } catch (err) {
      setTestResult(String((err as Error).message))
    } finally {
      setTesting(false)
    }
  }

  const finish = async () => {
    await updateSettings({ onboarded: true, user_name: name, wake_word: wake })
    toast(`IRIS est prête. Dites « ${wake} » pour commencer.`, 'success')
  }

  return (
    <div className="overlay">
      <div className="modal" style={{ width: 'min(620px, 92vw)' }}>
        <div className="steps">{steps.map((s, i) => <span key={s} className={i <= step ? 'done' : ''} />)}</div>
        {step === 0 ? (
          <>
            <div className="row" style={{ marginBottom: 12 }}><Ring /><h3 style={{ margin: 0 }}>Bienvenue dans IRIS</h3></div>
            {/* Première phrase du produit : bénéfice concret, aucun jargon, promesse vérifiable (cf. docs/DIFFERENCIATION.md §3.A). */}
            <p>IRIS est une assistante vocale : elle fait travailler votre ordinateur à votre place, retient ce qui compte pour vous, et vous laisse <strong>vérifier vous-même</strong> ce qu’elle a capté et ce qu’elle a envoyé. Rien ne sort de cet ordinateur sans votre accord.</p>
            {/* Triade de marque conservée, dans sa forme en français clair du README. */}
            <p className="small muted"><strong>Vois. Souviens-toi. Fais.</strong></p>
            <label className="field"><span>Comment devons-nous vous appeler ?</span><input className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="Votre prénom" /></label>
            <div className="actions"><button className="btn primary" onClick={() => setStep(1)}>Commencer</button></div>
          </>
        ) : null}
        {step === 1 ? (
          <>
            <h3>Connecter OpenRouter</h3>
            {/* On dit d’abord pourquoi la clé est demandée, avant de nommer le fournisseur. « Coffre du système » : keyring avec repli fichier chiffré (main.py). */}
            <p className="small muted">IRIS a besoin d’une intelligence pour comprendre vos demandes. Collez votre clé OpenRouter : elle donne accès à des centaines de modèles, gratuits par défaut. La clé est rangée dans le coffre du système et n’est jamais affichée.</p>
            <label className="field"><span>Clé API OpenRouter</span><input className="input mono" type="password" placeholder="sk-or-v1-…" value={key} onChange={(e) => setKey(e.target.value)} /></label>
            <div className="row" style={{ marginTop: 10 }}>
              <button className="btn primary sm" disabled={!key.trim() || testing} onClick={connectClaude}>{testing ? 'Vérification…' : 'Connecter et tester'}</button>
              <button className="btn ghost sm" onClick={() => window.iris.openExternal('https://openrouter.ai/keys')}>Obtenir une clé ↗</button>
              {testResult ? <span className="small">{testResult}</span> : null}
            </div>
            <p className="small muted" style={{ marginTop: 14 }}>Vous pourrez ajouter Claude, GPT, Gemini ou un moteur local plus tard dans Réglages › Moteurs IA.</p>
            <div className="actions"><button className="btn" onClick={() => setStep(0)}>Retour</button><button className="btn primary" onClick={() => setStep(2)}>Continuer</button></div>
          </>
        ) : null}
        {step === 2 ? (
          <>
            <h3>Ce qui peut quitter votre ordinateur</h3>
            <p className="small muted">Par défaut, rien n’est envoyé. Pour qu’une IA externe réponde, elle doit recevoir le texte de vos demandes. Vous décidez, type par type, et pouvez changer d’avis à tout moment.</p>
            {Object.entries(consent).map(([k, c]: [string, any]) => (
              <div key={k} className="row between" style={{ padding: '8px 0', borderBottom: '1px solid var(--border)' }}>
                <div><div>{c.label}</div><div className="small muted">{c.description}</div></div>
                <Toggle on={Boolean(c.granted)} onChange={(v) => setConsent(k, v)} />
              </div>
            ))}
            <div className="actions"><button className="btn" onClick={() => setStep(1)}>Retour</button><button className="btn primary" onClick={() => setStep(3)}>Continuer</button></div>
          </>
        ) : null}
        {step === 3 ? (
          <>
            <h3>Micro et sortie audio</h3>
            <p className="small muted">Choisissez comment IRIS vous entend et où elle parle. Le micro « Hands-Free » d’un casque ou de lunettes Bluetooth est en qualité téléphone (8 kHz) : la reconnaissance y est bien moins fiable que sur le micro de l’ordinateur.</p>
            <label className="field"><span>Micro</span>
              <select className="select" value={settings?.audio_input_device || ''} onChange={(e) => api.patch('/api/glasses/prefs', { audio_input_device: e.target.value }).catch((err) => toast(err.message, 'error'))}>
                <option value="">Micro par défaut de l’ordinateur (recommandé)</option>
                {devices.devices.map((d) => <option key={d} value={d}>{d}{isHandsFree(d) ? ' — qualité téléphone' : ''}</option>)}
              </select>
            </label>
            <label className="field" style={{ marginTop: 10 }}><span>Sortie audio (voix d’IRIS)</span>
              <select className="select" value={settings?.audio_output_device || ''} onChange={(e) => api.patch('/api/glasses/prefs', { audio_output_device: e.target.value }).catch((err) => toast(err.message, 'error'))}>
                <option value="">Sortie par défaut du système</option>
                {devices.outputs.map((d) => <option key={d} value={d}>{d}</option>)}
              </select>
            </label>
            <p className="small muted" style={{ marginTop: 10 }}>Conseil lunettes VELA : gardez le micro du PC et choisissez la sortie « Stereo » des lunettes pour entendre IRIS dedans. Modifiable à tout moment dans « Lunettes ».</p>
            <div className="actions"><button className="btn" onClick={() => setStep(2)}>Retour</button><button className="btn primary" onClick={() => setStep(4)}>Continuer</button></div>
          </>
        ) : null}
        {step === 4 ? (
          <>
            <h3>Votre mot d’activation</h3>
            <label className="field"><span>Dites-le suivi de votre demande</span><input className="input" value={wake} onChange={(e) => setWake(e.target.value)} /></label>
            <p className="small muted" style={{ marginTop: 10 }}>Exemple : « {wake}, ouvre mon navigateur et mets de la musique ». IRIS répond en moins de 5 secondes et vous pose une question si elle a besoin d’une précision.</p>
            <div className="row between" style={{ padding: '8px 0', borderTop: '1px solid var(--border)', marginTop: 8 }}>
              <div><div>Reconnaissance vocale hors-ligne</div><div className="small muted">{voice?.model_ready ? 'Modèle installé — tout reste sur l’appareil.' : `Téléchargez le modèle (${voice?.model_info?.size_mb} Mo) pour une écoute 100 % locale.`}</div></div>
              {voice?.model_ready ? <span className="pill ok">installé</span> : <button className="btn sm" disabled={downloading} onClick={() => { setDownloading(true); api.post('/api/voice/model/download', {}).catch((e) => toast(e.message, 'error')) }}>{downloading ? 'Téléchargement…' : 'Télécharger'}</button>}
            </div>
            <div className="actions"><button className="btn" onClick={() => setStep(3)}>Retour</button><button className="btn primary" onClick={finish}>Terminer</button></div>
          </>
        ) : null}
      </div>
    </div>
  )
}
