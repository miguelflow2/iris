import React, { useState } from 'react'
import { useStore } from '../lib/store'
import { api, ApiError } from '../lib/api'
import { BtnIcone, Holo, TopBar } from '../components/ui'
import { IcoFermer, IcoHautParleur, IcoMicro, IcoOnde, IcoRobotDegrade, IcoTelecharger } from '../components/icons'

/* =========================================================================
   Présentation de l'assistante IA (maquettes IMG_0709 et IMG_0710) : deux
   pages dans un seul écran. Page 1 : ce qu'on peut lui demander, avec des
   exemples cliquables qui envoient vraiment la question à IRIS. Page 2 : les
   deux façons de la réveiller, avec un bouton pour entendre l'exemple.
   ========================================================================= */

const WAKE_DEFAUT = 'Dis-moi Iris'

const EXEMPLES_VOIX = [
  'Comment prendre efficacement des notes pendant une réunion ?',
  'Peux-tu te présenter ?',
  'Recommande-moi des films bien notés à voir ce week-end.'
]

const EXEMPLES_PHOTO = ['De quel type de plante s’agit-il ?', 'Peux-tu me recommander un plat faible en calories dans ce menu ?']

interface ImageEnvoyee {
  media_type: string
  data: string
}

/** Blob → base64 sans le préfixe « data:… ; base64, » (format attendu par /messages). */
function blobEnBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const lecteur = new FileReader()
    lecteur.onerror = () => reject(lecteur.error || new Error('lecture impossible'))
    lecteur.onload = () => {
      const brut = String(lecteur.result || '')
      const virgule = brut.indexOf(',')
      resolve(virgule >= 0 ? brut.slice(virgule + 1) : brut)
    }
    lecteur.readAsDataURL(blob)
  })
}

