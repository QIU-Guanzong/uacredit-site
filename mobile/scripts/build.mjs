import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { build } from 'esbuild';
import { validateAccountOrigin } from './account-origin.mjs';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const site=path.dirname(root);
const config=JSON.parse(await fs.readFile(path.join(root,'app-config.json'),'utf8'));
validateAccountOrigin(config);
const target=path.join(root,'www');
const old=await fs.lstat(target).catch(()=>null);
if(old?.isSymbolicLink())throw new Error('Generated www cannot be a symbolic link.');
await fs.rm(target,{recursive:true,force:true});
await fs.mkdir(target,{recursive:true});
// Copy only the deployable public assets, never databases, .env, staff data or credentials.
const omittedAssets=new Set(['admin.css','editor.js','account.css','account.js']);
await fs.cp(path.join(site,'dist'),target,{recursive:true,force:true,filter:src=>!omittedAssets.has(path.basename(src))});
const notices=await fs.readFile(path.join(root,'resources/THIRD_PARTY_NOTICES.txt'),'utf8');
const shell=(await fs.readFile(path.join(root,'src/shell.html'),'utf8')).replace('{{THIRD_PARTY_NOTICES}}',notices.replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;'));
await fs.mkdir(path.join(target,'mobile'),{recursive:true});
await fs.writeFile(path.join(target,'mobile/index.html'),shell);
await fs.copyFile(path.join(root,'src/mobile.css'),path.join(target,'assets/mobile.css'));
async function htmlPaths(folder,prefix=''){const paths=[];for(const e of await fs.readdir(folder,{withFileTypes:true})){const rel=path.posix.join(prefix,e.name);if(e.isDirectory())paths.push(...await htmlPaths(path.join(folder,e.name),rel));else if(e.name.endsWith('.html'))paths.push('/'+rel);}return paths;}
const publicPaths=await htmlPaths(target);
await fs.writeFile(path.join(target,'assets/public-pages.json'),JSON.stringify(publicPaths));
await build({entryPoints:[path.join(root,'src/mobile.js')],bundle:true,minify:true,format:'iife',target:['safari15','chrome109'],outfile:path.join(target,'assets/mobile.js'),define:{__APP_CONFIG__:JSON.stringify(config),__PUBLIC_PATHS__:JSON.stringify(publicPaths)},legalComments:'eof'});
async function visit(folder){for(const e of await fs.readdir(folder,{withFileTypes:true})){const p=path.join(folder,e.name);if(e.isDirectory())await visit(p);else if(e.name.endsWith('.html')){
  let html=await fs.readFile(p,'utf8');
  html=html.replace(/width=device-width, initial-scale=1(?!, viewport-fit)/,'width=device-width, initial-scale=1, viewport-fit=cover');
  html=html.replace('</head>','<link rel="stylesheet" href="/assets/mobile.css"><script src="/assets/mobile.js" defer></script></head>');
  // Explicit file paths work consistently in WKWebView and Android's local asset server.
  html=html.replace(/href="(\/[^"?#]*)([?#][^"]*)?"/g,(full,route,tail='')=>{
    if(route.startsWith('/account')||route.startsWith('/admin')||route.startsWith('/assets')||path.extname(route))return full;
    return `href="${route.replace(/\/$/,'')}/index.html${tail}"`.replace('href="/index.html/index.html','href="/index.html');
  });
  await fs.writeFile(p,html);
}}}
await visit(target);
console.log('Built guest-first bundled app: public information is available without network or registration.');
