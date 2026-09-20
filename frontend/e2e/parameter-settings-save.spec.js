import { test, expect } from '@playwright/test';

for (const scenario of ['pending', 'promoted', 'stale', 'unavailable', 'rejected', 'bad-response']) {
    test(`Maximum Hold verified save: ${scenario}`, async ({ page }) => {
        let configured = {scope: 'PAPER', configuredRevision: 1, storeStatus: 'VALID', parameters: {maximumHoldMs: 30000}};
        let effective = {scope: 'PAPER', effectiveRevision: 1, parameters: {maximumHoldMs: 30000}};
        let submitted;
        await page.routeWebSocket('**/*', ws => ws.close());
        await page.route('http://127.0.0.1:4174/api/**', async route => {
            const req = route.request(), path = new URL(req.url()).pathname;
            let body = {}, status = 200;
            if (path.endsWith('/schema')) body = {parameters: [{name: 'maximumHoldMs', labelEn: 'Maximum Hold', unit: 'milliseconds', valueType: 'int', minimum: 100, maximum: null, tier: 'PRIMARY'}]};
            if (path.endsWith('/configuration')) {
                if (req.method() === 'PUT') {
                    submitted = req.postDataJSON();
                    if (scenario === 'rejected') { status = 422; body = {message: 'Rejected'}; }
                    else {
                        const saved = {...configured, configuredRevision: 2, parameters: submitted.parameters};
                        if (scenario !== 'stale') configured = saved;
                        if (scenario === 'promoted') effective = {...effective, effectiveRevision: 2, parameters: saved.parameters};
                        body = {code: 'CONFIGURATION_ACCEPTED', configuredRevision: 2, configuration: scenario === 'bad-response' ? {...saved, parameters: {maximumHoldMs: 60000}} : saved};
                    }
                } else {
                    body = configured;
                    if (submitted && scenario === 'unavailable') status = 503;
                }
            }
            if (path.endsWith('/effective')) body = effective;
            await route.fulfill({status, json: body});
        });
        await page.goto('/parameter-settings');
        const input = page.getByTestId('parameter-configured-maximumHoldMs');
        await expect(input).toHaveValue('30000');
        await input.fill('90000');
        await page.getByTestId('save-button').click();
        await expect.poll(() => submitted?.parameters.maximumHoldMs).toBe(90000);
        if (['pending', 'promoted'].includes(scenario)) {
            await expect(page.getByTestId('save-saved')).toContainText(scenario === 'pending' ? 'promotion pending' : 'effective).');
            await expect(input).toHaveValue('90000');
            await page.reload();
            await expect(input).toHaveValue('90000');
            await expect(page.getByTestId('parameter-effective-maximumHoldMs')).toContainText(scenario === 'pending' ? '30000' : '90000');
            await expect(page.getByTestId('parameter-status-maximumHoldMs')).toHaveText(scenario === 'pending' ? 'PENDING' : 'EFFECTIVE');
        } else {
            await expect(page.getByTestId(scenario === 'rejected' ? 'save-invalid' : 'save-error')).toBeVisible();
            await expect(page.getByTestId('save-saved')).toHaveCount(0);
            await expect(input).toHaveValue('90000');
        }
    });
}
