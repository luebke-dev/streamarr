import { getItemType, getMediaImageUrl, formatYear } from 'src/composables/useMediaFormatters'

export function useMediaSection() {
  function getPosterUrl(item) {
    return getMediaImageUrl(item, { preferBackdrop: false })
  }

  function getItemSubtitle(item) {
    return formatYear(item.release_date || item.first_air_date)
  }

  return { getItemType, getPosterUrl, getItemSubtitle }
}
