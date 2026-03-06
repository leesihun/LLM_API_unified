import axios from 'axios';

function getDefaultBaseUrl(): string {
  const saved = localStorage.getItem('huni_server_url');
  if (saved && saved.trim()) {
    return saved.replace(/\/$/, '');
  }
  if (typeof window !== 'undefined' && window.location?.origin) {
    return window.location.origin.replace(/\/$/, '');
  }
  return 'http://localhost:3000';
}

let baseURL = getDefaultBaseUrl();

export function setServerUrl(url: string) {
  baseURL = url.replace(/\/$/, '');
  api.defaults.baseURL = baseURL;
}

export function getServerUrl() {
  return baseURL;
}

/**
 * Returns the base URL to use for file uploads.
 *
 * In Vite dev mode, VITE_BACKEND_URL is injected from .env.development so
 * uploads bypass the Vite dev proxy and go directly to Express.
 * The Vite proxy has known issues stalling large multipart/form-data requests.
 *
 * In production (built app) VITE_BACKEND_URL is undefined so this falls back
 * to the normal baseURL (the user-configured server URL).
 */
export function getUploadBaseUrl(): string {
  const devBackend = (import.meta as any).env?.VITE_BACKEND_URL as string | undefined;
  if (devBackend) {
    return devBackend.replace(/\/$/, '');
  }
  return baseURL;
}

const api = axios.create({
  baseURL,
  timeout: 0,
});

export default api;
