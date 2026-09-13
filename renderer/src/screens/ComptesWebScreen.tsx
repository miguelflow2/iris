import React, { useCallback, useEffect, useState } from 'react'
import { BtnIcone, Field, Holo, TopBar, Vide } from '../components/ui'
import { IcoGlobe, IcoPoubelle } from '../components/icons'
import { api } from '../lib/api'
import { useStore } from '../lib/store'

/* =========================================================================
   « Comptes web » : les sites auxquels IRIS sait se connecter (ancienne
   section Comptes web des Paramètres). Le mot de passe est rangé dans le
   coffre du système et rempli par IRIS elle-même dans son navigateur piloté :
   l'IA ne le voit jamais, il ne quitte jamais cet ordinateur.
   ========================================================================= */

interface Site {
  name: string
  label?: string
  url: string
  username?: string
  has_password?: boolean
  profile?: string
}

function messageErreur(err: unknown): string {
  return err instanceof Error ? err.message : String(err)
}

export function ComptesWebScreen({ params: _params }: { params?: Record<string, any> }): JSX.Element {
  const { toast } = useStore()
  const [sites, setSites] = useState<Site[]>([])
  const [charge, setCharge] = useState(false)
  const [form, setForm] = useState({ name: '', url: '', username: '', password: '' })
  const [occupe, setOccupe] = useState<string | null>(null) // nom du site en cours de test/suppression, ou 'form'

  const chargerSites = useCallback(
    () =>
      api
        .get('/api/sites')
        .then((r) => setSites(Array.isArray(r?.sites) ? r.sites : []))
        .catch(() => undefined)
        .finally(() => setCharge(true)),
    []
  )

  useEffect(() => {
    chargerSites()
  }, [chargerSites])

  const formValide = Boolean(form.name.trim() && form.url.trim())

  const enregistrer = (): void => {
    if (!formValide || occupe) return
    const nom = form.name.trim().toLowerCase()
    setOccupe('form')
    api
      .put(`/api/sites/${encodeURIComponent(nom)}`, { url: form.url.trim(), username: form.username.trim(), password: form.password || undefined })
      .then(() => {
        setForm({ name: '', url: '', username: '', password: '' })
        toast('Compte enregistré dans le coffre.', 'success')
        return chargerSites()
      })
      .catch((e) => toast(messageErreur(e), 'error'))
      .finally(() => setOccupe(null))
  }

  const tester = (s: Site): void => {
    if (occupe) return
    setOccupe(s.name)
    api
      // Le résultat (« Connecté à … » / « non confirmée ») est annoncé par le store à la réception de
      // l'événement web.login que le service publie à chaque tentative : un second toast ferait doublon.
      // Seules les erreurs HTTP (site inconnu, navigateur indisponible…) sont signalées ici.
      .post(`/api/sites/${encodeURIComponent(s.name)}/login`)
      .catch((e) => toast(messageErreur(e), 'error'))
      .finally(() => setOccupe(null))
  }

  const supprimer = (s: Site): void => {
    if (occupe) return
    if (!window.confirm(`Oublier le compte « ${s.label || s.name} » ? Le mot de passe sera effacé du coffre.`)) return
    setOccupe(s.name)
    api
      .delete(`/api/sites/${encodeURIComponent(s.name)}`)
      .then(() => {
        toast('Compte oublié.', 'info')
        return chargerSites()
      })
      .catch((e) => toast(messageErreur(e), 'error'))
      .finally(() => setOccupe(null))
  }

  return (
    <div className="ecran">
      <TopBar titre="Comptes web" />
      <div className="contenu">
        <p className="small muted" style={{ lineHeight: 1.45, padding: '0 4px' }}>
          IRIS peut se connecter à vos sites (Omnivox, portails, intranets) et y naviguer à la voix : « Dis-moi Iris, connecte-toi à Omnivox et montre mes notes ».
          IRIS ouvre le site dans son navigateur piloté. Le mot de passe est stocké dans le coffre Windows et rempli par IRIS elle-même : l’IA ne le voit jamais et
          il reste sur cet ordinateur. Si le site affiche un contrôle de sécurité (captcha), résolvez-le dans la fenêtre du navigateur qu’IRIS ouvre ; la session est
          ensuite mémorisée.
        </p>

        <h3 className="section-sous">Ajouter un compte</h3>
        <div className="carte col" style={{ gap: 14 }}>
          <Field label="Nom court (ex. omnivox)">
            <input className="input" value={form.name} autoComplete="off" onChange={(e) => setForm({ ...form, name: e.target.value })} />
          </Field>
          <Field label="Adresse de la page de connexion">
            <input className="input mono" placeholder="https://…/Login" autoComplete="off" value={form.url} onChange={(e) => setForm({ ...form, url: e.target.value })} />
          </Field>
          <Field label="Identifiant (matricule, courriel…)">
            <input className="input" value={form.username} autoComplete="off" onChange={(e) => setForm({ ...form, username: e.target.value })} />
          </Field>
          <Field label="Mot de passe" hint="Saisi par vous, jamais affiché ni envoyé à l’IA.">
            <input
              className="input"
              type="password"
              autoComplete="new-password"
              value={form.password}
              onChange={(e) => setForm({ ...form, password: e.target.value })}
              onKeyDown={(e) => {
                if (e.key === 'Enter') enregistrer()
              }}
            />
          </Field>
          <Holo variante="blanc" disabled={!formValide || occupe === 'form'} onClick={enregistrer}>
            {occupe === 'form' ? 'Enregistrement…' : 'Enregistrer le compte'}
          </Holo>
        </div>

        <h3 className="section-sous">Comptes enregistrés</h3>
        {sites.length === 0 ? (
          <Vide icone={<IcoGlobe />} texte={charge ? 'Aucun compte web' : 'Chargement…'} petit={charge ? 'Ajoutez un site ci-dessus pour qu’IRIS puisse s’y connecter à votre place.' : undefined} />
        ) : (
          sites.map((s) => (
            <div className="carte serree col" key={s.name} style={{ gap: 8 }}>
              <div className="row between" style={{ alignItems: 'flex-start' }}>
                <div style={{ minWidth: 0, flex: 1 }}>
                  <div style={{ fontSize: 18, fontWeight: 700 }}>{s.label || s.name}</div>
                  <div className="small muted mono" style={{ wordBreak: 'break-all' }}>{s.url}</div>
                  <div className="small muted" style={{ marginTop: 4 }}>
                    Identifiant : {s.username || '—'} · {s.has_password ? 'mot de passe enregistré' : 'mot de passe manquant'}
                    {s.profile ? ` · profil ${s.profile}` : ''}
                  </div>
                </div>
                <BtnIcone title="Oublier ce compte" aria-label={`Oublier le compte ${s.label || s.name}`} disabled={Boolean(occupe)} onClick={() => supprimer(s)}>
                  <IcoPoubelle />
                </BtnIcone>
              </div>
              <div className="row wrap">
                <button type="button" className="btn sm" disabled={Boolean(occupe)} onClick={() => tester(s)}>
                  {occupe === s.name ? 'Connexion…' : 'Tester la connexion'}
                </button>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  )
}
