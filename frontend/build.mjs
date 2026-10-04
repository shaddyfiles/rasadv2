// Bundle the React app into ../backend/static (no dev server needed; Flask serves it).
import * as esbuild from 'esbuild';
import { copyFileSync, cpSync, mkdirSync } from 'node:fs';

const out = new URL('../backend/static/', import.meta.url).pathname;
mkdirSync(out, { recursive: true });
copyFileSync(new URL('./index.html', import.meta.url).pathname, out + 'index.html');
cpSync(new URL('./public/fonts', import.meta.url).pathname, out + 'fonts', { recursive: true });

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
  nodePaths: process.env.NODE_PATH ? process.env.NODE_PATH.split(':') : [],
  external: ['/static/*'],
  logLevel: 'info',
};

if (process.argv.includes('--watch')) {
  const ctx = await esbuild.context(opts);
  await ctx.watch();
} else {
  await esbuild.build(opts);
}
