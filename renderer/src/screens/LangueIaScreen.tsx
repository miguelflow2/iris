import React, { useMemo, useState } from 'react'
import { Option, TopBar } from '../components/ui'
import { IcoCoche, IcoRecherche } from '../components/icons'
import { useStore } from '../lib/store'
import { messageErreur } from './ia/commun'

/* =========================================================================
   Paramètres de langue de l'IA (maquette IMG_0714) : « Suivre le système »
   (= fr-CA, la langue par défaut du service) ou une autre langue de la liste.
   Enregistré dans settings.language (PATCH /api/settings).
   ========================================================================= */

const LANGUE_SYSTEME = 'fr-CA'

interface Langue {
  code: string
  nom: string
  natif: string
}

const LANGUES_BRUTES: Langue[] = [
  { code: 'af-ZA', nom: 'Afrikaans (Afrique du Sud)', natif: 'Afrikaans' },
  { code: 'de-DE', nom: 'Allemand (Allemagne)', natif: 'Deutsch (Deutschland)' },
  { code: 'de-AT', nom: 'Allemand (Autriche)', natif: 'Deutsch (Österreich)' },
  { code: 'de-CH', nom: 'Allemand (Suisse)', natif: 'Deutsch (Schweiz)' },
  { code: 'am-ET', nom: 'Amharique (Éthiopie)', natif: 'አማርኛ' },
  { code: 'en-AU', nom: 'Anglais (Australie)', natif: 'English (Australia)' },
  { code: 'en-CA', nom: 'Anglais (Canada)', natif: 'English (Canada)' },
  { code: 'en-US', nom: 'Anglais (États-Unis)', natif: 'English (United States)' },
  { code: 'en-GB', nom: 'Anglais (Royaume-Uni)', natif: 'English (United Kingdom)' },
  { code: 'ar-SA', nom: 'Arabe (Arabie saoudite)', natif: 'العربية (السعودية)' },
  { code: 'ar-EG', nom: 'Arabe (Égypte)', natif: 'العربية (مصر)' },
  { code: 'ar-AE', nom: 'Arabe (Émirats arabes unis)', natif: 'العربية (الإمارات)' },
  { code: 'ar-MA', nom: 'Arabe (Maroc)', natif: 'العربية (المغرب)' },
  { code: 'eu-ES', nom: 'Basque (Espagne)', natif: 'Euskara' },
  { code: 'bn-BD', nom: 'Bengali (Bangladesh)', natif: 'বাংলা' },
  { code: 'bg-BG', nom: 'Bulgare (Bulgarie)', natif: 'Български' },
  { code: 'ca-ES', nom: 'Catalan (Espagne)', natif: 'Català' },
  { code: 'zh-CN', nom: 'Chinois (Chine)', natif: '中文 (简体)' },
  { code: 'zh-TW', nom: 'Chinois (Taïwan)', natif: '中文 (繁體)' },
  { code: 'ko-KR', nom: 'Coréen (Corée du Sud)', natif: '한국어' },
  { code: 'hr-HR', nom: 'Croate (Croatie)', natif: 'Hrvatski' },
  { code: 'da-DK', nom: 'Danois (Danemark)', natif: 'Dansk' },
  { code: 'es-AR', nom: 'Espagnol (Argentine)', natif: 'Español (Argentina)' },
  { code: 'es-ES', nom: 'Espagnol (Espagne)', natif: 'Español (España)' },
  { code: 'es-MX', nom: 'Espagnol (Mexique)', natif: 'Español (México)' },
  { code: 'et-EE', nom: 'Estonien (Estonie)', natif: 'Eesti' },
  { code: 'fi-FI', nom: 'Finnois (Finlande)', natif: 'Suomi' },
  { code: 'fr-BE', nom: 'Français (Belgique)', natif: 'Français (Belgique)' },
  { code: 'fr-CA', nom: 'Français (Canada)', natif: 'Français (Canada)' },
  { code: 'fr-FR', nom: 'Français (France)', natif: 'Français (France)' },
  { code: 'fr-CH', nom: 'Français (Suisse)', natif: 'Français (Suisse)' },
  { code: 'el-GR', nom: 'Grec (Grèce)', natif: 'Ελληνικά' },
  { code: 'he-IL', nom: 'Hébreu (Israël)', natif: 'עברית' },
  { code: 'hi-IN', nom: 'Hindi (Inde)', natif: 'हिन्दी' },
  { code: 'hu-HU', nom: 'Hongrois (Hongrie)', natif: 'Magyar' },
  { code: 'id-ID', nom: 'Indonésien (Indonésie)', natif: 'Bahasa Indonesia' },
  { code: 'ga-IE', nom: 'Irlandais (Irlande)', natif: 'Gaeilge' },
  { code: 'is-IS', nom: 'Islandais (Islande)', natif: 'Íslenska' },
  { code: 'it-IT', nom: 'Italien (Italie)', natif: 'Italiano' },
  { code: 'ja-JP', nom: 'Japonais (Japon)', natif: '日本語' },
  { code: 'lv-LV', nom: 'Letton (Lettonie)', natif: 'Latviešu' },
  { code: 'lt-LT', nom: 'Lituanien (Lituanie)', natif: 'Lietuvių' },
  { code: 'ms-MY', nom: 'Malais (Malaisie)', natif: 'Bahasa Melayu' },
  { code: 'nl-BE', nom: 'Néerlandais (Belgique)', natif: 'Nederlands (België)' },
  { code: 'nl-NL', nom: 'Néerlandais (Pays-Bas)', natif: 'Nederlands (Nederland)' },
  { code: 'nb-NO', nom: 'Norvégien (Norvège)', natif: 'Norsk bokmål' },
  { code: 'ur-PK', nom: 'Ourdou (Pakistan)', natif: 'اردو' },
  { code: 'fa-IR', nom: 'Persan (Iran)', natif: 'فارسی' },
  { code: 'pl-PL', nom: 'Polonais (Pologne)', natif: 'Polski' },
  { code: 'pt-BR', nom: 'Portugais (Brésil)', natif: 'Português (Brasil)' },
  { code: 'pt-PT', nom: 'Portugais (Portugal)', natif: 'Português (Portugal)' },
  { code: 'ro-RO', nom: 'Roumain (Roumanie)', natif: 'Română' },
  { code: 'ru-RU', nom: 'Russe (Russie)', natif: 'Русский' },
  { code: 'sr-RS', nom: 'Serbe (Serbie)', natif: 'Српски' },
  { code: 'sk-SK', nom: 'Slovaque (Slovaquie)', natif: 'Slovenčina' },
  { code: 'sl-SI', nom: 'Slovène (Slovénie)', natif: 'Slovenščina' },
  { code: 'sv-SE', nom: 'Suédois (Suède)', natif: 'Svenska' },
  { code: 'sw-KE', nom: 'Swahili (Kenya)', natif: 'Kiswahili' },
  { code: 'tl-PH', nom: 'Tagalog (Philippines)', natif: 'Tagalog' },
  { code: 'ta-IN', nom: 'Tamoul (Inde)', natif: 'தமிழ்' },
  { code: 'cs-CZ', nom: 'Tchèque (Tchéquie)', natif: 'Čeština' },
  { code: 'th-TH', nom: 'Thaï (Thaïlande)', natif: 'ไทย' },
  { code: 'tr-TR', nom: 'Turc (Turquie)', natif: 'Türkçe' },
  { code: 'uk-UA', nom: 'Ukrainien (Ukraine)', natif: 'Українська' },
  { code: 'vi-VN', nom: 'Vietnamien (Vietnam)', natif: 'Tiếng Việt' }
]

