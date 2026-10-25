export const NOTIFICATION_EVENT = "weatheriq-alert-preferences";
export const NOTIFICATION_PERMISSION_EVENT = "weatheriq-notification-permission";

export function subscribeNotificationPreferences(listener: () => void) {
  window.addEventListener("storage", listener);
  window.addEventListener(NOTIFICATION_EVENT, listener);
  return () => {
    window.removeEventListener("storage", listener);
    window.removeEventListener(NOTIFICATION_EVENT, listener);
  };
}

export function updateNotificationPreference(key: string, value: string) {
  window.localStorage.setItem(key, value);
  window.dispatchEvent(new Event(NOTIFICATION_EVENT));
}

export function subscribeNotificationPermission(listener: () => void) {
  window.addEventListener("focus", listener);
  document.addEventListener("visibilitychange", listener);
  window.addEventListener(NOTIFICATION_PERMISSION_EVENT, listener);
  return () => {
    window.removeEventListener("focus", listener);
    document.removeEventListener("visibilitychange", listener);
    window.removeEventListener(NOTIFICATION_PERMISSION_EVENT, listener);
  };
}

export function getNotificationPermission(): NotificationPermission | "unsupported" {
  return typeof Notification === "undefined" ? "unsupported" : Notification.permission;
}
