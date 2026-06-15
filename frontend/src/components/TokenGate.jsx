import React, { useState } from "react";
import { useAppState } from "../state/appContext.jsx";

// Shown when the backend requires the remote access token (e.g. the phone
// reaching Odin over Tailscale). The token is read off the Mac (Settings ->
// Remote Access) and entered here once; it is then stored for this device.
export function TokenGate() {
  const { submitToken } = useAppState();
  const [token, setToken] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function handleSubmit(event) {
    event.preventDefault();
    if (!token.trim()) {
      return;
    }
    setBusy(true);
    setError("");
    try {
      await submitToken(token);
    } catch (submitError) {
      setError(
        submitError.status === 401
          ? "That token was not accepted. Check it on your Mac and try again."
          : submitError.message,
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="app-shell token-gate" aria-label="Remote access">
      <form className="token-gate-card" onSubmit={handleSubmit}>
        <h1>O.D.I.N.</h1>
        <p>Enter your remote access token to connect.</p>
        <p className="token-gate-hint">
          Find it on your Mac under Configuration → Remote Access.
        </p>
        <input
          type="password"
          autoComplete="off"
          aria-label="Remote access token"
          placeholder="Access token"
          value={token}
          onChange={(event) => setToken(event.target.value)}
        />
        {error && <p className="error">{error}</p>}
        <button type="submit" disabled={busy || !token.trim()}>
          {busy ? "Connecting…" : "Connect"}
        </button>
      </form>
    </main>
  );
}
