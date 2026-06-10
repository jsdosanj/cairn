"""Zero-dependency local web dashboard for Cairn.

`cairn web` launches a tiny local web app (bound to 127.0.0.1 by default) so a
non-technical user can see their integrations, test connections, preview a
dry-run sync with a results table, and toggle the native schedule — all without
editing YAML or touching the terminal.

Implementation notes:
  * Standard library only (http.server, json, threading, webbrowser, urllib).
    This keeps it working inside a PyInstaller frozen binary — no Flask/FastAPI.
  * The whole UI is a single embedded HTML/CSS/JS string; no external assets.
  * Light localhost protection: a random session token (os.urandom) is embedded
    in the served page; every /api call must echo it in X-Cairn-Token or get a
    403. This is not real auth — it just deters other local processes / CSRF.
  * Every request handler is wrapped so a handler error returns a JSON 500
    rather than crashing the server.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import os
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

logger = logging.getLogger(__name__)

# --- secret handling --------------------------------------------------------

# Keys that should always be masked when echoing config back to the browser,
# regardless of provider metadata.
_ALWAYS_SECRET = {
    "token",
    "client_secret",
    "api_token",
    "password",
    "api_key",
    "webhook_url",
    "secret",
}

MASK = "********"


def _secret_keys() -> set:
    """Every field key marked secret in provider_meta, plus the literal set."""
    keys = set(_ALWAYS_SECRET)
    try:
        from .provider_meta import all_meta

        for section in all_meta().values():
            for meta in section.values():
                for fld in getattr(meta, "fields", []) or []:
                    if getattr(fld, "secret", False):
                        keys.add(fld.key)
    except Exception:  # noqa: BLE001 - metadata must never block masking
        logger.exception("Could not derive secret keys from provider_meta")
    return keys


def _mask_config(value, secret_keys: set):
    """Recursively copy `value`, masking any secret-named keys."""
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if isinstance(k, str) and k in secret_keys and v not in (None, "", False):
                out[k] = MASK
            else:
                out[k] = _mask_config(v, secret_keys)
        return out
    if isinstance(value, list):
        return [_mask_config(v, secret_keys) for v in value]
    return value


# --- provider metadata serialization ---------------------------------------

def _meta_to_dict() -> dict:
    """Serialize provider_meta.all_meta() into plain JSON-able dicts."""
    from .provider_meta import all_meta

    out: dict = {}
    for section, providers in all_meta().items():
        out[section] = {}
        for key, meta in providers.items():
            out[section][key] = {
                "key": meta.key,
                "display": meta.display,
                "blurb": meta.blurb,
                "note": getattr(meta, "note", "") or "",
                "fields": [
                    {
                        "key": f.key,
                        "label": f.label,
                        "help": getattr(f, "help", "") or "",
                        "secret": bool(getattr(f, "secret", False)),
                        "required": bool(getattr(f, "required", False)),
                        "default": getattr(f, "default", None),
                        "placeholder": getattr(f, "placeholder", "") or "",
                    }
                    for f in (getattr(meta, "fields", []) or [])
                ],
            }
    return out


# --- API handlers (return plain dicts) -------------------------------------

def _api_state(config_path: str) -> dict:
    from .config import enabled_items, load_config

    state: dict = {
        "config_path": config_path,
        "exists": os.path.isfile(config_path),
        "meta": _meta_to_dict(),
    }
    try:
        config = load_config(config_path)
    except Exception as e:  # noqa: BLE001 - no/invalid config is normal
        state["error"] = str(e)
        state["config"] = {}
        state["enabled"] = {"sources": [], "sinks": [], "notifiers": []}
        return state

    secret_keys = _secret_keys()
    state["config"] = _mask_config(config, secret_keys)
    state["enabled"] = {
        "sources": sorted(enabled_items(config, "sources").keys()),
        "sinks": sorted(enabled_items(config, "sinks").keys()),
        "notifiers": sorted(enabled_items(config, "notifiers").keys()),
    }
    return state


def _api_test(body: dict) -> dict:
    from . import health
    from .registry import get_sink_class, get_source_class

    section = (body or {}).get("section")
    key = (body or {}).get("key")
    cfg = (body or {}).get("config") or {}
    if not section or not key:
        return {"ok": False, "message": "Missing section or key."}
    try:
        if section == "sources":
            obj = get_source_class(key)(cfg)
            ok, message = health.probe_source(obj)
        elif section == "sinks":
            obj = get_sink_class(key)(cfg)
            ok, message = health.probe_sink(obj)
        else:
            return {"ok": False, "message": f"Cannot test section '{section}'."}
        return {"ok": bool(ok), "message": message}
    except Exception as e:  # noqa: BLE001 - never raise out of a handler
        return {"ok": False, "message": str(e)[:300]}


def _api_dry_run(config_path: str) -> dict:
    from .config import load_config
    from .orchestrator import Orchestrator

    config = load_config(config_path)
    summary = Orchestrator(config).run(dry_run=True)
    results = [
        {
            "action": r.action,
            "serial": r.serial,
            "identifier": r.identifier,
            "detail": r.detail,
        }
        for r in summary.results[:500]
    ]
    return {
        "summary": {
            "devices_seen": summary.devices_seen,
            "created": summary.created,
            "updated": summary.updated,
            "skipped": summary.skipped,
            "failed": summary.failed,
            "source_errors": dict(summary.source_errors),
        },
        "results": results,
        "truncated": len(summary.results) > 500,
        "text": summary.as_text(),
    }


def _api_schedule_get() -> dict:
    from . import scheduler

    return {"status": scheduler.status()}


def _api_schedule_post(body: dict, config_path: str) -> dict:
    from . import scheduler

    action = (body or {}).get("action")
    try:
        if action == "install":
            interval = int((body or {}).get("interval") or 3600)
            mode = (body or {}).get("mode")
            message = scheduler.install(interval, config_path, mode)
            return {"ok": True, "message": message}
        if action == "uninstall":
            message = scheduler.uninstall()
            return {"ok": True, "message": message}
        return {"ok": False, "message": f"Unknown action: {action!r}."}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "message": str(e)[:300]}


# --- request handler --------------------------------------------------------

def _make_handler(token: str, config_path: str):
    class Handler(BaseHTTPRequestHandler):
        server_version = "Cairn/1.0"

        # Quiet the default noisy stderr logging; route through our logger.
        def log_message(self, fmt, *args):  # noqa: A003
            logger.debug("%s - %s", self.address_string(), fmt % args)

        # -- helpers --
        def _send_json(self, obj, status=200):
            payload = json.dumps(obj).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)

        def _send_html(self, html, status=200):
            payload = html.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)

        def _check_token(self) -> bool:
            return self.headers.get("X-Cairn-Token") == token

        def _read_body(self) -> dict:
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0:
                return {}
            raw = self.rfile.read(length)
            if not raw:
                return {}
            try:
                data = json.loads(raw.decode("utf-8"))
                return data if isinstance(data, dict) else {}
            except Exception:  # noqa: BLE001
                return {}

        # -- routing --
        def do_GET(self):  # noqa: N802
            try:
                path = self.path.split("?", 1)[0]
                if path == "/":
                    self._send_html(PAGE_HTML.replace("__CAIRN_TOKEN__", token))
                    return
                if path.startswith("/api/"):
                    if not self._check_token():
                        self._send_json({"error": "Invalid or missing token."}, 403)
                        return
                    if path == "/api/state":
                        self._send_json(_api_state(config_path))
                        return
                    if path == "/api/schedule":
                        self._send_json(_api_schedule_get())
                        return
                self._send_json({"error": "Not found."}, 404)
            except Exception as e:  # noqa: BLE001
                logger.exception("GET %s failed", self.path)
                self._send_json({"error": str(e)[:300]}, 500)

        def do_POST(self):  # noqa: N802
            try:
                path = self.path.split("?", 1)[0]
                if not path.startswith("/api/"):
                    self._send_json({"error": "Not found."}, 404)
                    return
                if not self._check_token():
                    self._send_json({"error": "Invalid or missing token."}, 403)
                    return
                body = self._read_body()
                if path == "/api/test":
                    self._send_json(_api_test(body))
                    return
                if path == "/api/dry-run":
                    self._send_json(_api_dry_run(config_path))
                    return
                if path == "/api/schedule":
                    self._send_json(_api_schedule_post(body, config_path))
                    return
                self._send_json({"error": "Not found."}, 404)
            except Exception as e:  # noqa: BLE001
                logger.exception("POST %s failed", self.path)
                self._send_json({"error": str(e)[:300]}, 500)

    return Handler


# --- server entrypoint ------------------------------------------------------

def serve(host: str = "127.0.0.1", port: int = 8765, config_path: str = "config.yaml") -> int:
    """Start the dashboard, open a browser, and run until Ctrl-C. Returns 0."""
    token = os.urandom(24).hex()
    config_path = os.path.abspath(config_path)
    handler = _make_handler(token, config_path)
    httpd = ThreadingHTTPServer((host, port), handler)

    url = f"http://{host}:{port}/"
    print(f"Cairn dashboard running at {url}")
    print("Press Ctrl-C to stop.")

    # Open the browser slightly after the server is ready, off the main thread.
    threading.Timer(0.5, lambda: _open_browser(url)).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down Cairn dashboard.")
    finally:
        try:
            httpd.shutdown()
        except Exception:  # noqa: BLE001
            pass
        httpd.server_close()
    return 0


def _open_browser(url: str) -> None:
    try:
        webbrowser.open(url)
    except Exception:  # noqa: BLE001 - headless boxes have no browser; that's fine
        logger.debug("Could not open a browser for %s", url)


# --- embedded UI ------------------------------------------------------------

PAGE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Cairn</title>
<style>
  :root {
    --bg: #14171c;
    --panel: #1d222b;
    --panel-2: #232a35;
    --line: #2e3744;
    --text: #e6ebf2;
    --muted: #9aa6b6;
    --accent: #6ea8fe;
    --ok: #4ade80;
    --fail: #f87171;
    --warn: #fbbf24;
    --stone: #8a94a6;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    line-height: 1.5;
  }
  .wrap { max-width: 920px; margin: 0 auto; padding: 28px 20px 80px; }
  header { display: flex; align-items: center; gap: 14px; margin-bottom: 8px; }
  .mark {
    width: 40px; height: 40px; flex: 0 0 40px;
    display: flex; align-items: flex-end; justify-content: center;
  }
  .mark span {
    display: block; margin: 0 auto; background: var(--stone); border-radius: 2px;
  }
  .mark .s1 { width: 10px; height: 8px; }
  .mark .s2 { width: 18px; height: 8px; margin-top: 2px; }
  .mark .s3 { width: 26px; height: 9px; margin-top: 2px; }
  h1 { font-size: 26px; margin: 0; letter-spacing: 0.5px; }
  .subtitle { color: var(--muted); font-size: 14px; margin: 0; }
  .pill {
    margin-left: auto; font-size: 13px; padding: 5px 12px; border-radius: 999px;
    border: 1px solid var(--line); background: var(--panel-2); color: var(--muted);
    white-space: nowrap;
  }
  .pill.ok { color: var(--ok); border-color: #2c5d3f; }
  .pill.fail { color: var(--fail); border-color: #5d2c2c; }
  .pill.warn { color: var(--warn); border-color: #5d4f2c; }
  section.card {
    background: var(--panel); border: 1px solid var(--line); border-radius: 12px;
    padding: 18px 18px 20px; margin-top: 18px;
  }
  section.card h2 { margin: 0 0 4px; font-size: 18px; }
  section.card p.lede { margin: 0 0 14px; color: var(--muted); font-size: 14px; }
  .integration {
    display: flex; align-items: center; gap: 12px; padding: 12px;
    border: 1px solid var(--line); border-radius: 10px; background: var(--panel-2);
    margin-bottom: 10px; flex-wrap: wrap;
  }
  .integration.prominent { border-color: var(--accent); }
  .integration .name { font-weight: 600; }
  .integration .kind {
    font-size: 11px; text-transform: uppercase; letter-spacing: 0.6px;
    color: var(--muted); border: 1px solid var(--line); padding: 2px 7px;
    border-radius: 6px;
  }
  .integration .blurb { color: var(--muted); font-size: 13px; flex: 1 1 160px; }
  .integration .result { font-size: 13px; min-width: 120px; }
  .result.ok { color: var(--ok); }
  .result.fail { color: var(--fail); }
  button {
    font: inherit; cursor: pointer; border-radius: 8px; border: 1px solid var(--line);
    background: var(--panel-2); color: var(--text); padding: 8px 14px;
  }
  button:hover:not(:disabled) { border-color: var(--accent); }
  button:disabled { opacity: 0.5; cursor: default; }
  button.primary { background: var(--accent); color: #0c1118; border-color: var(--accent); font-weight: 600; }
  button.big { padding: 12px 20px; font-size: 15px; }
  .counts { display: flex; gap: 10px; flex-wrap: wrap; margin: 14px 0; }
  .count {
    background: var(--panel-2); border: 1px solid var(--line); border-radius: 10px;
    padding: 10px 16px; text-align: center; min-width: 92px;
  }
  .count .n { font-size: 22px; font-weight: 700; display: block; }
  .count .l { font-size: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.5px; }
  .count.created .n { color: var(--ok); }
  .count.updated .n { color: var(--accent); }
  .count.failed .n { color: var(--fail); }
  table { width: 100%; border-collapse: collapse; margin-top: 12px; font-size: 13px; }
  th, td { text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--line); }
  th { color: var(--muted); font-weight: 600; text-transform: uppercase; font-size: 11px; letter-spacing: 0.5px; }
  td.action { font-weight: 600; }
  .badge { padding: 2px 8px; border-radius: 6px; font-size: 12px; }
  .badge.created { background: #133524; color: var(--ok); }
  .badge.updated { background: #142b46; color: var(--accent); }
  .badge.skipped { background: #2a2f38; color: var(--muted); }
  .badge.failed { background: #381717; color: var(--fail); }
  .spinner {
    display: inline-block; width: 16px; height: 16px; border: 2px solid var(--line);
    border-top-color: var(--accent); border-radius: 50%; animation: spin 0.8s linear infinite;
    vertical-align: middle; margin-right: 8px;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
  .row { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
  label { font-size: 14px; color: var(--muted); }
  input[type="number"] {
    font: inherit; background: var(--bg); color: var(--text); border: 1px solid var(--line);
    border-radius: 8px; padding: 8px 10px; width: 80px;
  }
  .msg { font-size: 13px; color: var(--muted); margin-top: 10px; white-space: pre-wrap; }
  .msg.error { color: var(--fail); }
  .status-box {
    background: var(--bg); border: 1px solid var(--line); border-radius: 8px;
    padding: 10px 12px; font-size: 13px; color: var(--muted); white-space: pre-wrap;
    margin-bottom: 12px;
  }
  .empty { color: var(--muted); font-size: 14px; font-style: italic; }
  code { background: var(--bg); padding: 1px 5px; border-radius: 4px; font-size: 12px; }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div class="mark" aria-hidden="true">
      <div><span class="s1"></span><span class="s2"></span><span class="s3"></span></div>
    </div>
    <div>
      <h1>Cairn</h1>
      <p class="subtitle">Every device. One source of truth.</p>
    </div>
    <span id="health" class="pill" role="status">Loading&hellip;</span>
  </header>

  <section class="card" id="config-note" style="display:none">
    <h2>Configuration</h2>
    <p class="lede" id="config-note-text"></p>
  </section>

  <section class="card">
    <h2>Integrations</h2>
    <p class="lede">Your enabled data sources and asset systems. Use <strong>Test</strong> to confirm each connection works.</p>
    <div id="integrations"><p class="empty">Loading&hellip;</p></div>
  </section>

  <section class="card">
    <h2>Dry run</h2>
    <p class="lede">Preview exactly what a sync would do — nothing is written. Safe to run any time.</p>
    <button id="dryrun-btn" class="primary big" type="button">Preview sync (dry-run)</button>
    <div id="dryrun-status" class="msg"></div>
    <div id="dryrun-counts" class="counts" style="display:none"></div>
    <div id="dryrun-results"></div>
  </section>

  <section class="card">
    <h2>Schedule</h2>
    <p class="lede">Run Cairn automatically in the background on this machine.</p>
    <div id="schedule-status" class="status-box">Loading&hellip;</div>
    <div class="row">
      <label for="interval-hours">Run every</label>
      <input type="number" id="interval-hours" min="1" value="6" aria-label="Interval in hours" />
      <label for="interval-hours">hours</label>
      <button id="install-btn" class="primary" type="button">Install</button>
      <button id="remove-btn" type="button">Remove</button>
    </div>
    <div id="schedule-msg" class="msg"></div>
  </section>
</div>

<script>
"use strict";
const TOKEN = "__CAIRN_TOKEN__";
let STATE = null;

function api(path, method, body) {
  const opts = {
    method: method || "GET",
    headers: { "X-Cairn-Token": TOKEN, "Content-Type": "application/json" }
  };
  if (body !== undefined) opts.body = JSON.stringify(body);
  return fetch(path, opts).then(function (r) {
    return r.json().catch(function () { return { error: "Bad response (HTTP " + r.status + ")" }; })
      .then(function (data) {
        if (!r.ok && data && !data.error && !("ok" in data)) data.error = "HTTP " + r.status;
        return data;
      });
  }).catch(function (e) { return { error: String(e) }; });
}

function el(tag, attrs, children) {
  const n = document.createElement(tag);
  if (attrs) for (const k in attrs) {
    if (k === "class") n.className = attrs[k];
    else if (k === "text") n.textContent = attrs[k];
    else n.setAttribute(k, attrs[k]);
  }
  (children || []).forEach(function (c) { n.appendChild(c); });
  return n;
}

function setHealth(cls, text) {
  const p = document.getElementById("health");
  p.className = "pill " + cls;
  p.textContent = text;
}

function metaFor(section, key) {
  try { return STATE.meta[section][key]; } catch (e) { return null; }
}

function configFor(section, key) {
  try { return STATE.config[section][key] || {}; } catch (e) { return {}; }
}

function renderIntegrations() {
  const wrap = document.getElementById("integrations");
  wrap.innerHTML = "";
  const enabled = STATE.enabled || { sources: [], sinks: [], notifiers: [] };
  const rows = [];
  (enabled.sinks || []).forEach(function (k) { rows.push(["sinks", k]); });
  (enabled.sources || []).forEach(function (k) { rows.push(["sources", k]); });

  if (rows.length === 0) {
    wrap.appendChild(el("p", { class: "empty",
      text: "No integrations enabled yet. Add sources and a sink to your config to get started." }));
    return;
  }

  rows.forEach(function (pair) {
    const section = pair[0], key = pair[1];
    const meta = metaFor(section, key) || { display: key, blurb: "" };
    const isSink = section === "sinks";
    const prominent = (key === "snipeit");
    const card = el("div", { class: "integration" + (prominent ? " prominent" : "") });
    card.appendChild(el("span", { class: "name", text: meta.display || key }));
    card.appendChild(el("span", { class: "kind", text: isSink ? "Sink" : "Source" }));
    card.appendChild(el("span", { class: "blurb", text: meta.blurb || "" }));
    const result = el("span", { class: "result", text: "" });
    const btn = el("button", { type: "button", text: "Test connection" });
    btn.addEventListener("click", function () { testConn(section, key, btn, result); });
    card.appendChild(btn);
    card.appendChild(result);
    wrap.appendChild(card);
  });
}

function testConn(section, key, btn, result) {
  btn.disabled = true;
  result.className = "result";
  result.textContent = "Testing\\u2026";
  const cfg = configFor(section, key);
  api("/api/test", "POST", { section: section, key: key, config: cfg }).then(function (data) {
    btn.disabled = false;
    if (data.error) {
      result.className = "result fail";
      result.textContent = "Error: " + data.error;
      return;
    }
    if (data.ok) {
      result.className = "result ok";
      result.textContent = "OK \\u2014 " + (data.message || "reachable");
    } else {
      result.className = "result fail";
      result.textContent = "FAIL \\u2014 " + (data.message || "unreachable");
    }
  });
}

function refreshHealthPill() {
  if (STATE && STATE.error) { setHealth("warn", "No config loaded"); return; }
  const e = (STATE && STATE.enabled) || {};
  const ns = (e.sources || []).length, nk = (e.sinks || []).length;
  if (nk === 0) { setHealth("warn", "No sink configured"); return; }
  setHealth("ok", ns + " source" + (ns === 1 ? "" : "s") + " \\u00b7 " + nk + " sink" + (nk === 1 ? "" : "s"));
}

function loadState() {
  return api("/api/state").then(function (data) {
    STATE = data;
    const note = document.getElementById("config-note");
    const noteText = document.getElementById("config-note-text");
    if (data.error) {
      note.style.display = "";
      noteText.textContent = "Could not load config (" + data.config_path + "): " + data.error;
    } else if (!data.exists) {
      note.style.display = "";
      noteText.textContent = "No config file at " + data.config_path + ". Relying on environment variables.";
    } else {
      note.style.display = "none";
    }
    renderIntegrations();
    refreshHealthPill();
  });
}

function runDryRun() {
  const btn = document.getElementById("dryrun-btn");
  const status = document.getElementById("dryrun-status");
  const counts = document.getElementById("dryrun-counts");
  const results = document.getElementById("dryrun-results");
  btn.disabled = true;
  counts.style.display = "none";
  results.innerHTML = "";
  status.className = "msg";
  status.innerHTML = "<span class=\\"spinner\\"></span>Running dry-run\\u2026 this can take a moment.";

  api("/api/dry-run", "POST", {}).then(function (data) {
    btn.disabled = false;
    if (data.error) {
      status.className = "msg error";
      status.textContent = "Dry-run failed: " + data.error;
      return;
    }
    const s = data.summary || {};
    status.className = "msg";
    status.textContent = (data.text || "") +
      (data.truncated ? "\\n(Showing first 500 results.)" : "");

    counts.innerHTML = "";
    const defs = [
      ["created", "Created", s.created],
      ["updated", "Updated", s.updated],
      ["skipped", "Skipped", s.skipped],
      ["failed", "Failed", s.failed],
      ["seen", "Devices", s.devices_seen]
    ];
    defs.forEach(function (d) {
      const c = el("div", { class: "count " + d[0] });
      c.appendChild(el("span", { class: "n", text: String(d[2] != null ? d[2] : 0) }));
      c.appendChild(el("span", { class: "l", text: d[1] }));
      counts.appendChild(c);
    });
    counts.style.display = "flex";

    const errs = s.source_errors || {};
    const errKeys = Object.keys(errs);
    if (errKeys.length) {
      const box = el("div", { class: "msg error" });
      box.textContent = "Source errors: " + errKeys.map(function (k) { return k + ": " + errs[k]; }).join("; ");
      results.appendChild(box);
    }

    const rows = data.results || [];
    if (rows.length === 0) {
      results.appendChild(el("p", { class: "empty", text: "No device results returned." }));
      return;
    }
    const table = el("table");
    const thead = el("tr");
    ["Action", "Serial", "Identifier", "Detail"].forEach(function (h) {
      thead.appendChild(el("th", { text: h }));
    });
    table.appendChild(el("thead", {}, [thead]));
    const tbody = el("tbody");
    rows.forEach(function (r) {
      const tr = el("tr");
      const td = el("td", { class: "action" });
      td.appendChild(el("span", { class: "badge " + (r.action || ""), text: r.action || "" }));
      tr.appendChild(td);
      tr.appendChild(el("td", { text: r.serial || "" }));
      tr.appendChild(el("td", { text: r.identifier || "" }));
      tr.appendChild(el("td", { text: r.detail || "" }));
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    results.appendChild(table);
  });
}

function loadSchedule() {
  return api("/api/schedule").then(function (data) {
    const box = document.getElementById("schedule-status");
    if (data.error) { box.textContent = "Could not read schedule: " + data.error; return; }
    box.textContent = data.status || "Unknown.";
  });
}

function scheduleAction(action) {
  const msg = document.getElementById("schedule-msg");
  const body = { action: action };
  if (action === "install") {
    const hours = parseInt(document.getElementById("interval-hours").value, 10);
    if (!hours || hours < 1) { msg.className = "msg error"; msg.textContent = "Enter a positive number of hours."; return; }
    body.interval = hours * 3600;
  }
  msg.className = "msg";
  msg.textContent = "Working\\u2026";
  api("/api/schedule", "POST", body).then(function (data) {
    if (data.error || !data.ok) {
      msg.className = "msg error";
      msg.textContent = data.message || data.error || "Failed.";
    } else {
      msg.className = "msg";
      msg.textContent = data.message || "Done.";
    }
    loadSchedule();
  });
}

document.getElementById("dryrun-btn").addEventListener("click", runDryRun);
document.getElementById("install-btn").addEventListener("click", function () { scheduleAction("install"); });
document.getElementById("remove-btn").addEventListener("click", function () { scheduleAction("uninstall"); });

loadState();
loadSchedule();
</script>
</body>
</html>
"""


# Silence an unused-import style lint for dataclasses if tooling is strict; it is
# imported defensively in case future serialization needs it.
_ = dataclasses
