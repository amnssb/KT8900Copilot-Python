// Cloudflare Worker: control-plane only (API proxy + runtime config).
// Data-plane (voice WebSocket) is direct from browser to backend tunnel.

const DEFAULT_FRONTEND_ORIGIN = "https://example.pages.dev";
const DEFAULT_API_ORIGIN = "https://radio-admin.example.com";
const DEFAULT_WS_URL = "wss://radio-data.example.com";

function getSettings(env) {
  return {
    frontendOrigin: (env.FRONTEND_ORIGIN || DEFAULT_FRONTEND_ORIGIN).replace(/\/$/, ""),
    apiOrigin: (env.API_ORIGIN || DEFAULT_API_ORIGIN).replace(/\/$/, ""),
    wsUrl: env.WS_URL || DEFAULT_WS_URL,
    clientId: env.CLIENT_ID || "kt8900copilot",
    passkey: env.PASSKEY || "your-secret-passkey",
  };
}

function withCors(headers) {
  headers.set("access-control-allow-origin", "*");
  headers.set("access-control-allow-methods", "GET,POST,PUT,DELETE,OPTIONS");
  headers.set("access-control-allow-headers", "content-type,authorization");
  return headers;
}

function jsonResponse(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: withCors(new Headers({
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
    })),
  });
}

async function proxyToApi(request, settings, url) {
  const target = new URL(url.pathname + url.search, settings.apiOrigin);
  const upstream = await fetch(target.toString(), {
    method: request.method,
    headers: request.headers,
    body: request.body,
  });

  const headers = withCors(new Headers(upstream.headers));
  return new Response(upstream.body, {
    status: upstream.status,
    headers,
  });
}

async function proxyToFrontend(request, settings, url) {
  const target = new URL(url.pathname + url.search, settings.frontendOrigin);
  return fetch(target.toString(), {
    method: request.method,
    headers: request.headers,
    body: request.body,
  });
}

export default {
  async fetch(request, env) {
    const settings = getSettings(env);
    const url = new URL(request.url);

    if (request.method === "OPTIONS" && url.pathname.startsWith("/api/")) {
      return new Response(null, {
        status: 204,
        headers: withCors(new Headers()),
      });
    }

    if (url.pathname === "/healthz") {
      return jsonResponse({
        ok: true,
        service: "kt8900-worker",
        mode: "control-plane",
      });
    }

    if (url.pathname === "/config.js") {
      const clientId = settings.clientId;
      const passkey = settings.passkey;
      if (clientId === "admin") {
        return jsonResponse(
          {
            error: "unsafe default",
            hint: "Do not expose admin credentials in APP_CONFIG. Use low-privilege client ID.",
          },
          500,
        );
      }
      const js = `window.APP_CONFIG = {
  CLIENT_ID: ${JSON.stringify(clientId)},
  PASSKEY: ${JSON.stringify(passkey)},
  WS_URL: ${JSON.stringify(settings.wsUrl)},
  API_BASE: "/api"
};`;
      return new Response(js, {
        headers: new Headers({
          "content-type": "application/javascript; charset=utf-8",
          "cache-control": "no-store",
        }),
      });
    }

    if (url.pathname.startsWith("/api/")) {
      return proxyToApi(request, settings, url);
    }

    if (request.headers.get("upgrade")?.toLowerCase() === "websocket") {
      return jsonResponse(
        {
          error: "WebSocket is not proxied by worker",
          hint: "Frontend must connect directly to APP_CONFIG.WS_URL",
        },
        426,
      );
    }

    return proxyToFrontend(request, settings, url);
  },
};
