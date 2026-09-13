import React, { useState } from 'react'
import { Avatar, Field, Holo, TopBar } from '../components/ui'
import { useStore } from '../lib/store'

/* =========================================================================
   « Modifier mon profil » : prénom, nom de l'assistante et mot d'activation
   (les trois champs « Identité » de l'ancien écran Paramètres). L'état est
   local jusqu'à « Enregistrer », qui envoie tout d'un coup au service.
   ========================================================================= */

export function ProfilModifierScreen({ params: _params }: { params?: Record<string, any> }): JSX.Element {
  const { nav, settings, updateSettings, toast } = useStore()
  const [prenom, setPrenom] = useState<string>(settings?.user_name || '')
  const [nomAssistante, setNomAssistante] = useState<string>(settings?.assistant_name || 'IRIS')
  const [motActivation, setMotActivation] = useState<string>(settings?.wake_word || 'Dis-moi Iris')
  const [occupe, setOccupe] = useState(false)

  const valide = nomAssistante.trim().length > 0 && motActivation.trim().length > 0

  const enregistrer = async (): Promise<void> => {
    if (!valide || occupe) return
    setOccupe(true)
    try {
      await updateSettings({ user_name: prenom.trim(), assistant_name: nomAssistante.trim(), wake_word: motActivation.trim() })
      toast('Profil enregistré.', 'success')
      nav.retour()
    } catch (err) {
      toast(String((err as Error).message), 'error')
    } finally {
      setOccupe(false)
    }
  }

  return (
    <div className="ecran">
      <TopBar titre="Modifier mon profil" />
      <div className="contenu">
        <div style={{ display: 'flex', justifyContent: 'center', padding: '18px 0 6px' }}>
          <Avatar taille="grand" nom={prenom} />
        </div>

        <div className="carte col" style={{ gap: 14 }}>
          <Field label="Votre prénom" hint="C’est ainsi qu’IRIS s’adresse à vous.">
            <input className="input" value={prenom} placeholder="Votre prénom" autoComplete="given-name" onChange={(e) => setPrenom(e.target.value)} />
          </Field>
          <Field label="Nom de l’assistante" hint="Le nom qu’elle donne quand on lui demande qui elle est.">
            <input className="input" value={nomAssistante} onChange={(e) => setNomAssistante(e.target.value)} />
          </Field>
          <Field label="Mot d’activation" hint="La phrase qui la réveille.">
            <input
              className="input"
              value={motActivation}
              onChange={(e) => setMotActivation(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') enregistrer()
              }}
            />
          </Field>
          <div className="small muted">Exemple : « {motActivation.trim() || 'Dis-moi Iris'}, ouvre mon navigateur et mets de la musique ».</div>
        </div>

        <Holo disabled={!valide || occupe} onClick={enregistrer}>{occupe ? 'Enregistrement…' : 'Enregistrer'}</Holo>
      </div>
    </div>
  )
}
