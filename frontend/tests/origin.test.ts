// @vitest-environment node
import { afterEach, describe, expect, it } from "vitest";
import { NextRequest } from "next/server";
import { applicationOrigin } from "@/lib/origin";

const previous = process.env.APP_BASE_URL;
afterEach(() => {
  if (previous === undefined) delete process.env.APP_BASE_URL;
  else process.env.APP_BASE_URL = previous;
});

describe("external application origin", () => {
  it("uses the configured reverse-proxy-safe origin", () => {
    process.env.APP_BASE_URL = "https://knowledge.example.com";
    expect(applicationOrigin(new NextRequest("http://frontend:3000/chat"))).toBe(
      "https://knowledge.example.com",
    );
  });

  it("rejects configured origins containing redirectable components", () => {
    process.env.APP_BASE_URL = "https://knowledge.example.com/unsafe";
    expect(() => applicationOrigin(new NextRequest("http://frontend:3000"))).toThrow(
      /HTTP\(S\) origin/,
    );
  });
});
