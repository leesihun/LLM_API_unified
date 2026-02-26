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

const api = axios.create({
  baseURL,
  timeout: 30000,
});

export default api;
