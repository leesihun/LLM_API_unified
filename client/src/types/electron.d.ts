export {};

declare global {
  interface Window {
    electronAPI?: {
      showNotification: (title: string, body: string) => Promise<void>;
      flashWindow: () => Promise<void>;
    };
  }
}