/** Sans accents ni casse, pour la recherche (les signes diacritiques sont retirés après
 *  décomposition Unicode : « É » → « E », « ç » → « c »). */
function normaliser(s: string): string {
  return s.normalize('NFD').replace(/\p{M}+/gu, '').toLowerCase()
}

const COLLATEUR = new Intl.Collator('fr-CA', { sensitivity: 'base' })
/** Triée par nom français. */
export const LANGUES: Langue[] = [...LANGUES_BRUTES].sort((a, b) => COLLATEUR.compare(a.nom, b.nom))

export function LangueIaScreen({ params }: { params?: Record<string, any> }): JSX.Element {
  void params
  const { settings, updateSettings, toast } = useStore()
  const [recherche, setRecherche] = useState('')

  const langue: string = settings?.language || LANGUE_SYSTEME
  const suivre = !settings?.language || settings.language === LANGUE_SYSTEME

  const choisir = (code: string): void => {
    updateSettings({ language: code }).catch((err) => toast(messageErreur(err), 'error'))
  }

  const visibles = useMemo(() => {
    const q = normaliser(recherche.trim())
    if (!q) return LANGUES
    return LANGUES.filter((l) => normaliser(l.nom).includes(q) || normaliser(l.natif).includes(q) || l.code.toLowerCase().includes(q))
  }, [recherche])

  return (
    <div className="ecran">
      <TopBar titre="Paramètres de langue de l’IA" />
      <div className="contenu">
        <button
          type="button"
          className="carte"
          style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', border: 'none', width: '100%', textAlign: 'left', color: 'var(--text)', cursor: 'pointer' }}
          onClick={() => choisir(LANGUE_SYSTEME)}
          aria-pressed={suivre}
        >
          <span style={{ fontSize: 22, fontWeight: 700 }}>Suivre le système</span>
          {suivre ? <IcoCoche style={{ color: 'var(--blue-2)', width: 28, height: 28 }} /> : null}
        </button>

        <h3 className="section-sous">Sélectionner une autre langue</h3>

        <div className="carte" style={{ padding: '16px 12px 6px' }}>
          <div className="recherche" style={{ margin: '0 4px 8px' }}>
            <IcoRecherche />
            <input
              placeholder="Rechercher une langue"
              value={recherche}
              onChange={(e) => setRecherche(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Escape') {
                  e.preventDefault()
                  setRecherche('')
                }
              }}
            />
          </div>
          {visibles.length === 0 ? <div className="empty">Aucune langue pour «&nbsp;{recherche.trim()}&nbsp;».</div> : null}
          {visibles.map((l) => (
            <Option key={l.code} titre={l.nom} sous={l.natif} actif={!suivre && langue === l.code} onClick={() => choisir(l.code)} />
          ))}
        </div>
        <p className="small muted" style={{ lineHeight: 1.5 }}>
          La langue choisie sert aux réponses écrites et parlées d’IRIS. La reconnaissance vocale hors ligne dépend des modèles installés (Mon profil › Réglages › Voix).
        </p>
      </div>
    </div>
  )
}
