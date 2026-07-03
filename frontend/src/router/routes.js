const routes = [
  // Installation route (no auth required, only available before first user)
  {
    path: '/install',
    component: () => import('layouts/EmptyLayout.vue'),
    meta: { requiresAuth: false },
    children: [
      {
        path: '',
        component: () => import('pages/auth/InstallPage.vue'),
        meta: { requiresAuth: false },
      },
    ],
  },
  // Authentication routes (no auth required)
  {
    path: '/auth',
    component: () => import('layouts/EmptyLayout.vue'),
    meta: { requiresAuth: false },
    children: [
      {
        path: 'login',
        component: () => import('pages/auth/LoginPage.vue'),
        meta: { requiresAuth: false },
      },
      {
        path: 'callback',
        component: () => import('pages/auth/CallbackPage.vue'),
        meta: { requiresAuth: false },
      },
      {
        path: 'register/:token',
        component: () => import('pages/auth/RegisterPage.vue'),
        meta: { requiresAuth: false },
      },
      {
        path: 'forgot-password',
        component: () => import('pages/auth/ForgotPasswordPage.vue'),
        meta: { requiresAuth: false },
      },
      {
        path: 'verify-email',
        component: () => import('pages/auth/VerifyEmailPage.vue'),
        meta: { requiresAuth: false },
      },
      {
        path: 'reset-password',
        component: () => import('pages/auth/ResetPasswordPage.vue'),
        meta: { requiresAuth: false },
      },
    ],
  },
  // Public registration route with invite token as query parameter
  {
    path: '/register',
    component: () => import('layouts/EmptyLayout.vue'),
    meta: { requiresAuth: false },
    children: [
      {
        path: '',
        component: () => import('pages/auth/RegisterPage.vue'),
        meta: { requiresAuth: false },
      },
    ],
  },

  // Main application routes (auth required)
  {
    path: '/',
    component: () => import('layouts/MainLayout.vue'),
    meta: { requiresAuth: true },
    children: [
      {
        path: '',
        component: () => import('pages/MediaListPage.vue'),
        meta: { requiresAuth: true, isHome: true },
      },
      {
        path: '/favorites',
        component: () => import('pages/FavoritesPage.vue'),
        meta: { requiresAuth: true },
      },
      {
        path: '/history',
        component: () => import('pages/ViewingHistoryPage.vue'),
        meta: { requiresAuth: true },
      },
      {
        path: '/membership',
        component: () => import('pages/MembershipPage.vue'),
        meta: { requiresAuth: true },
      },
      {
        path: '/friends',
        component: () => import('pages/FriendsPage.vue'),
        meta: { requiresAuth: true },
      },
      {
        path: '/invite-a-friend',
        component: () => import('pages/InviteFriendsPage.vue'),
        meta: { requiresAuth: true },
      },
      {
        path: '/play/:id',
        name: 'play',
        component: () => import('pages/PlayPage.vue'),
        meta: { requiresAuth: true },
      },

      // Central media detail page — /media/:guid
      {
        path: '/media/:guid',
        name: 'media-detail',
        component: () => import('pages/MediaDetailPage.vue'),
        meta: { requiresAuth: true },
      },
      // Library browse pages — /movies, /shows, /games, /music, /books
      {
        path: '/:mediaType(movies|shows|games|music|books)',
        component: () => import('pages/MediaListPage.vue'),
        meta: { requiresAuth: true },
      },
      {
        path: '/lists/:guid',
        component: () => import('pages/ListPage.vue'),
        meta: { requiresAuth: true },
      },
      {
        path: '/playlists/:guid',
        component: () => import('pages/ListPage.vue'),
      },
      {
        path: '/settings',
        component: () => import('pages/UserSettingsPage.vue'),
        meta: { requiresAuth: true },
      },
      {
        path: '/search',
        component: () => import('pages/SearchResultsPage.vue'),
        meta: { requiresAuth: true },
      },
      {
        path: '/person/:guid',
        name: 'person',
        component: () => import('pages/PersonPage.vue'),
        meta: { requiresAuth: true },
      },
    ],
  },

  // Admin routes
  {
    path: '/admin',
    component: () => import('layouts/AdminLayout.vue'),
    meta: { requiresAuth: true, requiresAdmin: true },
    children: [
      {
        path: '',
        component: () => import('pages/admin/IndexPage.vue'),
      },
      {
        path: 'active-sessions',
        component: () => import('src/pages/admin/SessionsPage.vue'),
      },
      {
        path: 'downloads',
        component: () => import('src/pages/admin/DownloadsPage.vue'),
      },
      {
        path: 'downloaders',
        component: () => import('src/pages/admin/DownloadersPage.vue'),
      },
      {
        path: 'metadata',
        component: () => import('src/pages/admin/MetadataPage.vue'),
      },
      {
        path: 'libraries/create',
        component: () => import('src/pages/admin/CreateLibraryPage.vue'),
      },
      {
        path: 'libraries/:id',
        component: () => import('src/pages/admin/LibrarySettingsPage.vue'),
        props: (route) => ({ libraryId: route.params.id }),
      },
      {
        path: 'transcoding',
        component: () => import('src/pages/admin/TranscodingPage.vue'),
      },
      {
        path: 'logs',
        component: () => import('src/pages/admin/LogsPage.vue'),
      },
      {
        path: 'tasks',
        component: () => import('src/pages/admin/TasksPage.vue'),
      },
      {
        path: 'users',
        component: () => import('src/pages/admin/UsersPage.vue'),
      },
      {
        path: 'users/create',
        component: () => import('src/pages/admin/CreateUserPage.vue'),
      },
      {
        path: 'users/:guid',
        component: () => import('src/pages/admin/UserPage.vue'),
      },
      {
        path: 'users/:guid/edit',
        component: () => import('src/pages/admin/EditUserPage.vue'),
      },
      {
        path: 'groups',
        component: () => import('src/pages/admin/GroupsPage.vue'),
      },
      {
        path: 'groups/create',
        component: () => import('src/pages/admin/EditGroupPage.vue'),
      },
      {
        path: 'groups/:id/edit',
        component: () => import('src/pages/admin/EditGroupPage.vue'),
      },
      {
        path: 'devices',
        component: () => import('src/pages/admin/DevicesPage.vue'),
      },
      {
        path: 'banners',
        component: () => import('src/pages/admin/BannersPage.vue'),
      },
      {
        path: 'banners/create',
        component: () => import('src/pages/admin/BannerFormPage.vue'),
      },
      {
        path: 'banners/:guid/edit',
        component: () => import('src/pages/admin/BannerFormPage.vue'),
      },
      {
        path: 'invites',
        component: () => import('src/pages/admin/InvitesPage.vue'),
      },
      {
        path: 'lists',
        component: () => import('src/pages/admin/ListsPage.vue'),
      },
      {
        path: 'page-layouts',
        component: () => import('src/pages/admin/PageLayoutsPage.vue'),
      },
      {
        path: 'page-layouts/create',
        component: () => import('src/pages/admin/EditPageLayoutPage.vue'),
      },
      {
        path: 'page-layouts/:guid',
        component: () => import('src/pages/admin/EditPageLayoutPage.vue'),
      },
      {
        path: 'indexers',
        component: () => import('src/pages/admin/IndexersPage.vue'),
      },
      {
        path: 'indexers/create',
        component: () => import('src/pages/admin/IndexerFormPage.vue'),
      },
      {
        path: 'indexers/:guid/edit',
        component: () => import('src/pages/admin/IndexerFormPage.vue'),
      },
      {
        path: 'settings',
        component: () => import('src/pages/admin/SettingsPage.vue'),
      },
      {
        path: 'parties',
        component: () => import('src/pages/admin/PartiesPage.vue'),
      },
      {
        path: 'packages',
        component: () => import('src/pages/admin/PackagesPage.vue'),
      },
      {
        path: 'packages/create',
        component: () => import('src/pages/admin/EditPackagePage.vue'),
      },
      {
        path: 'packages/:guid/edit',
        component: () => import('src/pages/admin/EditPackagePage.vue'),
      },
      {
        path: 'vouchers',
        component: () => import('src/pages/admin/VouchersPage.vue'),
      },
      {
        path: 'smart-collections',
        component: () => import('src/pages/admin/SmartCollectionsPage.vue'),
      },
      {
        path: 'overlays',
        component: () => import('src/pages/admin/OverlayTemplatesPage.vue'),
      },
      {
        path: 'mass-operations',
        component: () => import('src/pages/admin/MassOperationsPage.vue'),
      },
    ],
  },

  // Always leave this as last one,
  // but you can also remove it
  {
    path: '/:catchAll(.*)*',
    component: () => import('pages/ErrorNotFound.vue'),
    meta: { requiresAuth: true },
  },
]

export default routes
