/* Local browser verification. No provider credentials or external browser service. */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const {chromium}=require(process.env.PLAYWRIGHT_PACKAGE||'playwright');
const url=process.env.TOKEN_TV_TEST_URL||'http://127.0.0.1:18788';
const out=process.env.TOKEN_TV_SCREENSHOTS||'.runtime/web-screenshots';fs.mkdirSync(out,{recursive:true});
const themes=['digital','neon','retro','hud'];
async function theme_and_responsive_checks(page){
 for(const theme of themes){await page.locator(`[data-theme-choice=${theme}]`).click();assert.equal(await page.locator('html').getAttribute('data-theme'),theme);await page.screenshot({path:`${out}/${theme}-desktop.png`,fullPage:true});for(const width of[320,375,414,768]){await page.setViewportSize({width,height:1000});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,`${theme} overflow at ${width}`);if(width===375)await page.screenshot({path:`${out}/${theme}-mobile.png`,fullPage:true});}await page.setViewportSize({width:1440,height:1100});}
 await page.reload();await page.waitForSelector('.provider-card');assert.equal(await page.locator('html').getAttribute('data-theme'),'hud');
}
async function account_and_state_checks(page){
 const accounts=page.locator('[data-account]');assert.equal(await accounts.count(),7);
 for(const b of await accounts.all()){const key=await b.getAttribute('data-account');await b.click();assert.equal(await page.locator(`.provider-card[data-key="${key}"]`).count(),1);assert.equal(await page.locator(`[data-account="${key}"]`).getAttribute('aria-pressed'),'true');}
 const fixture={schema:1,updated_at:Date.now()/1000,accounts:{a:{key:'a',alias:'CLAUDE A',provider:'claude',status:'stale',source:'laptop',windows:[{label:'5H',used_percent:82,resets_at:Date.now()/1000+3600},{label:'WEEK',used_percent:50,resets_at:Date.now()/1000+8000}],last_success_at:Date.now()/1000-3600,fetched_at:Date.now()/1000-3600},b:{key:'b',alias:'CODEX A',provider:'codex',status:'identity_mismatch',windows:[{label:'WEEK',used_percent:99}]},c:{key:'c',alias:'GROK A',provider:'grok',status:'quota_unavailable',windows:[],source:'mini'}}};
 await page.route('**/snapshot',r=>r.fulfill({json:fixture}));await page.reload();await page.waitForSelector('[data-key=a]');assert.match(await page.locator('[data-key=a] .row-status').innerText(),/OLD/);assert.equal(await page.locator('[data-key=a] .meter').first().getAttribute('aria-valuenow'),'82');await page.locator('.more-windows summary').click();assert.equal(await page.locator('.window-percent').innerText(),'50%');assert.equal(await page.locator('[data-key=b] [role=meter]').count(),0);assert.equal(await page.locator('[data-key=c] .percentage').innerText(),'—');
 await page.route('**/snapshot',r=>r.abort());await page.evaluate(()=>update());await page.waitForFunction(()=>document.body.dataset.offline==='true');assert.match(await page.locator('#notice').innerText(),/Connection lost/);assert.match(await page.locator('[data-key=a] .row-status').innerText(),/OFFLINE/);
 await page.unroute('**/snapshot');await page.reload();await page.waitForSelector('[data-account]');
}
async function clock_independence_checks(page){
 const original=await (await page.request.get(url+'/display')).json();let posts=0;page.on('request',r=>{if(r.method()==='POST')posts++});
 for(const theme of themes)await page.locator(`[data-theme-choice=${theme}]`).click();for(const b of await page.locator('[data-account]').all())await b.click();assert.equal(posts,0);assert.equal((await(await page.request.get(url+'/display')).json()).style,original.style);
 await page.locator('#clock-toggle').click();await page.waitForFunction(()=>{const i=document.querySelector('#frame');return i.complete&&i.naturalWidth===240&&i.currentSrc.includes('style='+document.querySelector('#clock-style').value)});await page.locator('#frame').evaluate(i=>i.decode());await page.locator('#clock-style').selectOption('neon');await page.waitForFunction(()=>{const i=document.querySelector('#frame');return i.complete&&i.naturalWidth===240&&i.currentSrc.includes('style='+document.querySelector('#clock-style').value)});await page.locator('#frame').evaluate(i=>i.decode());assert.equal(posts,0);assert.equal((await(await page.request.get(url+'/display')).json()).style,original.style);
 // Exercise apply against intercepted delivery, never mutate the real clock from a web test.
 await page.route('**/display/style',r=>{assert.deepEqual(r.request().postDataJSON(),{style:'neon'});return r.fulfill({json:{style:'neon',applied_style:'neon',status:'ok',styles:original.styles}})});
 await page.locator('#apply').click();await page.waitForFunction(()=>document.querySelector('#display-state').textContent==='Image sent · Neon');assert.equal((await(await page.request.get(url+'/display')).json()).style,original.style);await page.locator('#close-clock').click();assert.equal(await page.locator('#clock-toggle').getAttribute('aria-expanded'),'false');
}
async function themes_checks(page){
 const t=(id,added,likes,state,extra={})=>Object.assign({id,name:id,author:'tester',local:false,installed:true,needs_update:false,min_version:'0.1.0',added_at:added,source_url:'https://github.com/x/y',license:'MIT',preview_url:null,likes,likes_state:state,likes_counted_at:likes===null?null:'2026-10-03T12:00:00Z',like_url:likes===null?null:'https://github.com/x/y/issues/1'},extra);
 const fixture={last_attempt_at:'2026-10-03T12:00:00Z',version:'0.1.0',themes:[t('digital','2026-10-01T00:00:00Z',8,'counted'),t('neon','2026-10-02T00:00:00Z',0,'counted'),t('retro','2026-10-03T00:00:00Z',null,'unavailable'),t('space',null,null,'local',{local:true,author:null,added_at:null,source_url:null}),t('vapor','2026-10-04T00:00:00Z',null,'not_open',{installed:false,needs_update:true,min_version:'0.3.0'})]};
 await page.route('**/themes',r=>r.fulfill({json:fixture}));await page.reload();await page.waitForSelector('[data-account]');
 let posts=0;page.on('request',r=>{if(r.method()==='POST')posts++});
 await page.waitForSelector('#gallery .theme-card');assert.equal(await page.locator('#clock-panel').isHidden(),true);assert.equal(await page.locator('#gallery').isVisible(),true); // gallery is visible without opening the clock panel
 assert.deepEqual(await page.locator('.theme-card').evaluateAll(n=>n.map(x=>x.dataset.id)),['digital','neon','vapor','retro','space']);
 for(const t of await page.locator('.theme-thumb').all())await t.scrollIntoViewIfNeeded();await page.waitForFunction(()=>[...document.querySelectorAll('.theme-thumb')].every(i=>i.complete&&i.naturalWidth===240));assert.equal(await page.locator('[data-id=vapor] .theme-thumb').count(),0);
 assert.match(await page.locator('[data-id=neon] .theme-likes').innerText(),/👍 0/);assert.match(await page.locator('[data-id=retro] .theme-likes').innerText(),/unavailable/);assert.match(await page.locator('[data-id=space]').innerText(),/Local/);
 assert.match(await page.locator('[data-id=vapor]').innerText(),/Needs v0.3.0/);assert.equal(await page.locator('[data-id=vapor] button').count(),0);
 await page.locator('[data-sort=new]').click();assert.deepEqual(await page.locator('.theme-card').evaluateAll(n=>n.map(x=>x.dataset.id)),['vapor','retro','neon','digital','space']);
 await page.locator('[data-id=neon] button').click();assert.equal(await page.locator('#clock-panel').isVisible(),true);assert.equal(await page.locator('#clock-style').inputValue(),'neon');assert.equal(posts,0);
 await page.locator('[data-id=digital] button').click();assert.equal(await page.locator('#clock-style').inputValue(),'digital');assert.equal(await page.locator('#frame').evaluate(e=>{const r=e.getBoundingClientRect();return r.top>=0&&r.bottom<=innerHeight}),true);assert.equal(posts,0);
 assert.equal(await page.locator('.gallery-links a',{hasText:'Share a face'}).getAttribute('href'),'https://github.com/click6067-ship-it/token-tv/issues/new?template=share_a_face.md');
 await page.unroute('**/themes');await page.locator('#close-clock').click();
}
async function demo_checks(browser,demo){
 const page=await browser.newPage({viewport:{width:375,height:900}});let posts=0;page.on('request',r=>{if(r.method()==='POST')posts++});
 await page.goto(demo);await page.waitForSelector('#gallery .theme-card');for(const t of await page.locator('.theme-thumb').all())await t.scrollIntoViewIfNeeded();await page.waitForFunction(()=>[...document.querySelectorAll('.theme-thumb')].length===6&&[...document.querySelectorAll('.theme-thumb')].every(i=>i.complete&&i.naturalWidth===240));await page.locator('.theme-card button').first().click();
 await page.waitForFunction(()=>{const i=document.querySelector('#frame');return i.complete&&i.naturalWidth===240});
 assert.equal(await page.locator('#apply').isVisible(),false);assert.match(await page.locator('.theme-actions a',{hasText:'Get'}).first().getAttribute('href'),/docs\/setup\.md$/);assert.equal(posts,0);
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);await page.screenshot({path:`${out}/demo-themes-375.png`,fullPage:true});await page.close();
}
(async()=>{const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_EXECUTABLE});try{const page=await browser.newPage({viewport:{width:1440,height:1100}});const errors=[];page.on('pageerror',e=>errors.push(e.message));await page.goto(url);await page.waitForSelector('[data-account]');await theme_and_responsive_checks(page);await account_and_state_checks(page);await clock_independence_checks(page);await themes_checks(page);if(process.env.TOKEN_TV_DEMO_URL)await demo_checks(browser,process.env.TOKEN_TV_DEMO_URL);assert.deepEqual(errors,[]);fs.writeFileSync(`${out}/result.json`,JSON.stringify({themes,widths:[320,375,414,768,1440],accounts:7,clockUnchanged:true,pageErrors:errors,passed:true},null,2));console.log('PASS: four themes, five widths, seven accounts, stale/missing/offline states, clock independence and apply.');}finally{await browser.close()}})().catch(e=>{console.error(e);process.exitCode=1});
