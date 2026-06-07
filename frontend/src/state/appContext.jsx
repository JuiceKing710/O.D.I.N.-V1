import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { fetchSettings, updateSettings } from "../ipc/apiClient.js";

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
  const startNewConversation = useCallback(() => {
    setConversationId(null);
  }, []);

  const refreshSettings = useCallback(async () => {
    setSettingsLoading(true);
    setSettingsError("");
    try {
      const nextSettings = await fetchSettings();
      setSettings(nextSettings);
      return nextSettings;
    } catch (error) {
      setSettingsError(error.message);
      throw error;
    } finally {
      setSettingsLoading(false);
    }
  }, []);

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
    }),
    [
      conversationId,
      currentUser,
      refreshSettings,
      saveSettings,
      settings,
      settingsError,
      settingsLoading,
      startNewConversation,
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
