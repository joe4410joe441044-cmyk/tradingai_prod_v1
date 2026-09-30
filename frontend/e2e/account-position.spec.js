import { test, expect } from "@playwright/test";

for (const width of [1920,1440,700]) for (const scenario of ["long","short","flat","unknown","stale","multiple"]) {
    test(`account position ${scenario} ${width}`, async ({page}) => {
        const apiRequests=[];
        await page.route(url => url.pathname.startsWith("/api/"), route => { apiRequests.push(route.request().url()); return route.abort(); });
        await page.setViewportSize({width,height:1400});
        await page.goto(`/e2e/support/account-position-harness.html?scenario=${scenario}`);
        const current=page.getByTestId("current-position-card");
        const last=page.getByTestId("last-position-event-card");
        await expect(current).toBeVisible();
        await expect(last).toContainText("643 ms");
        await expect(last).toContainText("0.00 USDT");
        const expected={long:"LONG",short:"SHORT",flat:"NO OPEN POSITION",unknown:"POSITION STATE UNAVAILABLE",stale:"POSITION DATA IS STALE",multiple:"2 OPEN POSITIONS DETECTED"};
        await expect(current).toContainText(expected[scenario]);
        if(scenario==="long") await expect(current).toContainText("6,174 coin");
        if(scenario==="short") await expect(current).toContainText("12 contracts");
        await current.locator("summary").click();
        await last.locator("summary").click();
        if(scenario==="multiple") for(const value of ["XRPUSDTM","LONG","ETHUSDTM","SHORT"]) await expect(current).toContainText(value);
        expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
        for(const card of [current,last]) {
            expect(await card.evaluate(el=> {
                const rect=el.getBoundingClientRect();
                return el.scrollWidth<=el.clientWidth && rect.left>=0 && rect.right<=innerWidth;
            })).toBeTruthy();
            const metrics=await card.locator(".as-position-metric").evaluateAll(elements=>elements.map(el=>{
                const rect=el.getBoundingClientRect();
                const value=el.querySelector("dd").getBoundingClientRect();
                return value.right<=rect.right+1 && el.scrollWidth<=el.clientWidth;
            }));
            expect(metrics.every(Boolean)).toBeTruthy();
        }
        await current.screenshot({path:`/tmp/cp3-current-${scenario}-${width}.png`});
        await last.screenshot({path:`/tmp/cp3-last-${scenario}-${width}.png`});
        await page.screenshot({path:`/tmp/cp3-${scenario}-${width}.png`,fullPage:true});
        expect(apiRequests).toEqual([]);
    });
}
