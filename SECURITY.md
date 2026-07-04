# Security Policy

Cairn handles credentials for every system it touches (Jamf, Intune, CrowdStrike,
Snipe-IT, …) and moves device inventory between them, so we take security
seriously. See [`docs/security.md`](docs/security.md) for how Cairn protects
secrets and data at runtime.

## Reporting a vulnerability

**Please do not report security vulnerabilities through public GitHub issues.**

Report privately through one of:

1. **GitHub private vulnerability reporting** (preferred) — go to the
   [Security tab](https://github.com/jsdosanj/cairn/security/advisories) of the
   repository and click **Report a vulnerability**. This opens a private
   advisory only you and the maintainers can see.
2. **Email** — `singhsxdhi@gmail.com` with the subject line
   `[SECURITY] Cairn` if you cannot use GitHub advisories.

Please include:

- A description of the issue and its impact.
- Steps to reproduce (a proof of concept is ideal).
- Affected version(s) / commit, and any relevant configuration.

We will acknowledge your report within **5 business days**, keep you updated on
progress, and credit you in the release notes unless you prefer to remain
anonymous.

## Scope

In scope: credential handling, secret leakage (logs/notifications), TLS and
HTTPS enforcement, the writeback path, config-permission checks, and the local
web dashboard (`cairn web`).

Out of scope: vulnerabilities in the upstream services Cairn integrates with
(report those to the respective vendor), and issues that require a pre-existing
local root/administrator compromise.

## Supported versions

Security fixes land on the latest released minor version. Please upgrade to the
newest release before reporting.
