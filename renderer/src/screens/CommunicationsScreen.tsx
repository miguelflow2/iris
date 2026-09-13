import React, { useCallback, useEffect, useState } from 'react'
import { Field, Holo, TopBar } from '../components/ui'
import { IcoChevronBas } from '../components/icons'
import { api } from '../lib/api'
import { useStore } from '../lib/store'
import './CommunicationsScreen.css'

/* =========================================================================
   « Courriel, SMS et appels » : les anciennes sections Courriel et SMS/appels
   de l'écran Paramètres. Le mot de passe d'application Gmail et le compte
   Twilio vont dans le coffre du système ; les secrets ne reviennent jamais du
   service (routes_communications.py), donc les formulaires repartent vides
   après chaque enregistrement. Twilio est un écran avancé : le nom est permis.
   ========================================================================= */

const LIEN_MOTS_DE_PASSE_APPLICATION = 'https://myaccount.google.com/apppasswords'

function messageErreur(err: unknown): string {
  return err instanceof Error ? err.message : String(err)
}

export function CommunicationsScreen({ params: _params }: { params?: Record<string, any> }): JSX.Element {
  const { toast } = useStore()
  const [courriel, setCourriel] = useState<any>(null)
  const [courrielForm, setCourrielForm] = useState({ adresse: '', mot_de_passe_application: '' })
  const [courrielOccupe, setCourrielOccupe] = useState(false) // « Tester » peut bloquer 20 s sur un port fermé
  const [telephonie, setTelephonie] = useState<any>(null)
  const [twilioForm, setTwilioForm] = useState({ account_sid: '', auth_token: '', numero: '' })
  const [twilioOccupe, setTwilioOccupe] = useState(false)

  const chargerCourriel = useCallback(() => api.get('/api/courriel/etat').then(setCourriel).catch(() => undefined), [])
  const chargerTelephonie = useCallback(() => api.get('/api/telephonie/etat').then(setTelephonie).catch(() => undefined), [])

  useEffect(() => {
    chargerCourriel()
    chargerTelephonie()
  }, [chargerCourriel, chargerTelephonie])

  // L'adresse déjà enregistrée se remet dans le champ : on ne la retape pas pour changer un mot de passe.
  useEffect(() => {
    if (courriel?.adresse) setCourrielForm((f) => (f.adresse ? f : { ...f, adresse: courriel.adresse }))
  }, [courriel?.adresse])

  /* ---------------------------------------------------------------- courriel */
  const courrielValide = Boolean(courrielForm.adresse.trim() && courrielForm.mot_de_passe_application.trim())

  const enregistrerCourriel = (): void => {
    if (!courrielValide || courrielOccupe) return
    setCourrielOccupe(true)
    api
      .post('/api/courriel/configurer', { adresse: courrielForm.adresse.trim(), mot_de_passe_application: courrielForm.mot_de_passe_application })
      .then((etat) => {
        setCourriel(etat)
        setCourrielForm({ adresse: etat?.adresse || '', mot_de_passe_application: '' })
        toast(etat?.avertissement || `Compte ${etat?.adresse} enregistré dans le coffre.`, etat?.avertissement ? 'error' : 'success')
      })
      .catch((e) => toast(messageErreur(e), 'error'))
      .finally(() => setCourrielOccupe(false))
  }

  const testerCourriel = (): void => {
    setCourrielOccupe(true)
    api
      .post('/api/courriel/tester')
      .then((r) => toast(r?.message || 'Connexion réussie.', 'success'))
      .catch((e) => toast(messageErreur(e), 'error'))
      .finally(() => setCourrielOccupe(false))
  }

  const oublierCourriel = (): void => {
    if (!window.confirm('Oublier ce compte courriel ? IRIS ne pourra plus envoyer de courriel tant que vous ne l’aurez pas redonné.')) return
    setCourrielOccupe(true)
    api
      .delete('/api/courriel')
      .then((etat) => {
        setCourriel(etat)
        setCourrielForm({ adresse: '', mot_de_passe_application: '' })
        toast('Compte courriel oublié : IRIS ne peut plus envoyer de courriel.', 'info')
      })
      .catch((e) => toast(messageErreur(e), 'error'))
      .finally(() => setCourrielOccupe(false))
  }

  /* ---------------------------------------------------------------- SMS et appels (Twilio) */
  const twilioValide = Boolean(twilioForm.account_sid.trim() && twilioForm.auth_token.trim() && twilioForm.numero.trim())

  const enregistrerTwilio = (): void => {
    if (!twilioValide || twilioOccupe) return
    setTwilioOccupe(true)
    api
      .post('/api/telephonie/configurer', { account_sid: twilioForm.account_sid.trim(), auth_token: twilioForm.auth_token.trim(), numero: twilioForm.numero.trim() })
      .then((etat) => {
        setTelephonie(etat)
        setTwilioForm({ account_sid: '', auth_token: '', numero: '' })
        toast(`Compte Twilio enregistré (numéro ${etat?.numero_expediteur || ''}).`, 'success')
      })
      .catch((e) => toast(messageErreur(e), 'error'))
      .finally(() => setTwilioOccupe(false))
  }

  const oublierTwilio = (): void => {
    if (!window.confirm('Oublier le compte Twilio ?')) return
    setTwilioOccupe(true)
    api
      .delete('/api/telephonie')
      .then((etat) => {
        setTelephonie(etat)
        toast('Compte Twilio oublié.', 'info')
      })
      .catch((e) => toast(messageErreur(e), 'error'))
      .finally(() => setTwilioOccupe(false))
  }

  const enAttente: number = Number(telephonie?.en_attente) || 0
  const restants: number = Number(telephonie?.envois_restants_cette_heure) || 0

  return (
    <div className="ecran">
      <TopBar titre="Courriel, SMS et appels" />
      <div className="contenu">
        {/* ------------------------------------------------------------ courriel */}
        <h3 className="section-sous">Courriel</h3>
        <div className="carte col" style={{ gap: 14 }}>
          <p className="small muted" style={{ lineHeight: 1.45 }}>
            IRIS écrit et envoie des courriels à votre demande : « Dis-moi Iris, écris à Sophie que j’arrive à 14 h ». Elle vous relit le message en entier et
            n’envoie rien sans votre accord. Le mot de passe est rangé dans le coffre Windows : il n’est jamais affiché, jamais transmis à l’IA.
          </p>
          <div className="row wrap" style={{ gap: 8 }}>
            {courriel?.configure ? <span className="pill ok">compte enregistré</span> : <span className="pill warn">aucun compte</span>}
            {courriel?.adresse ? (
              <span className="small muted">
                {courriel.adresse}
                {courriel.smtp_hote ? ` · ${courriel.smtp_hote}:${courriel.smtp_port}` : ''}
              </span>
            ) : null}
            {courriel?.mode_local ? <span className="pill warn">Mode local actif : aucun courriel ne partira tant qu’il l’est.</span> : null}
          </div>
          <Field label="Adresse Gmail">
            <input
              className="input"
              type="email"
              autoComplete="off"
              placeholder="prenom@gmail.com"
              value={courrielForm.adresse}
              onChange={(e) => setCourrielForm({ ...courrielForm, adresse: e.target.value })}
            />
          </Field>
          <Field label="Mot de passe d’application" hint="16 lettres générées par Google, pas le mot de passe habituel du compte. Saisi par vous, jamais affiché.">
            <input
              className="input mono"
              type="password"
              autoComplete="new-password"
              placeholder={courriel?.configure ? '•••••••• (remplacer)' : 'xxxx xxxx xxxx xxxx'}
              value={courrielForm.mot_de_passe_application}
              onChange={(e) => setCourrielForm({ ...courrielForm, mot_de_passe_application: e.target.value })}
              onKeyDown={(e) => {
                if (e.key === 'Enter') enregistrerCourriel()
              }}
            />
          </Field>
          <div className="small muted" style={{ lineHeight: 1.45 }}>
            Pour obtenir ce mot de passe :{' '}
            <a
              href={LIEN_MOTS_DE_PASSE_APPLICATION}
              onClick={(e) => {
                e.preventDefault()
                window.iris.openExternal(LIEN_MOTS_DE_PASSE_APPLICATION)
              }}
            >
              Créer un mot de passe d’application
            </a>{' '}
            — il faut la validation en deux étapes sur le compte Google, sinon la page n’existe pas. Le mot de passe habituel du compte est refusé par Gmail depuis 2022.
          </div>
          <Holo variante="blanc" disabled={!courrielValide || courrielOccupe} onClick={enregistrerCourriel}>
            {courrielOccupe ? 'Un instant…' : 'Enregistrer'}
          </Holo>
          <div className="row wrap">
            <button
              type="button"
              className="btn sm"
              disabled={!courriel?.configure || courrielOccupe}
              onClick={testerCourriel}
              title="Se connecte au serveur d’envoi avec ces identifiants, sans envoyer le moindre message."
            >
              {courrielOccupe ? 'Test en cours…' : 'Tester la connexion'}
            </button>
            {courriel?.adresse ? (
              <button type="button" className="btn danger sm" disabled={courrielOccupe} onClick={oublierCourriel}>Oublier le compte</button>
            ) : null}
          </div>
        </div>

        {/* ------------------------------------------------------------ SMS et appels */}
        <h3 className="section-sous">SMS et appels</h3>
        <div className="carte col" style={{ gap: 14 }}>
          <p className="small muted" style={{ lineHeight: 1.45 }}>
            IRIS ne peut pas envoyer un texto depuis cet ordinateur : le téléphone ne le permet à aucun programme. Elle prépare le message, et il apparaît en haut
            de la page IRIS de votre téléphone (Mon profil › Compte et sécurité › Accès depuis le téléphone) : Messages s’ouvre déjà rempli, c’est vous qui touchez
            Envoyer. Votre correspondant voit votre vrai numéro, et rien ne part sans ce geste.
          </p>
          {telephonie ? (
            <div className="row wrap" style={{ gap: 8 }}>
              <span className="pill ok">voie active : {telephonie.voie}</span>
              <span className="pill">{enAttente ? `${enAttente} message${enAttente > 1 ? 's' : ''} en attente sur le téléphone` : 'rien en attente'}</span>
              <span className="pill">
                {restants} envoi{restants > 1 ? 's' : ''} encore possible{restants > 1 ? 's' : ''} cette heure
              </span>
              {telephonie.mode_local ? <span className="pill warn">mode local : rien ne part</span> : null}
            </div>
          ) : (
            <div className="small muted">État de la téléphonie indisponible pour l’instant.</div>
          )}
          <details className="communications">
            <summary className="small">
              <span className="chevron" aria-hidden="true">
                <IcoChevronBas />
              </span>
              <span>Configuration avancée (Twilio) — envoi automatique, optionnel, compte payant</span>
            </summary>
            <div className="col" style={{ paddingTop: 12, gap: 12 }}>
              <p className="small muted" style={{ lineHeight: 1.45 }}>
                Utile seulement pour qu’IRIS envoie un SMS toute seule, depuis un numéro loué (environ 1,15 $ US par mois, 1,7 ¢ par message) : le correspondant
                voit alors ce numéro-là, pas le vôtre. Le compte s’ouvre sur twilio.com avec une carte de crédit et une pièce d’identité ; IRIS ne peut pas le faire
                à votre place. Les identifiants vont dans le coffre Windows.
                {telephonie?.fournisseur && telephonie.fournisseur !== 'twilio'
                  ? ' Tant que le fournisseur de téléphonie reste « iphone », ce compte dort : rien ne part de l’ordinateur.'
                  : ''}
              </p>
              {telephonie?.identifiant ? (
                <div className="small muted">
                  Compte enregistré : {telephonie.identifiant} · numéro {telephonie.numero_expediteur}
                </div>
              ) : null}
              <Field label="Identifiant de compte (« Account SID » dans la console Twilio)" hint="Commence par AC, 34 caractères.">
                <input className="input mono" autoComplete="off" placeholder="AC…" value={twilioForm.account_sid} onChange={(e) => setTwilioForm({ ...twilioForm, account_sid: e.target.value })} />
              </Field>
              <Field label="Jeton d’authentification (« Auth Token »)" hint="Saisi par vous, jamais affiché.">
                <input className="input mono" type="password" autoComplete="new-password" value={twilioForm.auth_token} onChange={(e) => setTwilioForm({ ...twilioForm, auth_token: e.target.value })} />
              </Field>
              <Field label="Numéro loué" hint="Au format +1 suivi de dix chiffres.">
                <input
                  className="input mono"
                  placeholder="+1 514 555 0100"
                  value={twilioForm.numero}
                  onChange={(e) => setTwilioForm({ ...twilioForm, numero: e.target.value })}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') enregistrerTwilio()
                  }}
                />
              </Field>
              <div className="row wrap">
                <button type="button" className="btn primary sm" disabled={!twilioValide || twilioOccupe} onClick={enregistrerTwilio}>
                  {twilioOccupe ? 'Un instant…' : 'Enregistrer'}
                </button>
                {telephonie?.identifiant ? (
                  <button type="button" className="btn danger sm" disabled={twilioOccupe} onClick={oublierTwilio}>Oublier le compte</button>
                ) : null}
              </div>
            </div>
          </details>
        </div>
      </div>
    </div>
  )
}
