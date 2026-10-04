// Bundle the React app into ../backend/static (no dev server needed; Flask serves it).
import * as esbuild from 'esbuild';
import { copyFileSync, cpSync, mkdirSync } from 'node:fs';
import { delimiter, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = p => fileURLToPath(new URL(p, import.meta.url));
const out = here('../backend/static/');
mkdirSync(out, { recursive: true });
copyFileSync(here('./index.html'), join(out, 'index.html'));
cpSync(here('./public/fonts'), join(out, 'fonts'), { recursive: true });

const opts = {
  entryPoints: ['src/main.jsx'],
  bundle: true,
  minify: true,
  sourcemap: false,
  format: 'iife',
  target: ['es2020'],
  jsx: 'automatic',
  loader: { '.js': 'jsx' },
  outdir: out,
  entryNames: 'app',
  define: { 'process.env.NODE_ENV': '"production"' },
  nodePaths: process.env.NODE_PATH ? process.env.NODE_PATH.split(delimiter) : [],
  external: ['/static/*'],
  logLevel: 'info',
};

if (process.argv.includes('--watch')) {
  const ctx = await esbuild.context(opts);
  await ctx.watch();
} else {
  await esbuild.build(opts);
}
