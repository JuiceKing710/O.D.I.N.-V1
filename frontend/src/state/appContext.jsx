import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { fetchSettings, setAuthToken, updateSettings } from "../ipc/apiClient.js";

const DEFAULT_USER = {
  displayName: "Local User",
  username: "local-user",
};

const AppStateContext = createContext(null);

export function AppStateProvider({ children }) {
  const [conversationId, setConversationId] = useState(null);
  const [currentUser, setCurrentUser] = useState(DEFAULT_USER);
  const [settings, setSettings] = useState(null);
  const [settingsError, setSettingsError] = useState("");
  const [settingsLoading, setSettingsLoading] = useState(true);
  const [authRequired, setAuthRequired] = useState(false);
  const startNewConversation = useCallback(() => {
    setConversationId(null);
  }, []);

  const refreshSettings = useCallback(async () => {
    setSettingsLoading(true);
    setSettingsError("");
    try {
      const nextSettings = await fetchSettings();
      setSettings(nextSettings);
      setAuthRequired(false);
      return nextSettings;
    } catch (error) {
      // A 401 means the backend wants the remote access token (phone over
      // Tailscale); surface a token prompt instead of a generic error.
      if (error.status === 401) {
        setAuthRequired(true);
      }
      setSettingsError(error.message);
      throw error;
    } finally {
      setSettingsLoading(false);
    }
  }, []);

  const submitToken = useCallback(
    async (token) => {
      setAuthToken(token.trim());
      return refreshSettings();
    },
    [refreshSettings],
  );

  const saveSettings = useCallback(async (patch) => {
    setSettingsLoading(true);
    setSettingsError("");
    try {
      const nextSettings = await updateSettings(patch);
      setSettings(nextSettings);
      return nextSettings;
    } catch (error) {
      setSettingsError(error.message);
      throw error;
    } finally {
      setSettingsLoading(false);
    }
  }, []);

  useEffect(() => {
    refreshSettings().catch(() => {
      // Consumers render settingsError; startup should keep the app shell usable.
    });
  }, [refreshSettings]);

  useEffect(() => {
    document.documentElement.dataset.theme = settings?.theme || "system";
  }, [settings?.theme]);

  const value = useMemo(
    () => ({
      authRequired,
      conversationId,
      currentUser,
      refreshSettings,
      saveSettings,
      setConversationId,
      setCurrentUser,
      settings,
      settingsError,
      settingsLoading,
      startNewConversation,
      submitToken,
    }),
    [
      authRequired,
      conversationId,
      currentUser,
      refreshSettings,
      saveSettings,
      settings,
      settingsError,
      settingsLoading,
      startNewConversation,
      submitToken,
    ],
  );

  return <AppStateContext.Provider value={value}>{children}</AppStateContext.Provider>;
}

export function useAppState() {
  const context = useContext(AppStateContext);
  if (!context) {
    throw new Error("useAppState must be used within AppStateProvider");
  }
  return context;
}
