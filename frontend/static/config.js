/**
 * Frontend Configuration
 * Configure the backend API URL here
 */

const CONFIG = {
    // Backend API URL - change this if your backend is running on a different host/port
    API_BASE_URL: 'http://localhost:10007',

    // Request timeout in milliseconds (20 minutes for long-running LLM requests)
    REQUEST_TIMEOUT: 1200000,

    // Alternative configurations for different environments
    // Development: 'http://localhost:1007'
    // Production: 'http://your-server-ip:1007'
    // Or use window.location to auto-detect: `${window.location.protocol}//${window.location.hostname}:1007`
};

// Auto-detect if running on same host but different port
// Uncomment this if you want automatic detection
// CONFIG.API_BASE_URL = `${window.location.protocol}//${window.location.hostname}:8000`;
