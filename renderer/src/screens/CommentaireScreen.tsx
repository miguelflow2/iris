import React, { useEffect, useState } from 'react'
import { Field, Holo, TopBar } from '../components/ui'
import { api } from '../lib/api'
import { useStore } from '../lib/store'

/* =========================================================================
   « Commentaire » : un message à VELA. Aucun envoi automatique — l'application
   de courriel de l'ordinateur s'ouvre, déjà remplie, et c'est l'utilisateur
   qui envoie. L'adresse de support vient du service (GET /api/plan →
   payment.support_email) ; si elle manque, on ne l'invente pas.
   ========================================================================= */

type Sujet = 'Bogue' | 'Idée' | 'Question' | 'Autre'

const SUJETS: Sujet[] = ['Bogue', 'Idée', 'Question', 'Autre']

export function CommentaireScreen({ params: _params }: { params?: Record<string, any> }): JSX.Element {
  const { appInfo, status, toast } = useStore()
  const [supportEmail, setSupportEmail] = useState<string>('')
  const [charge, setCharge] = useState(false)
  const [sujet, setSujet] = useState<Sujet>('Bogue')
  const [texte, setTexte] = useState('')

  useEffect(() => {
    api
      .get('/api/plan')
      .then((r) => setSupportEmail(typeof r?.payment?.support_email === 'string' ? r.payment.support_email : ''))
      .catch(() => undefined)
      .finally(() => setCharge(true))
  }, [])

  const version: string = appInfo?.version || ''
  const plateforme: string = status?.platform || appInfo?.platform || ''

  const envoyer = (): void => {
    if (!supportEmail || !texte.trim()) return
    const objet = `[IRIS ${version}] ${sujet}`
    const corps = `${texte.trim()}\n\n— IRIS ${version} · ${plateforme}`
    const lien = `mailto:${supportEmail}?subject=${encodeURIComponent(objet)}&body=${encodeURIComponent(corps)}`
    // Le pont `iris.openExternal` ne laisse passer que http(s) (electron/main/index.ts). Pour un
    // lien mailto:, on passe par window.open : le processus principal (setWindowOpenHandler)
    // le remet au système, qui ouvre le client de courriel par défaut — rien ne part d'ici.
    window.open(lien)
    toast('Votre application de courriel s’ouvre.', 'info')
  }

  return (
    <div className="ecran">
      <TopBar titre="Commentaire" />
      <div className="contenu">
        <div className="carte col" style={{ gap: 14 }}>
          <Field label="Sujet">
            <select className="select" value={sujet} onChange={(e) => setSujet(e.target.value as Sujet)}>
              {SUJETS.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </Field>
          <Field label="Votre message">
            <textarea
              className="textarea"
              rows={7}
              placeholder="Dites-nous ce qui marche, ce qui manque…"
              value={texte}
              onChange={(e) => setTexte(e.target.value)}
            />
          </Field>
          <div className="small muted">Version {version || '—'}{plateforme ? ` · ${plateforme}` : ''} — ces deux informations sont ajoutées au bas du message.</div>
        </div>

        <Holo disabled={!supportEmail || !texte.trim()} onClick={envoyer}>Envoyer par courriel</Holo>

        {charge && !supportEmail ? <div className="small muted" style={{ textAlign: 'center' }}>Adresse de support indisponible pour le moment.</div> : null}
        <div className="small muted" style={{ textAlign: 'center', lineHeight: 1.45 }}>
          Aucun envoi automatique : votre application de courriel s’ouvre, vous relisez, vous envoyez.
        </div>
      </div>
    </div>
  )
}
