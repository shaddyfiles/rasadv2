// Build the clickable demo: one HTML file with the app, its styles, the fonts and recorded API data inlined.
// First record the data:  python demo/capture.py   then:  node build-demo.mjs   (writes dist-demo/rasad-demo.html)
import * as esbuild from 'esbuild';
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const here = p => fileURLToPath(new URL(p, import.meta.url));
const r = await esbuild.build({
  entryPoints: ['src/main.jsx'], bundle: true, minify: true, format: 'iife', target: ['es2020'],
  jsx: 'automatic', loader: { '.js': 'jsx' }, outdir: 'out', entryNames: 'app', write: false,
  define: { 'process.env.NODE_ENV': '"production"' }, external: ['/static/*'],
  nodePaths: process.env.NODE_PATH ? process.env.NODE_PATH.split(':') : [],
});
const pick = ext => new TextDecoder().decode(r.outputFiles.find(f => f.path.endsWith(ext)).contents);
const css = pick('.css').replace(/url\(["']?\/static\/fonts\/([\w-]+)\.(woff2?)["']?\)/g, (_, name, ext) =>
  `url(data:font/${ext};base64,${readFileSync(here(`public/fonts/${name}.${ext}`)).toString('base64')})`);
const js = pick('.js').replace(/<\/script/gi, '<\\/script');
const data = readFileSync(here('demo/demo-data.json'), 'utf8').replace(/<\//g, '<\\/');

const page = `<title>Rasad Forward Logistics</title>
<meta name="description" content="Predictive logistics for forward posts: stock-out risk, road-closure forecasts and GA + ACO resupply plans.">
<style>${css}</style>
<div id="root"></div>
<script>window.RASAD_DEMO = ${data};</script>
<script>${js}</script>
`;
mkdirSync(here('dist-demo'), { recursive: true });
writeFileSync(here('dist-demo/artifact-body.html'), page);   // for hosts that add their own <html> skeleton
writeFileSync(here('dist-demo/rasad-demo.html'), `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">\n${page}</html>`);
console.log('dist-demo/rasad-demo.html', Math.round(page.length / 1024), 'KB');
