import { afterEach, describe, expect, it } from "vitest";
import { isSecureRuntime } from "@/lib/runtime";

const previous = process.env.APP_ENV;
afterEach(() => {
  if (previous === undefined) delete process.env.APP_ENV;
  else process.env.APP_ENV = previous;
});

describe("runtime security mode", () => {
  it.each(["development", "test"])("allows explicit %s HTTP test mode", (mode) => {
    process.env.APP_ENV = mode;
    expect(isSecureRuntime()).toBe(false);
  });

  it.each(["production", "invalid", undefined])("fails secure for %s", (mode) => {
    if (mode === undefined) delete process.env.APP_ENV;
    else process.env.APP_ENV = mode;
    expect(isSecureRuntime()).toBe(true);
  });
});
