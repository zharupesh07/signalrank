import { NextRequest } from "next/server";

const HOP_BY_HOP_HEADERS = new Set([
  "connection",
  "content-encoding",
  "content-length",
  "host",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
]);

function backendOrigin() {
  const raw =
    process.env.BACKEND_URL ??
    process.env.API_URL_SERVER ??
    process.env.NEXT_PUBLIC_API_URL ??
    "http://localhost:8000";
  return raw.replace(/\/+$/, "");
}

function forwardHeaders(request: NextRequest) {
  const headers = new Headers(request.headers);
  for (const header of HOP_BY_HOP_HEADERS) headers.delete(header);
  // Let fetch negotiate encoding itself so we don't forward a decompressed body
  // with stale compression headers back to the browser.
  headers.delete("accept-encoding");
  return headers;
}

async function proxy(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> | { path: string[] } },
) {
  const params = await Promise.resolve(context.params);
  const path = Array.isArray(params.path) ? params.path.join("/") : "";
  const url = new URL(request.url);
  const target = `${backendOrigin()}/${path}${url.search}`;
  const method = request.method.toUpperCase();
  const body =
    method === "GET" || method === "HEAD" ? undefined : await request.arrayBuffer();

  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method,
      headers: forwardHeaders(request),
      body,
      redirect: "manual",
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unknown upstream error";
    return new Response(message, { status: 502, statusText: "Bad Gateway" });
  }

  const headers = new Headers(upstream.headers);
  for (const header of HOP_BY_HOP_HEADERS) headers.delete(header);
  const payload = await upstream.arrayBuffer();

  return new Response(payload, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers,
  });
}

export const dynamic = "force-dynamic";

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
export const OPTIONS = proxy;
export const HEAD = proxy;
