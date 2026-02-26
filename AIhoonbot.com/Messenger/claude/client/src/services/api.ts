import axios from 'axios';

let baseURL = 'http://localhost:3000';

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
