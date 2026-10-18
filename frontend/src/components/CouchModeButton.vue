<!--
  CouchModeButton — the couch interface's entry point in the toolbar.

  Desktop only. A browser build has no controller, no shell and no window to make
  fullscreen, so the button would be a control that cannot work; `v-if` rather
  than disabling it keeps the web interface unchanged.

  Entering the mode does not navigate anywhere. Couch mode is a *way of driving*
  the interface that is already there — the arrow keys and the controller move the
  focus, Enter opens what is focused. That is why this is a button and a focus
  highlight rather than a separate page: a "big picture" route would be a second
  implementation of every list in the app.
-->
<template>
  <q-btn
    v-if="isSupported"
    flat
    dense
    round
    :icon="active ? 'mdi-sofa' : 'mdi-sofa-outline'"
    :color="active ? 'primary' : 'grey-7'"
    :aria-label="active ? $t('couch.exit') : $t('couch.enter')"
    :aria-pressed="active"
    @click="toggle"
  >
    <q-tooltip>
      {{ active ? $t('couch.exit') : $t('couch.enter') }}
    </q-tooltip>
  </q-btn>

  <!--
    Announced to a screen reader rather than only shown: couch mode is a change
    of *how* the interface reacts, which is invisible until a key is pressed.
  -->
  <span v-if="active" class="sr-only" role="status">{{ $t('couch.status') }}</span>

  <!--
    The controller is named when there is one and reported as missing when there
    is not. A user pressing a controller's buttons with no effect needs to know
    which of the two it is — the keyboard path works either way, and the hint
    says so.
  -->
  <span v-if="active" class="sr-only" role="status">
    {{ pads > 0 ? $t('couch.controllers', { count: pads }) : $t('couch.noController') }}
  </span>
</template>

<script setup>
import { onBeforeUnmount } from 'vue'
import { useCouchMode } from 'src/composables/useCouchMode'

const { active, pads, isSupported, toggle } = useCouchMode()

// Leaving the page leaves the mode: a focus highlight on a view that is gone is
// a state the user cannot see and did not ask for.
onBeforeUnmount(() => {
  if (active.value) toggle()
})
</script>

<style scoped>
/* Visible to assistive technology only. Not `display: none`, which would remove
   it from the accessibility tree as well. */
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}
</style>
