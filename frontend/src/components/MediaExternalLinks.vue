<template>
  <div v-if="links.length > 0" class="external-links-section q-mt-lg">
    <h5 class="text-white q-mt-none q-mb-md">{{ $t('mediaDetail.externalLinks') }}</h5>
    <div class="external-links">
      <q-btn
        v-for="link in links"
        :key="`${link.provider}:${link.provider_id}`"
        :label="link.display_name"
        :href="link.url"
        target="_blank"
        rel="noopener noreferrer"
        icon-right="mdi-open-in-new"
        color="blue-grey-7"
        text-color="white"
        no-caps
        dense
      />
    </div>
  </div>
</template>

<script setup>
defineProps({
  links: {
    type: Array,
    default: () => [],
  },
})
</script>

<style lang="scss" scoped>
.external-links {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
</style>
