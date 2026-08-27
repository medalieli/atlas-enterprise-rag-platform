import { cookies } from "next/headers";
import { EncryptJWT, jwtDecrypt } from "jose";

export type Session = { accessToken: string; refreshToken?: string; expiresAt: number };
const secure = process.env.NODE_ENV === "production";
const name = secure ? "__Host-rag_session" : "rag_session";
const key = () => {
  const secret = process.env.SESSION_SECRET ?? (process.env.NODE_ENV === "production" ? "" : "development-only-change-me");
  if (secret.length < 32) throw new Error("SESSION_SECRET must contain at least 32 characters");
  return new TextEncoder().encode(secret.slice(0, 32));
};

export async function encode(value: object, ttl = "1h") {
  return new EncryptJWT(value as Record<string, unknown>).setProtectedHeader({ alg: "dir", enc: "A256GCM" }).setIssuedAt().setExpirationTime(ttl).encrypt(key());
}
export async function decode<T>(value?: string): Promise<T | null> {
  if (!value) return null;
  try { return (await jwtDecrypt(value, key())).payload as T; } catch { return null; }
}
export async function getSession() { return decode<Session>((await cookies()).get(name)?.value); }
export async function setSession(session: Session) {
  (await cookies()).set(name, await encode(session, "8h"), { httpOnly: true, secure, sameSite: "lax", path: "/", maxAge: 28800 });
}
export async function clearSession() {
  (await cookies()).set(name, "", {
    httpOnly: true,
    secure,
    sameSite: "lax",
    path: "/",
    maxAge: 0,
  });
}
export const sessionCookieName = name;
