// ═══════════════════════════════════════════════════════════
// sharktalk 게이트 모듈
//
// 보호할 사이트의 Worker 앞단에 붙여 쓴다.
// 쿠키의 JWT 를 로컬에서 검증하고, 없거나 틀리면 로그인으로 보낸다.
//
// 매 요청마다 auth 워커를 부르지 않는다 (JWT_SECRET 공유 + 로컬 검증).
// 대신 KV 를 바인딩해 두면 계정 비활성화가 즉시 반영된다.
// ═══════════════════════════════════════════════════════════

const COOKIE_NAME = "st_session";
const LOGIN_URL = "https://auth.sharktalk.co.kr/login";

function readCookie(request, name) {
  const raw = request.headers.get("Cookie");
  if (!raw) return null;
  for (const part of raw.split(";")) {
    const idx = part.indexOf("=");
    if (idx < 0) continue;
    if (part.slice(0, idx).trim() === name) return part.slice(idx + 1).trim();
  }
  return null;
}

function b64urlToStr(b64) {
  const binary = atob(b64.replace(/-/g, "+").replace(/_/g, "/"));
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return new TextDecoder().decode(bytes);
}

function b64urlToBytes(b64) {
  const binary = atob(b64.replace(/-/g, "+").replace(/_/g, "/"));
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

async function verifyJWT(token, secret) {
  const parts = token.split(".");
  if (parts.length !== 3) throw new Error("format");
  const data = `${parts[0]}.${parts[1]}`;
  const key = await crypto.subtle.importKey(
    "raw", new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" }, false, ["verify"]
  );
  const ok = await crypto.subtle.verify(
    "HMAC", key, b64urlToBytes(parts[2]), new TextEncoder().encode(data)
  );
  if (!ok) throw new Error("signature");
  const payload = JSON.parse(b64urlToStr(parts[1]));
  if (payload.exp < Date.now() / 1000) throw new Error("expired");
  return payload;
}

/**
 * 요청자를 확인한다. 통과하면 payload, 아니면 null.
 * env.AUTH (KV) 가 있으면 계정 active 여부까지 확인한다.
 */
export async function authenticate(request, env) {
  const token = readCookie(request, COOKIE_NAME);
  if (!token) return null;
  try {
    const payload = await verifyJWT(token, env.JWT_SECRET);
    if (env.AUTH) {
      const raw = await env.AUTH.get(`user:${payload.sub}`);
      if (!raw) return null;
      if (!JSON.parse(raw).active) return null;
    }
    return payload;
  } catch {
    return null;
  }
}

/**
 * 막혔을 때의 응답.
 * 문서 요청이면 로그인 화면으로 리다이렉트(원래 주소를 next 로 전달),
 * 그 외(fetch·이미지·데이터)는 401 JSON.
 */
export function denied(request) {
  const accept = request.headers.get("Accept") || "";
  if (request.method === "GET" && accept.includes("text/html")) {
    const next = encodeURIComponent(request.url);
    return Response.redirect(`${LOGIN_URL}?next=${next}`, 302);
  }
  return new Response(JSON.stringify({ error: "인증이 필요합니다" }), {
    status: 401,
    headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" },
  });
}

/**
 * 정적 자산 Worker 를 통째로 보호하는 기본 핸들러.
 *
 *   import { guardAssets } from "./shared/gate.js";
 *   export default { fetch: guardAssets };
 *
 * 인증을 통과하면 env.ASSETS 로 넘겨 원래 파일을 서빙한다.
 */
export async function guardAssets(request, env, ctx) {
  const user = await authenticate(request, env);
  if (!user) return denied(request);

  const res = await env.ASSETS.fetch(request);
  // 보호된 내용이 중간 캐시에 남지 않도록
  const headers = new Headers(res.headers);
  headers.set("Cache-Control", "private, no-store");
  headers.set("X-Robots-Tag", "noindex, nofollow");
  return new Response(res.body, { status: res.status, headers });
}
