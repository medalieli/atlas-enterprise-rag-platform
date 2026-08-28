import { describe, expect, it } from "vitest";

import { bffSpan, injectTrace } from "@/lib/telemetry";

describe("BFF telemetry", () => {
  it("does not invent trace headers when telemetry has no active context", () => {
    const headers = new Headers({ authorization: "Bearer browser-test-value" });
    injectTrace(headers);
    expect(headers.get("authorization")).toBe("Bearer browser-test-value");
    expect([...headers]).toEqual([["authorization", "Bearer browser-test-value"]]);
  });

  it("does not change request outcomes when export is disabled", async () => {
    await expect(bffSpan(async () => "ok")).resolves.toBe("ok");
    await expect(bffSpan(async () => Promise.reject(new Error("safe")))).rejects.toThrow(
      "safe",
    );
  });
});
