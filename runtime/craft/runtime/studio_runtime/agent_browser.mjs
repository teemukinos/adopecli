// Local inspection of existing Rive artifacts. No external network requests.
import {createServer} from 'node:http';
import {readFile,writeFile,mkdir} from 'node:fs/promises';
import {resolve,extname,sep} from 'node:path';
import {pathToFileURL} from 'node:url';
import {createHash} from 'node:crypto';
const [root,output,modulePath,chrome]=process.argv.slice(2);
const {default:puppeteer}=await import(pathToFileURL(modulePath).href);
const config=JSON.parse(await readFile(resolve(root,'component.json'),'utf8'));
await mkdir(output,{recursive:true});
const server=createServer(async(req,res)=>{try{
 const path=resolve(root,'.'+decodeURIComponent(req.url.split('?')[0]));
 if(path!==resolve(root)&&!path.startsWith(resolve(root)+sep))throw Error('path');
 const actual=req.url==='/'?resolve(root,'index.html'):path;
 res.setHeader('Content-Type',({'.html':'text/html','.js':'text/javascript','.wasm':'application/wasm','.json':'application/json'})[extname(actual)]||'application/octet-stream');
 res.end(await readFile(actual));
}catch{res.statusCode=404;res.end();}});
await new Promise(r=>server.listen(0,'127.0.0.1',r));
const browser=await puppeteer.launch({executablePath:chrome,headless:true,pipe:true,args:['--disable-background-networking','--disable-sync','--no-first-run']});
const report={passed:false,checks:[],errors:[],externalRequests:[]};
try{
 const page=await browser.newPage();await page.setViewport({width:900,height:700,deviceScaleFactor:1});
 await page.setRequestInterception(true);
 const origin=`http://127.0.0.1:${server.address().port}`;
 page.on('request',r=>{if(r.url().startsWith(origin+'/')||r.url().startsWith('data:')||r.url().startsWith('blob:'))r.continue();else{report.externalRequests.push(r.url());r.abort();}});
 page.on('pageerror',e=>report.errors.push(String(e)));
 await page.goto(origin+'/');await page.waitForFunction('window.ready || window.failure',{timeout:15000});
 const failure=await page.evaluate(()=>window.failure);if(failure)throw Error(failure);
 const pause=ms=>new Promise(r=>setTimeout(r,ms));
 async function capture(name,value){
  await page.waitForFunction(({input,value})=>window.construction.stateMachineInputs('Construction').find(i=>i.name===input).value===value,{timeout:3000},{input:config.input,value});
  await pause(350);const png=await(await page.$('canvas')).screenshot();await writeFile(resolve(output,name+'.png'),png);
  report.checks.push({name,value,sha256:createHash('sha256').update(png).digest('hex')});
 }
 const expected=event=>{const e=config.events.find(e=>e.event===event);if(!e)throw Error('Missing '+event+' interaction');return e.value;};
 const idle=config.states[0].value;await capture('idle',idle);
 const target=config.objects.find(o=>o.id===config.events.find(e=>e.event==='enter')?.target);
 if(!target)throw Error('No hover target');
 const bounds=await(await page.$('canvas')).boundingBox();
 const x=bounds.x+bounds.width*target.x/config.width,y=bounds.y+bounds.height*target.y/config.height;
 await page.mouse.move(x,y);await capture('hover',expected('enter'));
 await page.mouse.down();await capture('pressed',expected('down'));
 // Exercise the actual pointer-up handler without the same handler immediately
 // overwriting it with click. The release coordinates lie outside the target.
 await page.evaluate(({x,y})=>document.querySelector('canvas').dispatchEvent(new PointerEvent('pointerup',
  {bubbles:true,pointerType:'mouse',pointerId:1,clientX:x,clientY:y})),{x:bounds.x-10,y});
 await capture('up',expected('up'));
 await page.mouse.up();await page.mouse.down();
 await page.mouse.up();await capture('result',expected('click'));
 await page.mouse.move(0,0);await capture('exit',expected('exit'));
 // Sample native interpolation between two distinct states.
 const transition=await page.evaluate(async({idle,hover})=>{
  const wait=ms=>new Promise(r=>setTimeout(r,ms));const canvas=document.querySelector('canvas');
  window.setConstructionData(idle);await wait(350);const before=canvas.toDataURL();
  window.setConstructionData(hover);await wait(65);const middle=canvas.toDataURL();await wait(350);
  const after=canvas.toDataURL();return {intermediateFrameDiffers:middle!==before&&middle!==after,middle};
 },{idle,hover:expected('enter')});
 const middle=Buffer.from(transition.middle.split(',')[1],'base64');
 await writeFile(resolve(output,'transition-middle.png'),middle);
 report.transition={intermediateFrameDiffers:transition.intermediateFrameDiffers,configuredDurationMs:config.transition_ms??180,
  sampleTimeMs:65,preview:'transition-middle.png',sha256:createHash('sha256').update(middle).digest('hex')};
 if(!transition.intermediateFrameDiffers)throw Error('No distinct interpolated frame');
 await page.click('#reduced');await page.waitForFunction('window.ready');
 const reduced=await page.evaluate(async({idle,hover})=>{
  const wait=ms=>new Promise(r=>setTimeout(r,ms));const canvas=document.querySelector('canvas');
  window.setConstructionData(idle);await wait(100);window.setConstructionData(hover);await wait(65);
  const early=canvas.toDataURL();await wait(350);return {enabled:window.reducedMotion,settledImmediately:early===canvas.toDataURL()};
 },{idle,hover:expected('enter')});
 report.reducedMotion=reduced;await capture('reduced-hover',expected('enter'));
 if(!reduced.enabled||!reduced.settledImmediately)throw Error('Reduced-motion output still interpolates');
 if(new Set(report.checks.filter(c=>['idle','hover','pressed','result'].includes(c.name)).map(c=>c.sha256)).size!==4)throw Error('Four states do not have distinct pixels');
 if(report.errors.length||report.externalRequests.length)throw Error('Browser emitted errors or external requests');
 report.passed=true;
}catch(error){report.error=String(error);process.exitCode=1;}
finally{await writeFile(resolve(output,'report.json'),JSON.stringify(report,null,2));await browser.close();server.close();}
console.log(JSON.stringify({passed:report.passed,error:report.error}));
