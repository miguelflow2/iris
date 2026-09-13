import React, { useCallback, useEffect, useState } from 'react'
import { BtnIcone, CarteReglage, Field, Holo, Liste, Rangee, TopBar } from '../components/ui'
import { IcoActualiser, IcoBouclier, IcoCopier } from '../components/icons'
import { api } from '../lib/api'
import { useStore } from '../lib/store'

/* =========================================================================
   « Compte et sécurité » : le mot de passe du propriétaire (celui qui protège
   l'accès depuis le téléphone — backend/iris/comptes.py), l'accès réseau local
   avec les adresses à ouvrir sur le téléphone, le démarrage avec Windows, et
   les raccourcis vers la confidentialité et l'assistant de démarrage.
   ========================================================================= */

interface Compte {
  configure: boolean
  nom?: string
}

interface Remote {
  enabled: boolean
  port: number
  urls: { ip: string; url: string }[]
  note?: string
}

export function CompteSecuriteScreen({ params: _params }: { params?: Record<string, any> }): JSX.Element {
  const { nav, settings, updateSettings, toast } = useStore()
  const [compte, setCompte] = useState<Compte | null>(null)
  const [nom, setNom] = useState('')
  const [ancien, setAncien] = useState('')
  const [nouveau, setNouveau] = useState('')
  const [repetition, setRepetition] = useState('')
  const [occupe, setOccupe] = useState(false)
  const [remote, setRemote] = useState<Remote | null>(null)

  const chargerCompte = useCallback(async () => {
    try {
      const c = await api.get('/api/compte')
      setCompte({ configure: Boolean(c?.configure), nom: c?.nom || '' })
      if (c?.nom) setNom((n) => n || c.nom)
    } catch {
      setCompte({ configure: false })
    }
  }, [])

  const chargerRemote = useCallback(async () => {
    try {
      setRemote(await api.get('/api/remote'))
    } catch {
      /* le service répondra plus tard */
    }
  }, [])

  useEffect(() => {
    chargerCompte()
  }, [chargerCompte])

  // Les adresses changent quand l'accès est (dés)activé : on les relit à chaque changement du réglage.
  useEffect(() => {
    chargerRemote()
  }, [chargerRemote, settings?.remote_access])

  const configure = Boolean(compte?.configure)
  const formulaireValide = nouveau.length >= 8 && nouveau === repetition && (configure ? ancien.length > 0 : true)

  const enregistrerMotDePasse = async (): Promise<void> => {
    if (nouveau.trim().length < 8) {
      toast('Le mot de passe doit faire au moins 8 caractères.', 'error')
      return
    }
    if (nouveau !== repetition) {
      toast('Les deux mots de passe ne sont pas identiques.', 'error')
      return
    }
    setOccupe(true)
    try {
      if (configure) {
        await api.patch('/api/compte', { mot_de_passe: ancien, nouveau })
        toast('Mot de passe modifié.', 'success')
      } else {
        await api.post('/api/compte', { nouveau, nom: nom.trim() })
        toast('Votre compte est en place.', 'success')
      }
      setAncien('')
      setNouveau('')
      setRepetition('')
      await chargerCompte()
    } catch (err) {
      // 400 = refus du service (ancien mot de passe faux, trop court…) : le détail est le message.
      toast(String((err as Error).message), 'error')
    } finally {
      setOccupe(false)
    }
  }

  const deconnecterTout = async (): Promise<void> => {
    if (!window.confirm('Déconnecter tous les appareils ? Chaque téléphone devra ressaisir le mot de passe.')) return
    try {
      await api.post('/api/compte/deconnexion')
      toast('Tous les appareils ont été déconnectés.', 'success')
    } catch (err) {
      toast(String((err as Error).message), 'error')
    }
  }

  const basculerAcces = async (v: boolean): Promise<void> => {
    try {
      // updateSettings pose le nouveau settings dans le magasin : l'effet ci-dessus relit /api/remote.
      await updateSettings({ remote_access: v })
      toast(v ? 'Accès depuis le téléphone activé. Redémarrez IRIS pour qu’il prenne effet.' : 'Accès depuis le téléphone désactivé.', 'success')
    } catch (err) {
      toast(String((err as Error).message), 'error')
    }
  }

  const copier = (url: string): void => {
    navigator.clipboard
      .writeText(url)
      .then(() => toast('Adresse copiée.', 'success'))
      .catch(() => toast('Impossible de copier l’adresse.', 'error'))
  }

  const relancerAssistant = (): void => {
    if (!window.confirm('Relancer l’assistant de démarrage ? Vos réglages sont conservés ; seules les étapes d’accueil seront reproposées.')) return
    updateSettings({ onboarded: false }).catch((err: Error) => toast(String(err.message), 'error'))
  }

  return (
    <div className="ecran">
      <TopBar titre="Compte et sécurité" />
      <div className="contenu">
        <h3 className="section-sous">Mot de passe du propriétaire</h3>
        <div className="carte col" style={{ gap: 14 }}>
          {compte === null ? (
            <div className="small muted">Chargement…</div>
          ) : configure ? (
            <>
              <div className="small muted">
                Un compte existe sur cet ordinateur{compte.nom ? ` — ${compte.nom}` : ''}. Pour changer le mot de passe, entrez l’ancien puis le nouveau.
              </div>
              <Field label="Ancien mot de passe">
                <input className="input" type="password" autoComplete="current-password" value={ancien} onChange={(e) => setAncien(e.target.value)} />
              </Field>
            </>
          ) : (
            <>
              <div className="small muted">
                Aucun mot de passe n’est encore posé. IRIS ouvre vos applications et lit votre écran : ce mot de passe protège cet accès quand vous la joignez depuis
                votre téléphone. Il ne quitte jamais cet ordinateur et n’y est jamais écrit en clair.
              </div>
              <Field label="Nom du compte">
                <input className="input" value={nom} placeholder="Votre prénom" onChange={(e) => setNom(e.target.value)} />
              </Field>
            </>
          )}
          {compte !== null ? (
            <>
              <Field label="Nouveau mot de passe" hint="8 caractères au minimum.">
                <input className="input" type="password" autoComplete="new-password" value={nouveau} onChange={(e) => setNouveau(e.target.value)} />
              </Field>
              <Field label="Répétez-le">
                <input
                  className="input"
                  type="password"
                  autoComplete="new-password"
                  value={repetition}
                  onChange={(e) => setRepetition(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && formulaireValide) enregistrerMotDePasse()
                  }}
                />
              </Field>
              <Holo variante="blanc" disabled={!formulaireValide || occupe} onClick={enregistrerMotDePasse}>
                {occupe ? 'Un instant…' : configure ? 'Changer le mot de passe' : 'Créer mon compte'}
              </Holo>
            </>
          ) : null}
          <div className="small muted">Ce mot de passe protège l’accès depuis le téléphone.</div>
          {configure ? (
            <>
              <button type="button" className="btn danger" onClick={deconnecterTout}>Déconnecter tous les appareils</button>
              <div className="small muted">
                Oublié ? Il n’est stocké nulle part, donc introuvable. Supprimez <span className="mono">compte.json</span> dans le dossier de données d’IRIS pour
                repartir de zéro : cela déconnecte aussi tous vos téléphones.
              </div>
            </>
          ) : null}
        </div>

        <h3 className="section-sous">Accès depuis le téléphone</h3>
        <CarteReglage
          titre="Autoriser l’accès depuis le téléphone"
          desc="Ouvre IRIS aux appareils de votre réseau local, protégé par le mot de passe."
          on={Boolean(settings?.remote_access)}
          onChange={basculerAcces}
        />
        {settings?.remote_access ? (
          <div className="carte col" style={{ gap: 10 }}>
            <div className="small" style={{ color: 'var(--warn)', lineHeight: 1.45 }}>
              IRIS exécute des commandes sur cet ordinateur. N’activez ceci que sur un réseau de confiance, et <strong>n’ouvrez jamais de port sur votre routeur</strong> :
              pour y accéder de l’extérieur, il faut un tunnel privé.
            </div>
            {remote?.urls?.length ? (
              <>
                <div className="small muted">Ouvrez cette adresse dans le navigateur de votre téléphone :</div>
                {remote.urls.map((u) => (
                  <div className="row between" key={u.ip} style={{ gap: 8 }}>
                    <code className="mono" style={{ wordBreak: 'break-all', flex: 1, minWidth: 0 }}>{u.url}</code>
                    <BtnIcone title="Copier" aria-label="Copier l’adresse" onClick={() => copier(u.url)}>
                      <IcoCopier />
                    </BtnIcone>
                  </div>
                ))}
                <div className="small muted">{remote.note || 'Le téléphone doit être sur le même réseau WiFi que cet ordinateur.'} L’adresse contient votre jeton : ne la partagez pas.</div>
              </>
            ) : (
              <div className="small muted">Redémarrez IRIS pour que l’accès réseau prenne effet.</div>
            )}
          </div>
        ) : null}

        <CarteReglage
          titre="Démarrer avec Windows"
          desc="IRIS s’ouvre avec votre session et reste dans la barre système."
          on={Boolean(settings?.start_with_windows)}
          onChange={(v) => updateSettings({ start_with_windows: v }).catch((err: Error) => toast(String(err.message), 'error'))}
        />

        <Liste>
          <Rangee icone={<IcoBouclier />} titre="Confidentialité et consentements" onClick={() => nav.ouvrir('confidentialite')} />
          <Rangee icone={<IcoActualiser />} titre="Relancer l’assistant de démarrage" onClick={relancerAssistant} />
        </Liste>
      </div>
    </div>
  )
}
