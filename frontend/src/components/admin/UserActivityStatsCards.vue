<template>
  <q-card flat bordered>
    <q-card-section>
      <div class="text-h6 q-mb-md">
        <q-icon name="mdi-chart-bar" class="q-mr-sm" color="info" />
        {{ $t('adminUserPage.activityStats') }}
      </div>
      <div class="row q-col-gutter-sm">
        <div class="col-6 col-md-3">
          <q-card flat class="bg-blue-1 text-center q-pa-md">
            <div class="text-h4 text-primary">{{ stats.invites_created }}</div>
            <div class="text-caption">{{ $t('adminUserPage.invitesCreated') }}</div>
          </q-card>
        </div>
        <div class="col-6 col-md-3">
          <q-card flat class="bg-green-1 text-center q-pa-md">
            <div class="text-h4 text-positive">{{ stats.movies_watched }}</div>
            <div class="text-caption">{{ $t('adminUserPage.moviesWatched') }}</div>
          </q-card>
        </div>
        <div class="col-6 col-md-3">
          <q-card flat class="bg-orange-1 text-center q-pa-md">
            <div class="text-h4 text-orange">{{ stats.episodes_watched }}</div>
            <div class="text-caption">{{ $t('adminUserPage.episodesWatched') }}</div>
          </q-card>
        </div>
        <div class="col-6 col-md-3">
          <q-card flat class="bg-purple-1 text-center q-pa-md">
            <div class="text-h4 text-purple">{{ stats.lists_created }}</div>
            <div class="text-caption">{{ $t('adminUserPage.listsCreated') }}</div>
          </q-card>
        </div>
      </div>
    </q-card-section>
  </q-card>
</template>

<script setup>
defineProps({
  stats: {
    type: Object,
    required: true,
  },
})
</script>
