import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'
import { quasar, transformAssetUrls } from '@quasar/vite-plugin'
import { fileURLToPath } from 'node:url'

// https://vitest.dev/config/
export default defineConfig({
  test: {
    environment: 'happy-dom',
    setupFiles: 'test/vitest/setup-file.js',
    include: ['src/**/*.vitest.{js,ts}', 'test/vitest/**/*.{test,spec}.{js,ts}'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'json', 'html', 'cobertura'],
      include: ['src/**'],
    },
  },
  plugins: [
    vue({
      template: { transformAssetUrls },
    }),
    quasar({
      sassVariables: 'src/css/quasar.variables.scss',
    }),
  ],
  resolve: {
    alias: {
      // Quasar CLI resolves '#q-app/*' via package.json subpath imports at build
      // time; map it manually so src/router and src/boot files load under vitest.
      '#q-app/wrappers': '@quasar/app-vite/wrappers',
      src: fileURLToPath(new URL('./src', import.meta.url)),
      boot: fileURLToPath(new URL('./src/boot', import.meta.url)),
      stores: fileURLToPath(new URL('./src/stores', import.meta.url)),
      pages: fileURLToPath(new URL('./src/pages', import.meta.url)),
      components: fileURLToPath(new URL('./src/components', import.meta.url)),
      composables: fileURLToPath(new URL('./src/composables', import.meta.url)),
      layouts: fileURLToPath(new URL('./src/layouts', import.meta.url)),
      assets: fileURLToPath(new URL('./src/assets', import.meta.url)),
    },
  },
})
