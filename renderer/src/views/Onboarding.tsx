import React, { useEffect, useState } from 'react'
import { Voile } from '../components/Voile'
import { Toggle } from '../components/ui'
import { api } from '../lib/api'
import { useStore } from '../lib/store'

export function Onboarding(): JSX.Element {
  const { settings, updateSettings, consent, setConsent, toast, voice } = useStore()
  const [step, setStep] = useState(0)
  const [name, setName] = useState(settings?.user_name || '')
  const [wake, setWake] = useState(settings?.wake_word || 'Dis-moi Iris')
  const [downloading, setDownloading] = useState(false)

  // Le compte du propriétaire. IRIS exécute des commandes sur cet ordinateur : on ne laisse pas
  // cet accès ouvert au premier appareil qui connaît l'adresse. Voir backend/iris/comptes.py.
  const [compte, setCompte] = useState<{ configure: boolean; nom?: string } | null>(null)
  const [email, setEmail] = useState('')
  const [mdp, setMdp] = useState('')
  const [mdp2, setMdp2] = useState('')
  const [compteErreur, setCompteErreur] = useState<string | null>(null)
  const [compteOccupe, setCompteOccupe] = useState(false)

  const steps = ['Bienvenue', 'Compte', 'Consentement', 'Audio', 'Voix']
  const [devices, setDevices] = useState<{ devices: string[]; outputs: string[] }>({ devices: [], outputs: [] })
  useEffect(() => {
    api.get('/api/voice/devices').then(setDevices).catch(() => undefined)
    api.get('/api/compte').then(setCompte).catch(() => setCompte({ configure: false }))
  }, [])
  const isHandsFree = (n: string) => /hands-free|mains libres/i.test(n)

  const validerCompte = async () => {
    setCompteErreur(null)
    setCompteOccupe(true)
    try {
      if (compte?.configure) {
        await api.post('/api/compte/connexion', { mot_de_passe: mdp })
      } else {
        if (mdp.trim().length < 8) throw new Error('Le mot de passe doit faire au moins 8 caractères.')
        if (mdp !== mdp2) throw new Error('Les deux mots de passe ne sont pas identiques.')
        await api.post('/api/compte', { nouveau: mdp, nom: name })
        // Le courriel d'achat suffit à activer l'abonnement : aucune clé à recopier.
        if (email.trim()) await updateSettings({ licence_email: email.trim(), licence_auto: true })
      }
      setMdp('')
      setMdp2('')
      setStep(2)
    } catch (err) {
      setCompteErreur(String((err as Error).message))
    } finally {
      setCompteOccupe(false)
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
            <div className="row" style={{ marginBottom: 12 }}><Voile taille={30} variante="clair" className="voile lueur" titre="VELA" /><h3 style={{ margin: 0 }}>Bienvenue dans IRIS</h3></div>
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
            <h3>{compte?.configure ? 'Connectez-vous' : 'Votre compte'}</h3>
            {compte?.configure ? (
              <p className="small muted">Un compte existe déjà sur cet ordinateur{compte.nom ? ` — ${compte.nom}` : ''}. Entrez son mot de passe pour reprendre la main.</p>
            ) : (
              <p className="small muted">IRIS ouvre vos applications, tape à votre place et lit votre écran. Ce mot de passe est ce qui protège cet accès quand vous la joignez depuis votre téléphone : sans lui, connaître l’adresse suffirait. Il ne quitte jamais cet ordinateur et n’y est jamais écrit en clair.</p>
            )}
            {!compte?.configure ? (
              <label className="field"><span>Courriel <span className="muted">(facultatif)</span></span>
                <input className="input" type="email" autoComplete="email" placeholder="vous@exemple.com" value={email} onChange={(e) => setEmail(e.target.value)} />
              </label>
            ) : null}
            {!compte?.configure ? (
              <p className="small muted" style={{ marginTop: -4 }}>Celui de votre achat VELA. Votre abonnement s’activera tout seul, sans clé à recopier.</p>
            ) : null}
            <label className="field" style={{ marginTop: 10 }}><span>Mot de passe</span>
              <input className="input" type="password" autoComplete={compte?.configure ? 'current-password' : 'new-password'}
                placeholder={compte?.configure ? '' : '8 caractères au minimum'} value={mdp}
                onChange={(e) => setMdp(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter' && compte?.configure) validerCompte() }} />
            </label>
            {!compte?.configure ? (
              <label className="field" style={{ marginTop: 10 }}><span>Répétez-le</span>
                <input className="input" type="password" autoComplete="new-password" value={mdp2}
                  onChange={(e) => setMdp2(e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter') validerCompte() }} />
              </label>
            ) : null}
            {compteErreur ? <p className="small" style={{ color: 'var(--danger)' }}>{compteErreur}</p> : null}
            {compte?.configure ? (
              <p className="small muted" style={{ marginTop: 12 }}>Oublié ? Il n’est stocké nulle part, donc introuvable. Supprimez <span className="mono">compte.json</span> dans le dossier de données d’IRIS pour repartir de zéro : cela déconnecte aussi tous vos téléphones.</p>
            ) : null}
            <div className="actions">
              <button className="btn" onClick={() => setStep(0)}>Retour</button>
              <button className="btn primary" disabled={compteOccupe || !mdp.trim()} onClick={validerCompte}>
                {compteOccupe ? 'Un instant…' : compte?.configure ? 'Se connecter' : 'Créer mon compte'}
              </button>
            </div>
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
              <div><div>Reconnaissance vocale hors-ligne</div><div className="small muted">{voice?.model_ready ? 'Installée — tout reste sur l’appareil.' : `IRIS l’installe elle-même (${voice?.model_info?.size_mb} Mo). Vous pouvez continuer, elle vous préviendra.`}</div></div>
              {voice?.model_ready ? <span className="pill ok">installé</span> : <button className="btn sm" disabled={downloading} onClick={() => { setDownloading(true); api.post('/api/voice/model/download', {}).catch((e) => toast(e.message, 'error')) }}>{downloading ? 'En cours…' : 'Relancer'}</button>}
            </div>
            <div className="actions"><button className="btn" onClick={() => setStep(3)}>Retour</button><button className="btn primary" onClick={finish}>Terminer</button></div>
          </>
        ) : null}
      </div>
    </div>
  )
}
