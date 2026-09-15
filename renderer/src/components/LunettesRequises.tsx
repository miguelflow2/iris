import React, { useEffect, useId, useRef } from 'react'
import { Holo } from './ui'
import { IcoLunettes } from './icons'
import { useStore, type DemandeLunettes } from '../lib/store'

/* =========================================================================
   « Cette fonction marche avec les lunettes VELA » — la même réponse partout.

   VELA vend des lunettes ; IRIS est ce qu'elles contiennent. Toute fonction qui
   capte (voir, écouter, enregistrer) ou qui agit exige des lunettes présentes
   (backend/iris/lunettes_presence.py). Sans elles, l'utilisateur ne doit pas lire
   une erreur technique, mais les deux seules suites utiles : connecter ses
   lunettes, ou les découvrir.

   Deux formes :
   - LunettesRequises (feuille) : ouverte par App.tsx pour tout refus 428
     « lunettes_requises » reçu par un écran, ou par store.exigerLunettes() ;
   - CarteLunettesRequises : l'état affiché dans un écran AVANT tout appel au
     service, quand la présence est déjà connue comme absente.

   Jamais de mention d'un mode de démonstration ni d'un moyen de lever le verrou :
   c'est un accès propriétaire caché, pas une option client.
   ========================================================================= */

const URL_ACHAT_DEFAUT = 'https://velaglass.ca/lunettes.html'
const TITRE = 'Cette fonction marche avec les lunettes VELA'

/** Ce qu'IRIS sait vraiment : pourquoi les lunettes ne comptent pas comme présentes. */
function phraseEtat(presence: ReturnType<typeof useStore>['presence']): string {
  if (!presence) return 'Connectez vos lunettes à cet ordinateur, ou ouvrez l’app IRIS sur le téléphone appairé à vos lunettes.'
  return 'Aucune paire n’est connectée à cet ordinateur, et aucun téléphone appairé à vos lunettes ne l’a signalé récemment.'
}

function Actions({ acheterUrl, apres }: { acheterUrl: string; apres?: () => void }): JSX.Element {
  const { nav } = useStore()
  return (
    <div className="col" style={{ gap: 10 }}>
      <Holo
        data-premier-focus=""
        onClick={() => {
          apres?.()
          nav.ouvrir('connecter')
        }}
      >
        <IcoLunettes /> Connecter mes lunettes
      </Holo>
      <Holo
        variante="contour"
        onClick={() => {
          window.iris.openExternal(acheterUrl)
        }}
      >
        Acheter les lunettes
      </Holo>
    </div>
  )
}

/**
 * Feuille modale (montée du bas). Rendue ici plutôt qu'avec Feuille (ui.tsx) : elle s'ouvre d'elle-même,
 * souvent juste après un clic sur une carte d'un écran d'accessibilité. Un lecteur d'écran doit donc y être
 * conduit : le focus va sur « Connecter mes lunettes », la tabulation reste dans la feuille, le titre nomme
 * la boîte de dialogue, et le focus revient à l'élément d'avant à la fermeture.
 */
export function LunettesRequises({ demande, onClose }: { demande: DemandeLunettes; onClose: () => void }): JSX.Element {
  const { presence, alerte } = useStore()
  const idTitre = useId()
  const idTexte = useId()
  const feuille = useRef<HTMLDivElement>(null)
  // Lus par l'écouteur clavier sans le réabonner à chaque rendu.
  const alerteRef = useRef(alerte)
  alerteRef.current = alerte
  const fermerRef = useRef(onClose)
  fermerRef.current = onClose

  useEffect(() => {
    const precedent = document.activeElement instanceof HTMLElement ? document.activeElement : null
    // Holo ne transmet pas de ref : on retrouve le bouton « Connecter mes lunettes » dans la feuille.
    feuille.current?.querySelector<HTMLButtonElement>('[data-premier-focus]')?.focus()
    const onKey = (e: KeyboardEvent): void => {
      // L'alerte sonore plein écran passe par-dessus (App.tsx) et se ferme elle-même à Échap :
      // une seule touche ne doit pas fermer les deux.
      if (alerteRef.current) return
      if (e.key === 'Escape') {
        fermerRef.current()
        return
      }
      if (e.key !== 'Tab' || !feuille.current) return
      const focusables = Array.from(feuille.current.querySelectorAll<HTMLElement>('button:not([disabled]), a[href], input, select, textarea, [tabindex]:not([tabindex="-1"])'))
      if (!focusables.length) return
      const debut = focusables[0]
      const fin = focusables[focusables.length - 1]
      const actif = document.activeElement
      if (e.shiftKey && (actif === debut || !feuille.current.contains(actif))) {
        e.preventDefault()
        fin.focus()
      } else if (!e.shiftKey && (actif === fin || !feuille.current.contains(actif))) {
        e.preventDefault()
        debut.focus()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('keydown', onKey)
      if (precedent && precedent.isConnected) precedent.focus()
    }
  }, [])

  const acheterUrl = demande.acheter_url || presence?.acheter_url || URL_ACHAT_DEFAUT
  // Le message du service commence souvent par la phrase du titre : on ne la répète pas deux fois.
  const message = (demande.message || '').startsWith(TITRE) ? (demande.message || '').slice(TITRE.length).replace(/^[\s.:]+/, '') : demande.message || ''
  return (
    <div className="voile-fond" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div ref={feuille} className="feuille" role="dialog" aria-modal="true" aria-labelledby={idTitre} aria-describedby={idTexte}>
        <h3 id={idTitre}>{TITRE}</h3>
        <div className="col lunettes-requises" style={{ gap: 14, padding: '0 6px' }}>
          <p className="lr-texte" id={idTexte}>
            {message || (demande.fonction ? `Connectez vos lunettes pour utiliser « ${demande.fonction} ».` : 'Connectez vos lunettes pour utiliser cette fonction.')}
          </p>
          <p className="small muted" style={{ lineHeight: 1.45 }}>{phraseEtat(presence)}</p>
          <Actions acheterUrl={acheterUrl} apres={onClose} />
          <p className="small muted" style={{ lineHeight: 1.45 }}>
            Sans lunettes, vous gardez l’accès à vos données (consulter, exporter, effacer), à vos réglages, à la confidentialité et au
            verrouillage à distance.
          </p>
          <button type="button" className="btn ghost" onClick={onClose}>Fermer</button>
        </div>
      </div>
    </div>
  )
}

/** Carte à poser en tête d'un écran dont les fonctions exigent les lunettes. */
export function CarteLunettesRequises({ fonction }: { fonction?: string }): JSX.Element {
  const { presence } = useStore()
  const acheterUrl = presence?.acheter_url || URL_ACHAT_DEFAUT
  return (
    <div className="carte col lunettes-requises" style={{ gap: 12 }} role="status">
      <h3 style={{ margin: 0 }}>{TITRE}</h3>
      {fonction ? <div style={{ fontWeight: 700, fontSize: 17 }}>{fonction}</div> : null}
      <div className="desc">{phraseEtat(presence)}</div>
      <Actions acheterUrl={acheterUrl} />
    </div>
  )
}
