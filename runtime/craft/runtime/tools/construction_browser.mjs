// Offline browser qualification of the shipped Rive runtime and real canvas pixels.
import {createServer} from 'node:http';
import {readFile,writeFile,mkdir} from 'node:fs/promises';
import {resolve,extname,sep} from 'node:path';
import {createHash} from 'node:crypto';
const [root,output,puppeteerPath,chrome]=process.argv.slice(2);
const {default:puppeteer}=await import(puppeteerPath);
await mkdir(output,{recursive:true});
const server=createServer(async(req,res)=>{try{const path=resolve(root,'.'+decodeURIComponent(req.url.split('?')[0]));if(path!==resolve(root)&&!path.startsWith(resolve(root)+sep))throw Error('path');const actual=req.url==='/'?resolve(root,'index.html'):path;res.setHeader('Content-Type',({'.html':'text/html','.js':'text/javascript','.wasm':'application/wasm','.json':'application/json'})[extname(actual)]||'application/octet-stream');res.end(await readFile(actual));}catch{res.statusCode=404;res.end();}});
await new Promise(r=>server.listen(0,'127.0.0.1',r));
const browser=await puppeteer.launch({executablePath:chrome,headless:true,args:['--disable-background-networking','--disable-sync','--no-first-run']});
let report={checks:[],externalRequests:[],errors:[]};
try {
 const page=await browser.newPage();await page.setViewport({width:900,height:700,deviceScaleFactor:1});
 await page.setRequestInterception(true);page.on('request',r=>{if(r.url().startsWith('http://127.0.0.1:')||r.url().startsWith('data:')||r.url().startsWith('blob:'))r.continue();else{report.externalRequests.push(r.url());r.abort();}});
 page.on('pageerror',e=>report.errors.push(String(e)));
 await page.goto(`http://127.0.0.1:${server.address().port}/`);await page.waitForFunction('window.ready || window.failure',{timeout:15000});
 const failure=await page.evaluate(()=>window.failure);if(failure)throw Error(failure);
 async function capture(name,expected){await page.waitForFunction(v=>window.construction.stateMachineInputs('Construction').find(i=>i.name==='state').value===v,{},expected);await new Promise(r=>setTimeout(r,400));const canvas=await page.$('canvas');const png=await canvas.screenshot();await writeFile(resolve(output,name+'.png'),png);const actual=await page.evaluate(()=>window.construction.stateMachineInputs('Construction').map(i=>({name:i.name,value:i.value})));const check={name,expected,actual,sha256:createHash('sha256').update(png).digest('hex')};report.checks.push(check);return check;}
 await capture('idle',0);
 const motion=await page.evaluate(async()=>{const canvas=document.querySelector('canvas'),pause=ms=>new Promise(r=>setTimeout(r,ms));window.setConstructionData(0);await pause(300);const idle=canvas.toDataURL();window.setConstructionData(1);await pause(65);const middle=canvas.toDataURL();await pause(300);return {idle,middle,settled:canvas.toDataURL()};});
 report.transition={intermediateFrameDiffers:motion.middle!==motion.idle&&motion.middle!==motion.settled};if(!report.transition.intermediateFrameDiffers)throw Error('No native transition interpolation observed');
 await page.evaluate(()=>window.setConstructionData(0));await new Promise(r=>setTimeout(r,250));let rect=await (await page.$('canvas')).boundingBox();const x=rect.x+rect.width/2,y=rect.y+rect.height/2;
 await page.mouse.move(x,y);await capture('hover',1);await page.mouse.down();await capture('pressed',2);await page.mouse.up();await capture('result',3);
 await page.mouse.move(0,0);await page.focus('canvas');await page.keyboard.down('Space');await capture('keyboard-pressed',2);await page.keyboard.up('Space');await capture('keyboard-result',3);
 await page.evaluate(()=>window.setConstructionData(1));await capture('data-hover',1);
 await page.click('#reduced');await page.waitForFunction('window.ready');await page.evaluate(()=>window.setConstructionData(3));await capture('reduced-result',3);
 const reduced=await page.evaluate(async()=>{const canvas=document.querySelector('canvas');window.setConstructionData(0);await new Promise(r=>setTimeout(r,100));window.setConstructionData(1);await new Promise(r=>setTimeout(r,65));const early=canvas.toDataURL();await new Promise(r=>setTimeout(r,300));return {enabled:window.reducedMotion,settledImmediately:early===canvas.toDataURL()};});report.reducedMotion=reduced;if(!reduced.enabled||!reduced.settledImmediately)throw Error('Reduced-motion output still interpolates');
 const touch=await browser.newPage();await touch.setViewport({width:900,height:700,hasTouch:true,isMobile:true});await touch.goto(`http://127.0.0.1:${server.address().port}/`);await touch.waitForFunction('window.ready');const bounds=await(await touch.$('canvas')).boundingBox();await touch.touchscreen.tap(bounds.x+bounds.width/2,bounds.y+bounds.height/2);await touch.waitForFunction("window.construction.stateMachineInputs('Construction')[0].value===3");report.touch=true;
 const hashes=new Set(report.checks.slice(0,4).map(c=>c.sha256));if(hashes.size!==4)throw Error('Native canvas states did not produce four different rendered frames');
 if(report.errors.length||report.externalRequests.length)throw Error('Browser emitted errors or external requests');
 report.passed=true;
} catch(e){report.passed=false;report.error=String(e);process.exitCode=1;} finally {await writeFile(resolve(output,'report.json'),JSON.stringify(report,null,2));await browser.close();server.close();}
console.log(JSON.stringify(report));
