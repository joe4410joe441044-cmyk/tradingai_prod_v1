import { expect, test } from '@playwright/test';
import { createNetworkIsolation } from './support/networkIsolation.js';
const record={schemaVersion:1,recordId:'r3',tradeId:'canonical-trade',origin:'PRODUCTION',scope:'PAPER',mode:'paper',symbol:'XRPUSDT',side:'BUY',effectiveRevision:3,controlSource:'MANUAL',entryTimestamp:1789948800,exitTimestamp:1789948860,entryPrice:1.25,exitPrice:1.5,quantity:10,realizedPnl:2.5,holdingMs:60000,exitReason:'MANUAL_CLOSE',result:'WIN',parameterContextAvailable:true,parameterSnapshot:{maximumHoldMs:60000}};
async function setup(page,settings={}) {
 const errors=[],requests=[]; page.on('pageerror',e=>errors.push(e.message));
 page.on('console',m=>{if(m.type()==='error' && !settings.error) errors.push(m.text());});
 const isolation=createNetworkIsolation({apiHandler:async (route,{url})=>{
  requests.push({path:url.pathname,query:Object.fromEntries(url.searchParams),method:route.request().method()});
  if(route.request().method()!=='GET') throw new Error('Unexpected mutation');
  let body={};
  if(url.pathname==='/api/trade-history') {
   if(settings.delay) await new Promise(r=>setTimeout(r,350));
   if(settings.error){await route.fulfill({status:503,contentType:'application/json',body:'{}'});return true;}
   const rows=settings.empty?[]:[{...record,...settings.record}];
   body={available:rows.length>0,records:rows,metrics:{tradeCount:rows.length?51:0,winCount:1,lossCount:0,breakevenCount:0,realizedPnl:2.5},options:{symbol:['XRPUSDT'],revision:[3,4],exitReason:['MANUAL_CLOSE']},pagination:{page:Number(url.searchParams.get('page')||1),pageSize:50,total:rows.length?51:0,pageCount:rows.length?2:0,hasNext:!url.searchParams.has('page'),hasPrevious:url.searchParams.has('page')}};
  } else if(url.pathname==='/api/trade-history/detail') body={...record,...settings.record};
  else if(url.pathname==='/api/parameter-settings/performance') {
   const scope=url.searchParams.get('scope')||'PAPER',revision=Number(url.searchParams.get('revision')||3);
   body={available:true,scope,revision,records:[record],metrics:{tradeCount:1},revisions:[{scope,effectiveRevision:revision,observedTradeCount:1,parameterValues:{maximumHoldMs:60000}}]};
  } else if(url.pathname==='/api/parameter-settings/schema') body={parameters:[]};
  else if(/\/parameter-settings\/(configuration|effective|runtime)$/.test(url.pathname)) body={scope:url.searchParams.get('scope'),configuredRevision:11,effectiveRevision:11,parameters:{},available:false};
  else if(url.pathname==='/api/bot/status') body={status:'STOPPED',tradeMode:'paper',realOrderAllowed:false};
  await route.fulfill({contentType:'application/json',body:JSON.stringify(body)});return true;
 }});
 await isolation.install(page); await page.routeWebSocket('**/ws',()=>{});
 return {errors,requests,isolation};
}
for(const width of [1440,390]) test(`desktop/mobile ${width}: factual fields, filters, detail, cross navigation`,async({page})=>{
 await page.setViewportSize({width,height:900}); const {errors,requests}=await setup(page);
 await page.goto('/trade-history?scope=PAPER&revision=3');
 await expect(page.getByRole('button',{name:'TRADE HISTORY / 取引履歴',exact:true})).toHaveAttribute('aria-current','page');
 const table=page.getByTestId('trade-history-table');
 for(const value of ['Entry Price','Exit Price','Quantity','1.25','1.5']) await expect(table).toContainText(value);
 await page.screenshot({path:`/tmp/trade-history-resume/history-${width}.png`,fullPage:true});
 await expect(table).toContainText(/2026.*\d{2}:\d{2}/); await expect(page.getByTestId('trade-history-metrics')).toContainText('51');
 for(const [key,value] of [['symbol','XRPUSDT'],['side','BUY'],['result','WIN'],['control','MANUAL'],['exit-reason','MANUAL_CLOSE'],['sort','effectiveRevision'],['direction','asc'],['period','custom']]) await page.getByTestId('th-filter-'+key).selectOption(value);
 await page.getByTestId('th-filter-from').fill('2026-09-20'); await page.getByTestId('th-filter-to').fill('2026-09-21');
 await page.getByTestId('th-filter-period').selectOption('all'); await page.getByTestId('trade-history-next').click();
 await expect.poll(()=>requests.some(r=>r.query.page==='2')).toBeTruthy();
 await page.getByTestId('trade-history-open-r3').click();
 await expect(page.getByTestId('trade-history-detail')).toContainText('PRODUCTION');
 await expect(page.getByTestId('trade-history-detail')).toContainText(/2026.*\d{2}:\d{2}/);
 await page.getByTestId('trade-history-open-revision').click();
 await expect(page).toHaveURL(/parameter-settings\?scope=PAPER&revision=3/);
 await expect(page.getByTestId('performance-revision-PAPER-3')).toHaveAttribute('data-focused','true');
 await expect(page.getByTestId('performance-revision-PAPER-3')).toBeFocused();
 await page.getByTestId('parameter-settings-to-trade-history').click();
 await expect(page.getByTestId('th-filter-revision')).toHaveValue('3');
 await page.goBack(); await expect(page.getByTestId('performance-revision-PAPER-3')).toHaveAttribute('data-focused','true');
 await page.goForward(); await expect(page.getByTestId('trade-history-table')).toBeVisible();
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBeTruthy();
 expect(errors).toEqual([]); expect(requests.every(r=>r.method==='GET')).toBeTruthy();
});
test('loading error empty and unknown revision',async({page})=>{
 const settings={delay:true};await setup(page,settings);await page.goto('/trade-history');
 await expect(page.getByTestId('trade-history-loading')).toBeVisible();await expect(page.getByTestId('trade-history-table')).toBeVisible();
 settings.error=true;await page.getByTestId('th-filter-period').selectOption('7d');await expect(page.getByTestId('trade-history-error')).toBeVisible();
 settings.error=false;settings.empty=true;await page.getByTestId('th-filter-period').selectOption('30d');await expect(page.getByTestId('trade-history-empty')).toBeVisible();
 settings.empty=false;settings.record={effectiveRevision:null,controlSource:'UNKNOWN',entryPrice:null,quantity:null};await page.getByTestId('th-filter-period').selectOption('90d');
 await page.getByTestId('trade-history-open-r3').click();await expect(page.getByTestId('trade-history-detail')).toContainText('UNKNOWN');await expect(page.getByTestId('trade-history-open-revision')).toHaveCount(0);
});
test('LIVE and same-page query Back restoration',async({page})=>{
 const {requests}=await setup(page,{record:{scope:'LIVE',mode:'live',controlSource:'BOT'}});await page.goto('/trade-history?scope=LIVE&revision=4');
 await expect(page.getByTestId('th-filter-mode')).toHaveValue('live');
 await page.evaluate(()=>{history.pushState({},'','/trade-history?scope=PAPER&revision=3');dispatchEvent(new PopStateEvent('popstate'));});
 await expect(page.getByTestId('th-filter-revision')).toHaveValue('3');await page.goBack();await expect(page.getByTestId('th-filter-revision')).toHaveValue('4');
 await expect.poll(()=>requests.some(r=>r.query.scope==='LIVE'&&r.query.revision==='4')).toBeTruthy();
});
test('custom period gates incomplete and reversed ranges without invalid requests',async({page})=>{
 const {requests,errors}=await setup(page);await page.goto('/trade-history?scope=PAPER&revision=3');
 const listRequests=()=>requests.filter(r=>r.path==='/api/trade-history');
 await expect.poll(()=>listRequests().length).toBe(1);
 await page.getByTestId('th-filter-period').selectOption('custom');
 await page.waitForTimeout(100);expect(listRequests()).toHaveLength(1);
 await page.getByTestId('th-filter-from').fill('2026-09-21');
 await page.waitForTimeout(100);expect(listRequests()).toHaveLength(1);
 await page.getByTestId('th-filter-to').fill('2026-09-20');
 await page.waitForTimeout(100);expect(listRequests()).toHaveLength(1);
 await page.getByTestId('th-filter-to').fill('2026-09-22');
 await expect.poll(()=>listRequests().length).toBe(2);
 expect(listRequests().at(-1).query).toMatchObject({period:'custom'});
 expect(Number(listRequests().at(-1).query.fromTimestamp)).toBeLessThan(Number(listRequests().at(-1).query.toTimestamp));
 await page.getByTestId('th-filter-from').fill('2026-09-20');
 await expect.poll(()=>listRequests().length).toBe(3);
 for(const period of ['today','7d','30d','90d','all']) await page.getByTestId('th-filter-period').selectOption(period);
 await expect.poll(()=>listRequests().length).toBe(8);
 expect(errors).toEqual([]);expect(listRequests().every(r=>r.method==='GET')).toBeTruthy();
});
