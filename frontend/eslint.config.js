import js from '@eslint/js'
import globals from 'globals'
import pluginVue from 'eslint-plugin-vue'
import pluginQuasar from '@quasar/app-vite/eslint'
import prettierSkipFormatting from '@vue/eslint-config-prettier/skip-formatting'

export default [
  {
    /**
     * Ignore the following files.
     * Please note that pluginQuasar.configs.recommended() already ignores
     * the "node_modules" folder for you (and all other Quasar project
     * relevant folders and files).
     *
     * ESLint requires "ignores" key to be the only one in this object
     */
    ignores: ['src-tauri/target/**', 'src-tauri/gen/**'],
  },

  ...pluginQuasar.configs.recommended(),
  js.configs.recommended,

  /**
   * https://eslint.vuejs.org
   *
   * pluginVue.configs.base
   *   -> Settings and rules to enable correct ESLint parsing.
   * pluginVue.configs[ 'flat/essential']
   *   -> base, plus rules to prevent errors or unintended behavior.
   * pluginVue.configs["flat/strongly-recommended"]
   *   -> Above, plus rules to considerably improve code readability and/or dev experience.
   * pluginVue.configs["flat/recommended"]
   *   -> Above, plus rules to enforce subjective community defaults to ensure consistency.
   */
  ...pluginVue.configs['flat/essential'],

  {
    languageOptions: {
      ecmaVersion: 'latest',
      sourceType: 'module',

      globals: {
        ...globals.browser,
        ...globals.node, // SSR, Tauri, config files
        process: 'readonly', // process.env.*
        ga: 'readonly', // Google Analytics
        cordova: 'readonly',
        Capacitor: 'readonly',
        chrome: 'readonly', // BEX related
        browser: 'readonly', // BEX related
      },
    },

    // add your custom rules here
    rules: {
      'prefer-promise-reject-errors': 'off',

      // allow debugger during development only
      'no-debugger': process.env.NODE_ENV === 'production' ? 'error' : 'off',

      // Consolidate the data layer: raw `api`/axios access should flow through
      // useUnifiedMedia / useSectionData / a service, not `boot/axios` directly.
      // `warn` (not error) so the large body of existing call sites stays green
      // while new violations surface in review.
      'no-restricted-imports': [
        'warn',
        {
          patterns: [
            {
              group: ['boot/axios', 'src/boot/axios'],
              message:
                'Do not import boot/axios directly. Use useUnifiedMedia / useSectionData / useApiResponseCache or a service in src/services instead.',
            },
          ],
        },
      ],
    },
  },

  {
    // Data-layer / boot files are allowed to import boot/axios directly.
    files: [
      'src/services/**',
      'src/composables/useUnifiedMedia.js',
      'src/composables/useSectionData.js',
      'src/composables/useApiResponseCache.js',
      'src/boot/**',
    ],
    rules: {
      'no-restricted-imports': 'off',
    },
  },

  {
    files: ['src-pwa/custom-service-worker.js'],
    languageOptions: {
      globals: {
        ...globals.serviceworker,
      },
    },
  },

  prettierSkipFormatting,
]
