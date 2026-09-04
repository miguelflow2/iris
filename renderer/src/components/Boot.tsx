import React from 'react'
import { Ring } from './Ring'

/**
 * Écrans de démarrage et de panne du service IRIS.
 *
 * Ce sont les deux premiers écrans qu'un visiteur peut voir : ils doivent parler
 * français, dire où on en est, et toujours offrir une sortie. Aucun d'eux ne
 * touche à la voix, aux plans, aux veilles ni à la mémoire : ils s'affichent
 * avant que l'application soit montée.
 */

/**
 * Relance le service local par le canal Electron `iris:restartBackend`.
 * Si le pont ne l'expose pas (shim navigateur, build antérieur), on recharge la fenêtre :
 * ça suffit quand c'est l'affichage qui a décroché pendant que le service est resté debout.
 */
export async function relancerService(): Promise<{ ok: boolean; message?: string }> {
  if (typeof window.iris?.restartBackend === 'function') return window.iris.restartBackend()
  window.location.reload()
  return { ok: true }
}

/** Ouvre le fichier de détail technique si le chemin est connu. */
function ouvrirDetail(chemin?: string): void {
  if (chemin) window.iris.openPath(chemin)
}

/**
 * Écran de démarrage. Aucune étape n'est inventée : on n'affiche que le temps
 * écoulé, qui est la seule chose que le renderer sait vraiment. Passé un certain
 * délai, on rassure, puis on offre une issue.
 */
export function Splash({ logPath }: { logPath?: string }): JSX.Element {
  const [secondes, setSecondes] = React.useState(0)
  React.useEffect(() => {
    const t = window.setInterval(() => setSecondes((v) => v + 1), 1000)
    return () => window.clearInterval(t)
  }, [])

  const patience =
    secondes < 8
      ? 'Le service, la mémoire et la voix démarrent sur cet ordinateur.'
      : secondes < 25
        ? 'Le premier démarrage après l’installation peut prendre une dizaine de secondes.'
        : 'C’est plus long que d’habitude. Le service local est plus lent au tout premier lancement.'

  return (
    <div className="splash">
      <Ring />
      <div>IRIS se prépare…</div>
      <div className="progress indet" style={{ width: 220 }}>
        <div />
      </div>
      <div className="small muted" style={{ maxWidth: 420, textAlign: 'center' }}>{patience}</div>
      {secondes >= 25 ? (
        <div className="row" style={{ gap: 8 }}>
          <button className="btn sm primary" onClick={() => void relancerService()}>Relancer IRIS</button>
          {logPath ? <button className="btn sm" onClick={() => ouvrirDetail(logPath)}>Voir le détail technique</button> : null}
        </div>
      ) : null}
    </div>
  )
}

/**
 * Écran de panne. Le bouton de relance vient en premier, le message technique
 * en dernier et replié : on ne veut pas d'une trace d'erreur en plein écran.
 */
export function Failure({ down, message, logPath }: { down: boolean; message: string; logPath?: string }): JSX.Element {
  const [enCours, setEnCours] = React.useState(false)
  const [echec, setEchec] = React.useState('')

  const relancer = async (): Promise<void> => {
    setEnCours(true)
    setEchec('')
    const res = await relancerService().catch((err) => ({ ok: false, message: String(err) }))
    // En cas de succès, le service repasse « prêt » et cet écran disparaît de lui-même.
    if (!res.ok) {
      setEnCours(false)
      setEchec(res.message || 'La relance n’a pas abouti.')
    }
  }

  return (
    <div className="splash">
      <Ring color="#e5484d" />
      <div style={{ color: 'var(--text)', fontSize: 16 }}>
        {down ? 'IRIS a été interrompue. Elle redémarre toute seule, quelques secondes.' : 'IRIS n’a pas réussi à démarrer sur cet ordinateur.'}
      </div>
      <div className="row" style={{ gap: 8 }}>
        <button className="btn primary" disabled={enCours} onClick={() => void relancer()}>
          {enCours ? 'Relance en cours…' : 'Relancer IRIS'}
        </button>
        {logPath ? <button className="btn" onClick={() => ouvrirDetail(logPath)}>Ouvrir le rapport d’erreur</button> : null}
      </div>
      {echec ? <div className="small" style={{ color: 'var(--danger)', maxWidth: 460, textAlign: 'center' }}>{echec}</div> : null}
      <div className="col small muted" style={{ gap: 4, maxWidth: 460, textAlign: 'center' }}>
        <div>Vérifiez qu’aucune autre copie d’IRIS n’est déjà ouverte (icône dans la barre système, près de l’horloge).</div>
        {logPath ? <div className="mono" style={{ wordBreak: 'break-all', opacity: 0.7 }}>{logPath}</div> : null}
      </div>
      {message ? (
        <details style={{ maxWidth: 640, textAlign: 'center' }}>
          <summary className="small muted" style={{ cursor: 'pointer' }}>Détail technique</summary>
          <div className="small mono muted" style={{ marginTop: 8, opacity: 0.75 }}>{message}</div>
        </details>
      ) : null}
    </div>
  )
}
