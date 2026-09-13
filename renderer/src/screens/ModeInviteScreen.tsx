import React from 'react'
import { TopBar } from '../components/ui'

/** PROVISOIRE (fondation du 2026-09-13) : remplacé par l'équipe qui construit « Mode invité ». */
export function ModeInviteScreen({ params: _params }: { params?: Record<string, any> }): JSX.Element {
  return (
    <div className="ecran">
      <TopBar titre="Mode invité" />
      <div className="contenu">
        <p className="muted">Écran en construction.</p>
      </div>
    </div>
  )
}
