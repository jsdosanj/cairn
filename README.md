# Cairn — marketing site

The source for the **Cairn** landing page. Cairn is an open-source CLI that
reconciles device inventory from your MDM/EDR tools into a single IT asset
system of record.

> Every device. One source of truth.

This repo contains only the static marketing site — no application code. The
Cairn tool itself lives at
**https://github.com/jsdosanj/cairn**.

## What's here

```
index.html              # the single-page site
assets/
  styles.css            # all styling (pure CSS, no frameworks)
  main.js               # mobile nav, copy-to-clipboard, install tabs
  cairn.svg             # stacked-stones logo / favicon
.github/workflows/
  pages.yml             # GitHub Pages deploy
```

No build step, no dependencies, no bundler. It's plain HTML, CSS, and a small
sprinkle of vanilla JavaScript.

## Preview locally

From the repository root:

```bash
python3 -m http.server 8000
```

Then open http://localhost:8000 in your browser. (Serving over HTTP rather than
opening the file directly keeps relative asset paths working consistently.)

## Deployment

The site deploys to **GitHub Pages** automatically. On every push to `main`,
the workflow in [`.github/workflows/pages.yml`](.github/workflows/pages.yml)
uploads the repository root as a Pages artifact and publishes it.

One-time setup in the GitHub repo: **Settings → Pages → Build and deployment →
Source: GitHub Actions**.

## License

AGPL-3.0-or-later (matching the Cairn tool and Snipe-IT).