export function AssistantIntroScreen({ params }: { params?: Record<string, any> }): JSX.Element {
  const { nav, settings, lunettes, voice, toast, setPref } = useStore()
  const [page, setPage] = useState<1 | 2>(params?.page === 2 ? 2 : 1)
  const [occupe, setOccupe] = useState(false)
  const wake: string = settings?.wake_word || WAKE_DEFAUT

  /** Ouvre une conversation écrite, y envoie la phrase (et l'image éventuelle), puis va dans l'onglet IA. */
  const envoyer = async (texte: string, images: ImageEnvoyee[] = []): Promise<void> => {
    const conv = await api.post('/api/conversations', { agent: 'auto' })
    await api.post(`/api/conversations/${conv.id}/messages`, { text: texte, images, agent: 'auto' })
    try {
      window.sessionStorage.setItem('iris.ouvrirConversation', String(conv.id))
    } catch {
      /* stockage de session indisponible : l'onglet IA ouvrira la conversation la plus récente */
    }
    nav.allerOnglet('ia')
  }

  const signalerErreur = (err: unknown): void => {
    const statut = err instanceof ApiError ? err.status : 0
    toast(String((err as Error)?.message || err), statut === 409 ? 'info' : 'error')
  }

  const poserQuestion = async (texte: string): Promise<void> => {
    if (occupe) return
    setOccupe(true)
    try {
      await envoyer(texte)
    } catch (err) {
      signalerErreur(err)
    } finally {
      setOccupe(false)
    }
  }

  const photoEtQuestion = async (texte: string): Promise<void> => {
    if (occupe) return
    if (!lunettes?.connected) {
      toast('Connectez d’abord les lunettes.', 'error')
      return
    }
    setOccupe(true)
    try {
      const r = await api.post('/api/glasses/photo', { reconnaissance: true })
      if (!r?.ok || !r?.chemin) {
        // Trame envoyée mais image non reconstituée : constat honnête, pas un faux succès.
        toast(r?.constat || 'Aucune image reçue des lunettes.', 'info')
        return
      }
      const nom = String(r.chemin).split(/[\\/]/).pop() || ''
      const blob = await api.blob('/api/glasses/captures/' + encodeURIComponent(nom))
      const data = await blobEnBase64(blob)
      await envoyer(texte, [{ media_type: 'image/jpeg', data }])
    } catch (err) {
      signalerErreur(err)
    } finally {
      setOccupe(false)
    }
  }

  const ecouter = async (): Promise<void> => {
    try {
      await api.post('/api/voice/say', { text: `${wake}, quel temps fait-il aujourd’hui ?` })
    } catch (err) {
      toast(String((err as Error).message), 'error')
    }
  }

  const terminer = (): void => {
    if (voice?.state === 'off') api.send({ type: 'voice.start' })
    setPref('assistant_intro_vue', true)
    nav.retour()
  }

  const fermer = (
    <BtnIcone plein aria-label="Fermer" onClick={nav.retour}>
      <IcoFermer />
    </BtnIcone>
  )

  if (page === 2) {
    return (
      <div className="ecran">
        <TopBar titre="" retour={false} droite={fermer} />
        <div className="intro">
          <IcoRobotDegrade className="robot" />
          <div style={{ textAlign: 'left', width: '100%', marginTop: 8 }}>
            <div style={{ fontSize: 22 }}>Essayez de dire :</div>
            <div style={{ fontSize: 28, fontWeight: 600, lineHeight: 1.25, whiteSpace: 'pre-line', marginTop: 10 }}>
              {`« ${wake}\nQuel temps fait-il aujourd’hui ? »`}
            </div>
          </div>
          <div className="reveil" style={{ width: '100%', marginTop: 24 }}>
            <div className="rond"><IcoMicro /></div>
            <div className="corps">
              <h3>Réveil vocal</h3>
              <p>Dites « {wake} » pour réveiller l’assistante vocale</p>
            </div>
            <BtnIcone plein aria-label="Écouter l’exemple" title="Écouter l’exemple" onClick={ecouter}>
              <IcoHautParleur />
            </BtnIcone>
          </div>
          <div className="reveil" style={{ width: '100%' }}>
            <div className="rond"><IcoTelecharger /></div>
            <div className="corps">
              <h3>Réveil par le bouton arrière droit</h3>
              <p>Un clic sur le bouton arrière droit réveille l’assistante vocale</p>
            </div>
          </div>
        </div>
        <div style={{ padding: '8px 16px 24px', marginTop: 'auto' }}>
          <Holo variante="blanc" onClick={terminer}>Terminer</Holo>
        </div>
      </div>
    )
  }

  return (
    <div className="ecran">
      <TopBar titre="" retour={false} droite={fermer} />
      <div className="intro">
        <IcoRobotDegrade className="robot" />
        <h1>Assistante IA IRIS</h1>
        <p className="sous">Vous pouvez activer l’assistante vocale à tout moment et lui poser des questions.</p>
        <p className="consigne">Dites « {wake} » pour activer l’assistante vocale et posez directement votre question.</p>

        <div className="bloc">
          <h3>Conversation vocale normale</h3>
          <div className="exemples">
            <div className="legende">Exemples de questions à l’assistante :</div>
            {EXEMPLES_VOIX.map((q) => (
              <button key={q} type="button" className="exemple" disabled={occupe} title="Envoyer cette question à IRIS" onClick={() => poserQuestion(q)}>
                <IcoOnde />
                <span>{q}</span>
              </button>
            ))}
          </div>
        </div>

        <div className="bloc">
          <h3>Prenez une photo et parlez</h3>
          <div className="exemples">
            <div className="legende">
              Par exemple, vous pouvez demander à l’assistante de prendre une photo de votre environnement et d’utiliser la reconnaissance d’images
              pour l’analyser et vous répondre précisément, par exemple :
            </div>
            {EXEMPLES_PHOTO.map((q) => (
              <button key={q} type="button" className="exemple" disabled={occupe} title="Prendre une photo avec les lunettes et poser cette question" onClick={() => photoEtQuestion(q)}>
                <IcoOnde />
                <span>{q}</span>
              </button>
            ))}
          </div>
        </div>
      </div>
      <div style={{ padding: '8px 16px 24px', marginTop: 'auto' }}>
        <Holo onClick={() => setPage(2)}>Continuer</Holo>
      </div>
    </div>
  )
}
