import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { BtnIcone, Field, Holo, Liste, Rangee, TopBar, Vide } from '../components/ui'
import { IcoPlus, IcoPoubelle, IcoUtilisateur } from '../components/icons'
import { api, messageErreur, type IrisEvent } from '../lib/api'
import { useStore } from '../lib/store'
import { IcoDegrade, dateLisible, pluriel } from './CoursScreen'
import './AccessibiliteScreen.css'
import './CoursScreen.css'

/* =========================================================================
   « Rappels liés à une personne » : « la prochaine fois que je vois Marc,
   rappelle-moi de lui rendre ses clés ».

   IRIS ne voit pas qui est devant vous : les lunettes n'envoient pas de flux
   vidéo, et la reconnaissance faciale est volontairement exclue (données
   biométriques). Un rappel ne se déclenche donc que sur des indices qu'IRIS
   constate réellement (backend/iris/rappels_contexte.py) : le prénom entendu
   dans les sous-titres, dit dans une commande vocale ou « je suis avec… »,
   écrit dans un message à IRIS, un texto, un brouillon ou un courriel.
   L'écran le dit tel quel, avec ce qui ne déclenche PAS.

   Créer, consulter et effacer ses rappels ne dépend pas des lunettes ; les
   déclencheurs par la voix, eux, n'existent que si IRIS entend.
   ========================================================================= */

interface Rappel {
  id: string
  personne: string
  texte: string
  cree_le: string | null
  declenche_le: string | null
  declencheur: string | null
}

/** Libellés des déclencheurs (rappels_contexte.DECLENCHEURS). */
const DECLENCHEURS: Record<string, string> = {
  sous_titres: 'nom entendu dans les sous-titres',
  presence: '« je suis avec… » dit à IRIS',
  commande_vocale: 'nom prononcé dans une commande vocale',
  message_ecrit: 'nom écrit dans un message à IRIS',
  sms: 'nom présent dans un texto reçu',
  brouillon_message: 'nom présent dans un brouillon de message',
  courriel: 'nom présent dans un courriel',
  telephonie: 'nom présent dans un événement de téléphonie'
}

