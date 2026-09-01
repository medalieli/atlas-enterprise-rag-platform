// @vitest-environment node
import { afterEach, describe, expect, it } from "vitest";
import { NextRequest } from "next/server";
import { proxy } from "@/proxy";

describe("demo-only administration routes", () => {
  const original = process.env.DEMO_ROLE_PREVIEW_ENABLED;
  afterEach(() => {
    if (original === undefined) delete process.env.DEMO_ROLE_PREVIEW_ENABLED;
    else process.env.DEMO_ROLE_PREVIEW_ENABLED = original;
  });

  it.each(["/admin/members", "/admin/invitations"])(
    "returns 404 for %s only while demo preview is enabled",
    (path) => {
      process.env.DEMO_ROLE_PREVIEW_ENABLED = "true";
      expect(proxy(new NextRequest(`http://localhost${path}`)).status).toBe(404);
      process.env.DEMO_ROLE_PREVIEW_ENABLED = "false";
      expect(proxy(new NextRequest(`http://localhost${path}`)).status).not.toBe(404);
    },
  );
});

describe("public brand assets", () => {
  it("serves the Atlas logo without requiring an authenticated session", () => {
    const response = proxy(new NextRequest("http://localhost/atlas-logo.svg"));
    expect(response.status).toBe(200);
    expect(response.headers.get("location")).toBeNull();
  });
});
