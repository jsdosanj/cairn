# Notifiers

[← Back to docs index](README.md)

Notifiers deliver a short summary after a sync, writeback, or scheduled drift run.
They're optional and best-effort: a notifier failure is logged but never fails the
run. All notifier URLs must be **HTTPS**.

Enable them under `notifiers:` in your config.

---

## When notifications fire

| Operation | Title example | Level |
|---|---|---|
| `cairn sync` | `Cairn sync: 7 created, 38 updated` (+`, N failed`) | `success` / `warning` (source errors) / `error` (failures) |
| `cairn writeback` | `Cairn writeback: 41 updated, 7 failed` | `success` / `error` |
| `cairn drift` (incl. scheduled `--drift`) | `Cairn drift: 7 missing, 3 stale, 2 conflicting, 1 duplicate` | `success` (no drift) / `warning` (drift) |

The message body is the run summary (or the masked drift report for drift). Serial
numbers in drift digests are **masked** to the last 4 chars.

---

## Microsoft Teams — `teams`

```yaml
notifiers:
  teams:
    enabled: true
    webhook_url: https://outlook.office.com/webhook/your-webhook-url
```

| Key | Required | Notes |
|---|---|---|
| `webhook_url` | ✅ | An **Incoming Webhook** connector URL for a Teams channel. Must be HTTPS. |

Get the URL: in Teams, **channel → … → Connectors → Incoming Webhook → Configure**.
Cairn posts a MessageCard.

---

## Slack — `slack`

```yaml
notifiers:
  slack:
    enabled: true
    webhook_url: https://hooks.slack.com/services/XXXX/YYYY/ZZZZ
```

| Key | Required | Notes |
|---|---|---|
| `webhook_url` | ✅ | A Slack **Incoming Webhook** URL. Must start with `https://`. |

Get the URL: create a Slack app, add the **Incoming Webhooks** feature, and add a
webhook to the target channel.

---

## Generic webhook — `webhook`

Posts a JSON payload to any HTTPS endpoint — wire Cairn into your own
collector/SIEM/automation.

```yaml
notifiers:
  webhook:
    enabled: true
    url: https://example.com/collector
    headers:
      X-Api-Key: optional-shared-secret
```

| Key | Required | Notes |
|---|---|---|
| `url` | ✅ | HTTPS endpoint to POST to. |
| `headers` | — | Extra HTTP headers (e.g. an auth/shared-secret header). |

---

## Notes

- If a notifier has no `webhook_url`/`url`, it silently does nothing (safe to
  leave a stub).
- A non-HTTPS notifier URL is rejected.
- Notifier delivery is wrapped: an exception is logged (`notifier <key> failed`)
  but the sync/drift result is unaffected.

See [Troubleshooting → notifications](troubleshooting.md#notifications).
