import { afterEach, describe, expect, it, vi } from "vitest";

import {
  getMusicProviderConfig,
  setMusicProviderConfig,
  type MusicProviderConfig,
} from "@/api/config";
import { CONFIG_MUSIC_PROVIDER_PATH } from "@/api/constants";

describe("Music Provider Config API", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("reads music provider config successfully", async () => {
    const payload: MusicProviderConfig = {
      activeProvider: "elevenlabs_music",
      defaultProvider: "elevenlabs_music",
      availableProviders: ["elevenlabs_music", "gemini_music"],
    };

    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(payload), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await getMusicProviderConfig();
    expect(result.ok).toBe(true);
    if (!result.ok) return;

    expect(result.data.activeProvider).toBe("elevenlabs_music");
    expect(result.data.defaultProvider).toBe("elevenlabs_music");
    expect(result.data.availableProviders).toEqual(["elevenlabs_music", "gemini_music"]);

    expect(fetchMock).toHaveBeenCalledWith(
      CONFIG_MUSIC_PROVIDER_PATH,
      expect.objectContaining({
        method: "GET",
      }),
    );
  });

  it("switches music provider successfully with reason payload", async () => {
    const responsePayload: MusicProviderConfig = {
      activeProvider: "gemini_music",
      defaultProvider: "elevenlabs_music",
      availableProviders: ["elevenlabs_music", "gemini_music"],
    };

    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(responsePayload), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await setMusicProviderConfig({
      provider: "gemini_music",
      reasonCode: "routine_ops",
      reasonRef: "OPS-1234",
      reasonText: "Switching to Gemini for quality testing",
    });

    expect(result.ok).toBe(true);
    if (!result.ok) return;

    expect(result.data.activeProvider).toBe("gemini_music");
    expect(fetchMock).toHaveBeenCalledWith(
      CONFIG_MUSIC_PROVIDER_PATH,
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          provider: "gemini_music",
          reasonCode: "routine_ops",
          reasonRef: "OPS-1234",
          reasonText: "Switching to Gemini for quality testing",
        }),
      }),
    );
  });

  it("reports schema drift when required fields are missing", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ activeProvider: "gemini_music" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await getMusicProviderConfig();
    expect(result.ok).toBe(false);
    if (result.ok) return;

    expect(result.code).toBe("SCHEMA_DRIFT");
  });
});

describe("Teachers Day Config API", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("reads teachers day config successfully", async () => {
    const payload = {
      enabled: true,
      discountPercent: 30,
    };

    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(payload), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const { getTeachersDayConfig } = await import("@/api/config");
    const { CONFIG_TEACHERS_DAY_PATH } = await import("@/api/constants");

    const result = await getTeachersDayConfig();
    expect(result.ok).toBe(true);
    if (!result.ok) return;

    expect(result.data.enabled).toBe(true);
    expect(result.data.discountPercent).toBe(30);

    expect(fetchMock).toHaveBeenCalledWith(
      CONFIG_TEACHERS_DAY_PATH,
      expect.objectContaining({
        method: "GET",
      }),
    );
  });

  it("switches teachers day config successfully with reason payload", async () => {
    const responsePayload = {
      enabled: false,
      discountPercent: 30,
    };

    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(responsePayload), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const { setTeachersDayConfig } = await import("@/api/config");
    const { CONFIG_TEACHERS_DAY_PATH } = await import("@/api/constants");

    const result = await setTeachersDayConfig({
      enabled: false,
      reasonCode: "routine_ops",
      reasonRef: "OPS-5678",
      reasonText: "Disabling Teachers Day promo",
    });

    expect(result.ok).toBe(true);
    if (!result.ok) return;

    expect(result.data.enabled).toBe(false);
    expect(fetchMock).toHaveBeenCalledWith(
      CONFIG_TEACHERS_DAY_PATH,
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          enabled: false,
          reasonCode: "routine_ops",
          reasonRef: "OPS-5678",
          reasonText: "Disabling Teachers Day promo",
        }),
      }),
    );
  });
});


describe("Checkout Rails Config API", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  function respond(payload: unknown, status = 200): ReturnType<typeof vi.fn> {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(payload), {
        status,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    return fetchMock;
  }

  it("reads the rails, keeping an unknown `wired` as null rather than false", async () => {
    const { getCheckoutRails } = await import("@/api/config");
    const { CONFIG_CHECKOUT_RAILS_PATH } = await import("@/api/constants");
    const fetchMock = respond({
      rails: [
        { name: "rhmt", enabled: true, wired: null },
        { name: "payme", enabled: false, wired: null },
        { name: "checkoutuz", enabled: true, wired: null },
      ],
      wiredKnown: false,
    });

    const result = await getCheckoutRails();
    expect(result.ok).toBe(true);
    if (!result.ok) return;

    expect(result.data.wiredKnown).toBe(false);
    expect(result.data.rails.map((r) => r.name)).toEqual(["rhmt", "payme", "checkoutuz"]);
    expect(result.data.rails[1]?.enabled).toBe(false);
    expect(result.data.rails[0]?.wired).toBeNull();
    expect(fetchMock).toHaveBeenCalledWith(
      CONFIG_CHECKOUT_RAILS_PATH,
      expect.objectContaining({ method: "GET" }),
    );
  });

  it("posts {rail, enabled} with the reason fields and returns the re-read view", async () => {
    const { setCheckoutRail } = await import("@/api/config");
    const { CONFIG_CHECKOUT_RAILS_PATH } = await import("@/api/constants");
    const fetchMock = respond({
      rails: [{ name: "checkoutuz", enabled: false, wired: true }],
      wiredKnown: true,
    });

    const result = await setCheckoutRail({
      rail: "checkoutuz",
      enabled: false,
      reasonCode: "routine_ops",
    });

    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.data.rails[0]?.enabled).toBe(false);
    expect(fetchMock).toHaveBeenCalledWith(
      CONFIG_CHECKOUT_RAILS_PATH,
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ rail: "checkoutuz", enabled: false, reasonCode: "routine_ops" }),
      }),
    );
  });

  it("reports schema drift when the server sends snake_case", async () => {
    const { getCheckoutRails } = await import("@/api/config");
    respond({ rails: [], wired_known: true });

    const result = await getCheckoutRails();
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.code).toBe("SCHEMA_DRIFT");
  });
});
