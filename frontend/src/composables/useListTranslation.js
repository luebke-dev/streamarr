import { useI18n } from 'vue-i18n'

/**
 * Returns the localized name/description for a list object,
 * falling back to the default name/description fields.
 * System list types (FAVORITES) use i18n keys automatically.
 */
export function useListTranslation() {
  const { locale, t } = useI18n()

  // Built-in localized names for system list types
  const systemListNames = {
    FAVORITES: () => t('favorites.title'),
  }

  function getListName(list) {
    if (!list) return ''

    // System lists: use i18n key if no custom translations set
    if (list.list_type && systemListNames[list.list_type] && !list.name_translations) {
      return systemListNames[list.list_type]()
    }

    const tr = list.name_translations
    if (tr) {
      if (tr[locale.value]) return tr[locale.value]
      const lang = locale.value.split('-')[0]
      const match = Object.keys(tr).find((k) => k.startsWith(lang))
      if (match) return tr[match]
    }
    return list.name || ''
  }

  function getListDescription(list) {
    if (!list) return ''
    const tr = list.description_translations
    if (tr) {
      if (tr[locale.value]) return tr[locale.value]
      const lang = locale.value.split('-')[0]
      const match = Object.keys(tr).find((k) => k.startsWith(lang))
      if (match) return tr[match]
    }
    return list.description || ''
  }

  return { getListName, getListDescription }
}
