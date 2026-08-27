import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, resetCsrfForTests } from "@/lib/api";
describe("central API client", () => {
  afterEach(()=>{vi.unstubAllGlobals();resetCsrfForTests();});
  it("returns typed JSON through the BFF", async()=>{vi.stubGlobal("fetch",vi.fn().mockResolvedValue(new Response(JSON.stringify({id:"c1"}),{status:200,headers:{"content-type":"application/json"}})));expect(await api<{id:string}>("/collections")).toEqual({id:"c1"});});
  it.each([401,403,404,429,500])("maps HTTP %s to ApiError",async status=>{vi.stubGlobal("fetch",vi.fn().mockResolvedValue(new Response(JSON.stringify({detail:"safe"}),{status})));await expect(api("/x")).rejects.toMatchObject({status,message:"safe"});});
  it("maps network failure without leaking request content",async()=>{vi.stubGlobal("fetch",vi.fn().mockRejectedValue(new Error("secret")));await expect(api("/x")).rejects.toEqual(new ApiError(0,"Network unavailable. Check your connection and try again."));});
  it("adds CSRF only to mutations",async()=>{const fetch=vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({token:"csrf"}))).mockResolvedValueOnce(new Response(JSON.stringify({ok:true})));vi.stubGlobal("fetch",fetch);await api("/collections",{method:"POST",body:"{}"});expect(fetch.mock.calls[1][1].headers.get("x-csrf-token")).toBe("csrf");});
});
