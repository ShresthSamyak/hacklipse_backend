interface EnvConfig {
  NODE_ENV: string
  API_BASE_URL: string
  APP_VERSION: string
}

export const env: EnvConfig = {
  NODE_ENV: import.meta.env.MODE || 'development',
  API_BASE_URL: import.meta.env.VITE_API_BASE_URL || 'http://localhost:3001',
  APP_VERSION: '1.0.0',
}