export function RappelsContexteScreen({ params }: { params?: Record<string, any> }): JSX.Element {
  const { settings, toast, presence } = useStore()
  const [rappels, setRappels] = useState<Rappel[] | null>(null)
  const [suspendue, setSuspendue] = useState<string | null>(null)
  const [erreurListe, setErreurListe] = useState('')
  const [personne, setPersonne] = useState<string>(() => (typeof params?.personne === 'string' ? params.personne : ''))
  const [texte, setTexte] = useState('')
  const [occupe, setOccupe] = useState(false)
  const [erreur, setErreur] = useState('')
  const vivant = useRef(true)

  const absentes = presence !== null && !presence.presentes

  const charger = useCallback(async () => {
    try {
      const r = await api.get('/api/rappels-contexte')
      if (!vivant.current) return
      setRappels(Array.isArray(r?.rappels) ? r.rappels : [])
      setSuspendue(typeof r?.memoire_suspendue === 'string' && r.memoire_suspendue ? r.memoire_suspendue : null)
      setErreurListe('')
    } catch (err) {
      if (vivant.current) setErreurListe(messageErreur(err))
    }
  }, [])

  useEffect(() => {
    vivant.current = true
    charger()
    // Un rappel créé à la voix, ou déclenché par un prénom entendu : la liste suit (le toast vient du magasin).
    const off = api.on((e: IrisEvent) => {
      if (e.type === 'rappels_contexte.maj' || e.type === 'rappel.contexte') charger()
    })
    return () => {
      vivant.current = false
      off()
    }
  }, [charger])

  const enAttente = useMemo(() => (rappels || []).filter((r) => !r.declenche_le), [rappels])
  const declenches = useMemo(
    () => (rappels || []).filter((r) => r.declenche_le).sort((a, b) => String(b.declenche_le).localeCompare(String(a.declenche_le))),
    [rappels]
  )

  const creer = async (): Promise<void> => {
    if (occupe) return
    if (!personne.trim()) {
      setErreur('Précisez la personne (par exemple « Marc »).')
      return
    }
    if (!texte.trim()) {
      setErreur('Précisez ce qu’il faut rappeler.')
      return
    }
    setOccupe(true)
    setErreur('')
    try {
      await api.post('/api/rappels-contexte', { personne: personne.trim(), texte: texte.trim() })
      if (!vivant.current) return
      toast(`Rappel créé pour ${personne.trim()}.`, 'success')
      setPersonne('')
      setTexte('')
      await charger()
    } catch (err) {
      if (vivant.current) setErreur(messageErreur(err))
    } finally {
      if (vivant.current) setOccupe(false)
    }
  }

  const supprimer = async (r: Rappel): Promise<void> => {
    if (!window.confirm(`Effacer le rappel pour ${r.personne} : « ${r.texte} » ?`)) return
    try {
      await api.delete(`/api/rappels-contexte/${encodeURIComponent(r.id)}`)
      toast('Rappel effacé.', 'success')
      charger()
    } catch (err) {
      toast(messageErreur(err), 'error')
    }
  }

  const motActivation = String(settings?.wake_word || 'Dis-moi Iris')

  const rangee = (r: Rappel): JSX.Element => (
    <Rangee
      key={r.id}
      compacte
      icone={<IcoUtilisateur />}
      titre={
        <>
          <span style={{ color: '#8ff0ff' }}>{r.personne}</span> · {r.texte}
        </>
      }
      sous={
        r.declenche_le
          ? `Déclenché le ${dateLisible(r.declenche_le)} : ${DECLENCHEURS[r.declencheur || ''] || r.declencheur || 'déclencheur inconnu'}`
          : `Créé le ${dateLisible(r.cree_le)} · en attente`
      }
      droite={
        <BtnIcone aria-label={`Effacer le rappel pour ${r.personne}`} title="Effacer" onClick={() => supprimer(r)}>
          <IcoPoubelle />
        </BtnIcone>
      }
    />
  )

  return (
    <div className="ecran">
      <TopBar titre="Rappels liés à une personne" />
      <div className="contenu">
        {suspendue ? (
          <div className="bloc-note attention">
            Mémoire suspendue (mode invité ou zone sans mémoire) : aucun rappel n’est créé ni déclenché tant qu’elle l’est.
          </div>
        ) : null}
        {absentes ? (
          <div className="bloc-note">
            Lunettes non connectées : IRIS n’entend ni vos commandes ni les prénoms autour de vous. En attendant, seul un message écrit à IRIS,
            un texto, un brouillon ou un courriel qui nomme la personne peut déclencher un rappel.
          </div>
        ) : null}

        {/* ------------------------------------------------------------ créer */}
        <div className="carte q-formulaire">
          <h3 style={{ margin: 0 }}>La prochaine fois que je vois…</h3>
          <div className="q-grille-2">
            <Field label="Personne" hint="Le prénom tel qu’on le dit : « Marc », « ma sœur Julie ».">
              <input className="input" value={personne} maxLength={60} placeholder="Marc" disabled={Boolean(suspendue)} onChange={(e) => setPersonne(e.target.value)} />
            </Field>
            <Field label="Rappelez-moi de…">
              <input
                className="input"
                value={texte}
                maxLength={300}
                placeholder="lui rendre ses clés"
                disabled={Boolean(suspendue)}
                onChange={(e) => setTexte(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') creer()
                }}
              />
            </Field>
          </div>
          <Holo disabled={occupe || Boolean(suspendue)} onClick={creer}><IcoPlus /> {occupe ? 'Création…' : 'Créer le rappel'}</Holo>
          {erreur ? <div className="bloc-note erreur" role="alert">{erreur}</div> : null}
          <div className="q-note">
            À la voix : « {motActivation}, la prochaine fois que je vois Marc, rappelle-moi de lui rendre ses clés », ou « rappelle-moi de lui
            demander le devis quand je parle à Julie ».
          </div>
        </div>

        {/* ------------------------------------------------------------ listes */}
        {erreurListe ? <div className="bloc-note erreur" role="alert">{erreurListe}</div> : null}
        {rappels === null && !erreurListe ? <div className="empty">Chargement…</div> : null}
        {rappels !== null && rappels.length === 0 ? (
          <Vide
            icone={<IcoDegrade glyphe="personne" />}
            texte="Aucun rappel lié à une personne"
            petit="Notez ce que vous voulez dire ou rendre à quelqu’un : IRIS vous le rappelle quand le prénom revient."
          />
        ) : null}

        {enAttente.length ? (
          <>
            <h2 className="section-sous">En attente · {enAttente.length}</h2>
            <Liste>{enAttente.map(rangee)}</Liste>
          </>
        ) : null}
        {declenches.length ? (
          <>
            <h2 className="section-sous">Déclenchés · {declenches.length}</h2>
            <Liste>{declenches.map(rangee)}</Liste>
            <div className="q-note">Un rappel ne se déclenche qu’une fois : il reste ici jusqu’à ce que vous l’effaciez ou que la durée de conservation l’efface.</div>
          </>
        ) : null}

        {/* ------------------------------------------------------------ comment ça se déclenche */}
        <div className="carte">
          <h3>Quand un rappel se déclenche</h3>
          <ul className="liste-limites">
            <li>Le prénom est entendu dans les sous-titres : seulement pendant que les sous-titres, le journal continu ou un cours transcrivent ce qui se dit.</li>
            <li>Vous dites le prénom dans une commande vocale, ou « {motActivation}, je suis avec Marc ».</li>
            <li>Le prénom apparaît dans un message écrit à IRIS, un texto reçu, un brouillon de message ou un courriel.</li>
          </ul>
          <h3 style={{ marginTop: 14 }}>Ce qui ne le déclenche pas</h3>
          <ul className="liste-limites">
            <li>Voir la personne : IRIS ne reconnaît pas les visages. C’est un choix : ce sont des données biométriques, qui exigeraient un consentement exprès et une déclaration préalable à la Commission d’accès à l’information du Québec.</li>
            <li>Un appel entrant : il ne porte qu’un numéro, et aucun carnet de contacts n’est relié.</li>
            <li>Un prénom mal reconnu par la transcription. À l’inverse, un prénom qui est aussi un mot courant (Pierre, Rose) peut déclencher à tort.</li>
            <li>La phrase qui crée le rappel. Et pendant les 45 secondes qui suivent sa création, les sous-titres ne comptent pas : ils pourraient capter IRIS qui répète le prénom en confirmant.</li>
            <li>Le mode confidentiel, le mode invité et les zones sans mémoire : aucun déclenchement.</li>
          </ul>
          <div className="q-note" style={{ marginTop: 10 }}>
            Personne et texte sont chiffrés sur cet ordinateur ; {pluriel(enAttente.length, 'rappel')} en attente. La durée de conservation réglée dans
            Confidentialité s’applique.
          </div>
        </div>
      </div>
    </div>
  )
}
