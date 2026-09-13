import React from 'react'
import { CarteReglage, Liste, Rangee, Toggle, TopBar } from '../components/ui'
import { IcoActualiser, IcoBouclier, IcoCerveau, IcoCourriel, IcoGlobe, IcoLunettes, IcoMicro, IcoReglages } from '../components/icons'
import { useStore } from '../lib/store'

/* =========================================================================
   « Réglages » : la porte d'entrée des réglages avancés (ancien écran
   Paramètres, éclaté en sous-écrans). Ici ne restent que les entrées de
   navigation, le démarrage avec Windows, le résumé quotidien (ancienne
   section « Mémoire ») et la relance de l'assistant de démarrage.
   ========================================================================= */

export function ReglagesScreen({ params: _params }: { params?: Record<string, any> }): JSX.Element {
  const { nav, settings, updateSettings, toast } = useStore()

  const set = (patch: Record<string, unknown>): void => {
    updateSettings(patch).catch((err: Error) => toast(String(err.message), 'error'))
  }

  const relancerAssistant = (): void => {
    if (!window.confirm('Relancer l’assistant de démarrage ? Vos réglages sont conservés ; seules les étapes d’accueil seront reproposées.')) return
    set({ onboarded: false })
  }

  const resumeActif = Boolean(settings?.daily_summary_enabled)

  return (
    <div className="ecran">
      <TopBar titre="Réglages" />
      <div className="contenu">
        <Liste>
          <Rangee icone={<IcoMicro />} titre="Voix et écoute" sous="Mot d’activation, reconnaissance, voix de synthèse" onClick={() => nav.ouvrir('reglages-voix')} />
          <Rangee icone={<IcoReglages />} titre="Contrôle de l’ordinateur et modèles" sous="Confirmations, effort, recherche web, historique" onClick={() => nav.ouvrir('reglages-pc')} />
          <Rangee icone={<IcoCourriel />} titre="Courriel, SMS et appels" onClick={() => nav.ouvrir('communications')} />
          <Rangee icone={<IcoGlobe />} titre="Comptes web" onClick={() => nav.ouvrir('comptes-web')} />
          <Rangee icone={<IcoCerveau />} titre="Moteurs IA" onClick={() => nav.ouvrir('moteurs-ia')} />
          <Rangee icone={<IcoBouclier />} titre="Confidentialité" onClick={() => nav.ouvrir('confidentialite')} />
          <Rangee icone={<IcoLunettes />} titre="Mes lunettes" onClick={() => nav.ouvrir('lunettes')} />
        </Liste>

        <CarteReglage
          titre="Démarrer avec Windows"
          desc="IRIS s’ouvre avec votre session et reste dans la barre système."
          on={Boolean(settings?.start_with_windows)}
          onChange={(v) => set({ start_with_windows: v })}
        />

        {/* Résumé quotidien : interrupteur + heure (ancienne section « Mémoire » des Paramètres). */}
        <div className="carte reglage">
          <div className="corps">
            <h3>Résumé quotidien</h3>
            <div className="desc">Chaque soir, IRIS résume décisions, promesses, chiffres et idées de la journée dans la mémoire.</div>
            <div className="row" style={{ marginTop: 12, gap: 10 }}>
              <span className="small muted">Chaque jour à</span>
              <input
                type="time"
                className="input"
                aria-label="Heure du résumé quotidien"
                style={{ width: 130 }}
                disabled={!resumeActif}
                value={settings?.daily_summary_time || '21:00'}
                onChange={(e) => {
                  if (e.target.value) set({ daily_summary_time: e.target.value })
                }}
              />
            </div>
          </div>
          <Toggle on={resumeActif} onChange={(v) => set({ daily_summary_enabled: v })} titre="Résumé quotidien" />
        </div>

        <Liste>
          <Rangee icone={<IcoActualiser />} titre="Relancer l’assistant de démarrage" onClick={relancerAssistant} />
        </Liste>
      </div>
    </div>
  )
}
