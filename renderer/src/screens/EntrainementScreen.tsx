import React from 'react'
import { TopBar } from '../components/ui'

/** PROVISOIRE (fondation du 2026-09-13) : remplacé par l'équipe qui construit « Entraînement ». */
export function EntrainementScreen({ params: _params }: { params?: Record<string, any> }): JSX.Element {
  return (
    <div className="ecran">
      <TopBar titre="Entraînement" />
      <div className="contenu">
        <p className="muted">Écran en construction.</p>
      </div>
    </div>
  )
}
