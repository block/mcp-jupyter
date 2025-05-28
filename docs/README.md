# MCP Jupyter Documentation

This is the documentation site for MCP Jupyter Server, built with Docusaurus.

## Local Development

First, activate hermit to get pnpm:

```bash
. bin/activate-hermit
```

Then install dependencies and start the development server:

```bash
cd docs
pnpm install
pnpm start
```

This command starts a local development server and opens up a browser window. Most changes are reflected live without having to restart the server.

## Build

```bash
pnpm build
```

This command generates static content into the `build` directory and can be served using any static contents hosting service.

## Serve Built Site

To preview the production build locally:

```bash
pnpm serve
```

## Structure

- `/docs` - Documentation pages
- `/src/pages` - Custom pages (homepage)
- `/src/components` - React components
- `/static` - Static assets (images, demos)
- `docusaurus.config.ts` - Site configuration