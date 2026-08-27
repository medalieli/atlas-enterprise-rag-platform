// @vitest-environment node
import { describe, expect, it } from "vitest";
import { decode, encode } from "@/lib/session";
describe("server session envelope",()=>{it("round trips encrypted token material",async()=>{const value=await encode({accessToken:"not-browser-readable",expiresAt:1});expect(value).not.toContain("not-browser-readable");expect(await decode<{accessToken:string}>(value)).toMatchObject({accessToken:"not-browser-readable"});});it("rejects tampering",async()=>{expect(await decode("invalid")).toBeNull();});});
