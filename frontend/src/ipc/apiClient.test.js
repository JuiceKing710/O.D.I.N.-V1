import { afterEach, describe, expect, it } from "vitest";
import { clearAuthToken, resolveMediaUrl, setAuthToken } from "./apiClient.js";

// Regression guard: browser-loaded media (<img>/<audio> src, download fetch)
// can't send the Authorization header, so when remote auth is on the token must
// ride in the query string — otherwise the phone gets 401 on every image and
// every voice clip even though the chat API itself works.
describe("resolveMediaUrl", () => {
  afterEach(() => {
    clearAuthToken();
    delete globalThis.jarvisDesktop;
  });

  it("leaves the URL untouched when auth is off (no token)", () => {
    clearAuthToken();
    const url = resolveMediaUrl("/api/v1/image/file/cat.png");
    expect(url).toContain("/api/v1/image/file/cat.png");
    expect(url).not.toContain("token=");
  });

  it("appends the stored token so the media request authenticates", () => {
    setAuthToken("s3cret-token");
    const url = new URL(resolveMediaUrl("/api/v1/image/file/cat.png"));
    expect(url.searchParams.get("token")).toBe("s3cret-token");
    expect(url.pathname).toBe("/api/v1/image/file/cat.png");
  });

  it("prefers the desktop-injected token when present", () => {
    globalThis.jarvisDesktop = { apiToken: "desktop-token" };
    const url = new URL(resolveMediaUrl("/api/v1/voice/audio/clip.wav"));
    expect(url.searchParams.get("token")).toBe("desktop-token");
  });
});
