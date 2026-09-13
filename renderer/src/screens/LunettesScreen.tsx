import React, { useCallback, useRef, useState } from 'react'
import { CarteReglage, Holo, Liste, Rangee, Toggle, TopBar } from '../components/ui'
import { IcoBatterie } from '../components/icons'
import { LunettesFace } from '../components/Lunettes'
import { api, formatDate, formatTime } from '../lib/api'
import { useStore } from '../lib/store'

/* =========================================================================
   Mes lunettes : l'appareil (nom, adresse, état, batterie), les réglages liés aux lunettes
   (reconnexion automatique, verrou, mode démonstration), les actions et la dissociation.
   Aucune donnée inventée : ni firmware ni numéro de série tant que le service ne les fournit pas.
   ========================================================================= */

const PAS_DISPONIBLE = 'Pas encore disponible dans cette version.'

function messageErreur(err: unknown): string {
  return err instanceof Error ? err.message : String(err)
}

export function LunettesScreen({ params }: { params?: Record<string, any> }): JSX.Element {
  void params
  const { nav, settings, updateSettings, lunettes, rafraichirLunettes, toast } = useStore()
  const [occupe, setOccupe] = useState<'batterie' | 'reconnexion' | 'deconnexion' | 'dissociation' | null>(null)
  const monte = useRef(true)
  React.useEffect(() => {
    monte.current = true
    return () => {
      monte.current = false
    }
  }, [])

  const connected = Boolean(lunettes?.connected)
  const device = lunettes?.device
  const remembered = lunettes?.remembered
  const battery: number | null = typeof lunettes?.battery === 'number' ? lunettes.battery : null
  const nom: string = device?.name || remembered?.name || device?.address || remembered?.address || 'Lunettes VELA'
  const adresse: string = device?.address || remembered?.address || ''
  const services: unknown[] = Array.isArray(lunettes?.services) ? lunettes.services : []
  const paquets: number = Number(lunettes?.packet_count) || 0

  const fini = (): void => {
    if (monte.current) setOccupe(null)
  }

  /* ---------------------------------------------------------------- actions */
  const mesurerBatterie = useCallback(async () => {
    if (!connected) {
      toast('Connectez les lunettes pour mesurer la batterie.', 'info')
      return
    }
    setOccupe('batterie')
    try {
      const r = await api.post('/api/glasses/battery')
      await rafraichirLunettes()
      if (typeof r?.battery === 'number') toast(`Batterie : ${r.battery} %`, 'success')
      else toast('Niveau de batterie non communiqué par les lunettes.', 'info')
    } catch (err) {
      toast(messageErreur(err), 'error')
    } finally {
      fini()
    }
  }, [connected, rafraichirLunettes, toast])

  const reconnecter = useCallback(async () => {
    if (!remembered?.address) {
      toast('Aucunes lunettes mémorisées : passez par « Connecter les lunettes ».', 'info')
      return
    }
    setOccupe('reconnexion')
    try {
      await api.post('/api/glasses/connect', { address: remembered.address, name: remembered.name })
      await rafraichirLunettes()
    } catch (err) {
      toast(messageErreur(err), 'error')
    } finally {
      fini()
    }
  }, [remembered?.address, remembered?.name, rafraichirLunettes, toast])

  const deconnecter = useCallback(async () => {
    setOccupe('deconnexion')
    try {
      await api.post('/api/glasses/disconnect')
      await rafraichirLunettes()
    } catch (err) {
      toast(messageErreur(err), 'error')
    } finally {
      fini()
    }
  }, [rafraichirLunettes, toast])

  const dissocier = useCallback(async () => {
    if (!window.confirm('Oublier ces lunettes sur cet ordinateur ?')) return
    setOccupe('dissociation')
    try {
      try {
        await api.post('/api/glasses/disconnect')
      } catch {
        /* déjà déconnectées : on poursuit */
      }
      await api.post('/api/glasses/forget')
      await rafraichirLunettes()
      toast('Lunettes oubliées sur cet ordinateur.', 'info')
      nav.viderPile()
    } catch (err) {
      toast(messageErreur(err), 'error')
    } finally {
      fini()
    }
  }, [nav, rafraichirLunettes, toast])

  /* ---------------------------------------------------------------- réglages */
  const changerAutoConnect = (v: boolean): void => {
    api
      .patch('/api/glasses/prefs', { auto_connect: v })
      .then(() => rafraichirLunettes())
      .catch((err: unknown) => toast(messageErreur(err), 'error'))
  }
  const changerVerrou = (v: boolean): void => {
    updateSettings({ require_glasses: v })
      .then(() => toast(v ? 'Lunettes VELA requises pour parler à IRIS.' : 'Verrou des lunettes désactivé.', 'info'))
      .catch((err: unknown) => toast(messageErreur(err), 'error'))
  }
  const changerDemo = (v: boolean): void => {
    updateSettings({ demo_sans_lunettes: v })
      .then(() => toast(v ? 'Mode démonstration activé : IRIS fonctionne sans les lunettes.' : 'Mode démonstration désactivé.', v ? 'success' : 'info'))
      .catch((err: unknown) => toast(messageErreur(err), 'error'))
  }

  return (
    <div className="ecran">
      <TopBar titre="Mes lunettes" />
      <div className="contenu">
        {/* carte de l'appareil (non cliquable ici) */}
        <div className="carte-appareil">
          <div>
            <div className="nom">{nom}</div>
            <div className="infos">
              {adresse ? <div className="mono" style={{ fontSize: 15 }}>{adresse}</div> : null}
              {connected && lunettes?.connected_at ? <div>Connecté depuis {formatTime(lunettes.connected_at)}</div> : null}
              {!connected && lunettes?.connected_at ? <div>Dernière connexion : {formatDate(lunettes.connected_at)}</div> : null}
              {connected ? (
                <div>
                  {services.length} service{services.length > 1 ? 's' : ''} · {paquets} paquet{paquets > 1 ? 's' : ''}
                </div>
              ) : null}
            </div>
            <div className="etat">
              <span className={'point' + (connected ? '' : ' hors')}>{connected ? 'Connecté' : 'Déconnecté'}</span>
              {battery !== null ? (
                <span className="batterie">
                  <IcoBatterie niveau={battery} /> {battery} %
                </span>
              ) : null}
            </div>
            {lunettes?.error ? (
              <div style={{ marginTop: 10 }}>
                <span className="pill err">{String(lunettes.error)}</span>
              </div>
            ) : null}
          </div>
          <LunettesFace className="photo" />
        </div>

        <CarteReglage
          titre="Reconnexion automatique"
          desc="Se reconnecte aux lunettes mémorisées dès qu’elles sont allumées."
          on={Boolean(remembered?.auto_connect)}
          disabled={!remembered?.address}
          onChange={changerAutoConnect}
        />
        <CarteReglage
          titre="Exiger les lunettes"
          desc="La voix ne fonctionne qu’avec les lunettes VELA connectées ; le chat écrit reste disponible."
          on={settings?.require_glasses !== false}
          onChange={changerVerrou}
        />
        <CarteReglage
          titre="Mode démonstration"
          desc="Pour une présentation : si les lunettes se déconnectent, IRIS continue de répondre à la voix et au chat écrit. À laisser désactivé le reste du temps."
          on={Boolean(settings?.demo_sans_lunettes)}
          onChange={changerDemo}
        />
        {/* Maquette : « Détection d'utilisation ». Aucun support côté service (pas de capteur de port
            exposé) : même carte, interrupteur désactivé, libellé « À venir », toast au clic sur la carte.
            Markup identique à CarteReglage (qui n'accepte qu'un titre texte). */}
        <div
          className="carte reglage"
          role="button"
          tabIndex={0}
          aria-label="Détection d’utilisation : à venir"
          style={{ cursor: 'pointer' }}
          onClick={() => toast(PAS_DISPONIBLE, 'info')}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault()
              toast(PAS_DISPONIBLE, 'info')
            }
          }}
        >
          <div className="corps">
            <h3>
              Détection d’utilisation <span className="pill" style={{ verticalAlign: 'middle', marginLeft: 6 }}>À venir</span>
            </h3>
            <div className="desc">Lorsque vous retirez vos lunettes, la fonction est suspendue.</div>
          </div>
          {/* Un bouton désactivé n'émet pas de clic : on laisse le clic traverser jusqu'à la carte. */}
          <span style={{ pointerEvents: 'none', display: 'inline-flex', flex: 'none' }} aria-hidden="true">
            <Toggle on={false} disabled onChange={() => toast(PAS_DISPONIBLE, 'info')} titre="Détection d’utilisation" />
          </span>
        </div>

        <Liste>
          <Rangee titre="Paramètres d’enregistrement audio" onClick={() => nav.ouvrir('lunettes-audio')} />
          <Rangee
            titre="Mesurer la batterie"
            valeur={occupe === 'batterie' ? 'Mesure…' : battery !== null ? `${battery} %` : undefined}
            onClick={occupe ? undefined : mesurerBatterie}
          />
          {connected ? (
            <Rangee titre="Reconnecter" valeur="Déjà connectées" chevron={false} />
          ) : (
            <Rangee titre="Reconnecter" valeur={occupe === 'reconnexion' ? 'Connexion…' : undefined} onClick={occupe ? undefined : reconnecter} />
          )}
          {connected ? (
            <Rangee titre="Déconnecter" valeur={occupe === 'deconnexion' ? 'Déconnexion…' : undefined} onClick={occupe ? undefined : deconnecter} />
          ) : null}
          <Rangee titre="Détails techniques" onClick={() => nav.ouvrir('lunettes-technique')} />
        </Liste>

        <Liste>
          <Rangee titre="Mise à jour du firmware" valeur="À venir" onClick={() => toast(PAS_DISPONIBLE, 'info')} />
          <Rangee titre="Redémarrer" valeur="À venir" onClick={() => toast(PAS_DISPONIBLE, 'info')} />
          <Rangee titre="Restaurer les paramètres d’usine" valeur="À venir" onClick={() => toast(PAS_DISPONIBLE, 'info')} />
          <Rangee titre="À propos" onClick={() => nav.ouvrir('a-propos')} />
        </Liste>

        <div style={{ marginTop: 'auto', paddingTop: 24 }}>
          <Holo disabled={occupe === 'dissociation'} onClick={dissocier}>
            {occupe === 'dissociation' ? 'Dissociation…' : 'Dissocier'}
          </Holo>
        </div>
      </div>
    </div>
  )
}
