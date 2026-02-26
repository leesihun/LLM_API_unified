declare global {
  interface Window {
    electronAPI?: {
      showNotification: (title: string, body: string) => void;
      flashWindow: () => void;
    };
  }
}

export function requestNotificationPermission() {
  if (!window.electronAPI && 'Notification' in window && Notification.permission === 'default') {
    Notification.requestPermission();
  }
}

export function showNotification(title: string, body: string) {
  if (window.electronAPI) {
    window.electronAPI.showNotification(title, body);
    window.electronAPI.flashWindow();
    return;
  }

  if ('Notification' in window && Notification.permission === 'granted') {
    new Notification(title, { body });
  }
}

export function isWebMode(): boolean {
  return !window.electronAPI;
}
