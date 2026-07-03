<template>
  <q-btn flat dense round icon="mdi-account-multiple" :aria-label="$t('watchParty.title')">
    <q-badge v-if="partyStore.isInParty" color="primary" floating>
      {{ partyStore.members.length }}
    </q-badge>

    <q-menu @before-show="onMenuOpen">
      <q-list style="min-width: 300px">
        <!-- If in a party, show party info -->
        <template v-if="partyStore.isInParty">
          <q-item-label header>{{ $t('watchParty.activeParty') }}</q-item-label>

          <q-item>
            <q-item-section avatar>
              <q-icon name="mdi-account-group" color="primary" />
            </q-item-section>
            <q-item-section>
              <q-item-label>{{
                partyStore.activeParty?.name || $t('watchParty.unnamed')
              }}</q-item-label>
              <q-item-label caption>
                {{ $t('watchParty.members') }}: {{ partyStore.members.length }}
              </q-item-label>
            </q-item-section>
          </q-item>

          <!-- Party Code -->
          <q-item>
            <q-item-section avatar>
              <q-icon name="mdi-tag" color="grey" />
            </q-item-section>
            <q-item-section>
              <q-item-label caption>{{ $t('watchParty.partyCode') }}</q-item-label>
              <q-item-label class="text-weight-bold text-h6">
                {{ partyStore.partyCode }}
              </q-item-label>
            </q-item-section>
            <q-item-section side>
              <q-btn flat dense round icon="mdi-content-copy" size="sm" @click.stop="copyCode">
                <q-tooltip>{{ $t('watchParty.copyCode') }}</q-tooltip>
              </q-btn>
            </q-item-section>
          </q-item>

          <q-separator />

          <!-- Member List -->
          <q-item-label header
            >{{ $t('watchParty.members') }} ({{ partyStore.members.length }})</q-item-label
          >

          <q-item v-for="member in partyStore.members" :key="member.guid" dense>
            <q-item-section avatar>
              <q-avatar
                :color="member.is_connected ? 'primary' : 'grey'"
                text-color="white"
                size="28px"
              >
                <q-icon name="mdi-account" size="16px" />
              </q-avatar>
            </q-item-section>
            <q-item-section>
              <q-item-label>
                {{ member.username }}
                <q-badge v-if="member.is_host" color="primary" class="q-ml-xs">{{
                  $t('watchParty.host')
                }}</q-badge>
              </q-item-label>
              <q-item-label
                caption
                :class="member.is_connected ? 'text-positive' : 'text-negative'"
              >
                {{
                  member.is_connected ? $t('watchParty.connected') : $t('watchParty.disconnected')
                }}
              </q-item-label>
            </q-item-section>
            <q-item-section side v-if="partyStore.isHost && !member.is_host">
              <q-btn
                flat
                dense
                round
                icon="mdi-account-remove"
                color="negative"
                size="sm"
                @click.stop="kickMember(member)"
              >
                <q-tooltip>{{ $t('watchParty.kickMember') }}</q-tooltip>
              </q-btn>
            </q-item-section>
          </q-item>

          <q-separator />

          <q-item clickable v-close-popup @click="leaveWatchParty">
            <q-item-section avatar>
              <q-icon name="mdi-exit-to-app" color="negative" />
            </q-item-section>
            <q-item-section>
              <q-item-label>{{ $t('watchParty.leaveParty') }}</q-item-label>
            </q-item-section>
          </q-item>
        </template>

        <!-- If not in a party, show create/join options -->
        <template v-else>
          <q-item-label header>{{ $t('watchParty.title') }}</q-item-label>

          <q-item clickable v-close-popup @click="openPartyDialog('create')">
            <q-item-section avatar>
              <q-icon name="mdi-plus-circle" color="primary" />
            </q-item-section>
            <q-item-section>
              <q-item-label>{{ $t('watchParty.create') }}</q-item-label>
              <q-item-label caption>{{ $t('watchParty.createPartyHint') }}</q-item-label>
            </q-item-section>
          </q-item>

          <q-item clickable v-close-popup @click="openPartyDialog('join')">
            <q-item-section avatar>
              <q-icon name="mdi-login" color="primary" />
            </q-item-section>
            <q-item-section>
              <q-item-label>{{ $t('watchParty.join') }}</q-item-label>
              <q-item-label caption>{{ $t('watchParty.joinPartyHint') }}</q-item-label>
            </q-item-section>
          </q-item>

          <!-- Friends' active parties -->
          <template v-if="friendsParties.length > 0">
            <q-separator />
            <q-item-label header>{{ $t('watchParty.friendsParties') }}</q-item-label>

            <q-item
              v-for="party in friendsParties"
              :key="party.guid"
              clickable
              v-close-popup
              @click="joinFriendsParty(party.party_code)"
            >
              <q-item-section avatar>
                <q-icon name="mdi-account-group" color="accent" />
              </q-item-section>
              <q-item-section>
                <q-item-label>{{ party.name || $t('watchParty.unnamed') }}</q-item-label>
                <q-item-label caption>
                  {{ party.owner_name }} · {{ $t('watchParty.members') }}: {{ party.member_count }}
                </q-item-label>
              </q-item-section>
              <q-item-section side>
                <q-btn flat dense round icon="mdi-login" color="primary" size="sm">
                  <q-tooltip>{{ $t('watchParty.join') }}</q-tooltip>
                </q-btn>
              </q-item-section>
            </q-item>
          </template>
        </template>
      </q-list>
    </q-menu>
  </q-btn>
</template>

<script setup>
import { ref, defineAsyncComponent } from 'vue'
import { useQuasar } from 'quasar'
import { useClipboard } from 'src/composables/useClipboard'
import { usePartyStore } from 'stores/party'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { logger } from 'src/utils/logger'

const PartyDialog = defineAsyncComponent(() => import('components/PartyDialog.vue'))

const $q = useQuasar()
const { copy } = useClipboard()
const { t } = useI18n()
const router = useRouter()
const partyStore = usePartyStore()

const friendsParties = ref([])

async function onMenuOpen() {
  if (!partyStore.isInParty) {
    friendsParties.value = await partyStore.fetchFriendsParties()
  } else {
    await partyStore.fetchPartyDetails()
  }
}

function copyCode() {
  const code = partyStore.partyCode
  if (!code) return
  copy(code, {
    successMessage: t('watchParty.codeCopied'),
    errorMessage: t('watchParty.copyError'),
  })
}

async function joinFriendsParty(partyCode) {
  try {
    const partyData = await partyStore.joinParty(partyCode)

    // Navigate to PlayPage if the party has active media
    if (partyData?.media_id) {
      router.push({
        name: 'play',
        params: { id: partyData.media_id },
        query: { type: partyData.media_type || 'movie' },
      })
    }
  } catch (error) {
    logger.error('Failed to join friends party:', error)
  }
}

async function kickMember(member) {
  $q.dialog({
    title: t('watchParty.kickMember'),
    message: t('watchParty.confirmKick', { name: member.username }),
    cancel: t('watchParty.cancel'),
    ok: { label: t('watchParty.kick'), color: 'negative' },
  }).onOk(async () => {
    await partyStore.kickMember(member.user_id)
  })
}

async function leaveWatchParty() {
  try {
    await partyStore.leaveParty()
  } catch (error) {
    logger.error('Failed to leave watch party:', error)
  }
}

function openPartyDialog(initialTab = 'create') {
  $q.dialog({
    component: PartyDialog,
    componentProps: {
      initialTab,
    },
  })
}
</script>
