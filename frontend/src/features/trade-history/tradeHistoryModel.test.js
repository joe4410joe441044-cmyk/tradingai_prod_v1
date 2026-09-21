import assert from 'node:assert/strict';
import test from 'node:test';
import { buildTradeHistoryQuery, parseTradeHistoryQuery, buildTradeRows, buildFilterOptions, buildTradeHistoryViewModel, buildParameterSettingsDeeplink, buildTradeHistoryDeeplink, isTradeHistoryQueryReady } from './tradeHistoryModel.js';

test('all query filters roundtrip and exact scope/revision deeplink', () => {
    const input={period:'custom',scope:'PAPER',mode:'paper',symbol:'XRPUSDT',side:'BUY',result:'WIN',revision:3,exitReason:'MANUAL_CLOSE',controlSource:'MANUAL',fromTimestamp:10,toTimestamp:20,sort:'effectiveRevision',direction:'asc',page:2,pageSize:10};
    assert.deepEqual(parseTradeHistoryQuery(buildTradeHistoryQuery(input)),input);
    assert.match(buildTradeHistoryDeeplink('PAPER',3),/scope=PAPER&revision=3/);
    assert.equal(buildParameterSettingsDeeplink('LIVE',4),'/parameter-settings?scope=LIVE&revision=4');
});
test('default general history includes both modes', () => {
    assert.equal(parseTradeHistoryQuery('').scope,null);
    assert.equal(parseTradeHistoryQuery('').period,'all');
    assert.equal(parseTradeHistoryQuery('').sort,'exitTimestamp');
});
test('canonical fields and date plus time remain factual, with no revision fallback', () => {
    const [row]=buildTradeRows([{entryTimestamp:1789948800,exitTimestamp:1789948860,entryPrice:1,exitPrice:2,quantity:3,effectiveRevision:null,parameterRevision:99}]);
    assert.match(row.entryTimeDisplay,/2026.*\d{2}:\d{2}/);
    assert.match(row.exitTimeDisplay,/\d{2}:\d{2}/);
    assert.equal(row.entryDisplay,'1'); assert.equal(row.exitDisplay,'2'); assert.equal(row.quantityDisplay,'3');
    assert.equal(row.effectiveRevision,'—'); assert.equal(row.controlSource,'UNKNOWN');
    assert.equal(buildTradeRows([{}])[0].quantityDisplay,'—');
});
test('backend singular option names map to view options', () => {
    assert.deepEqual(buildFilterOptions({symbol:['X'],revision:[3],exitReason:['TP']}),{symbols:['X'],revisions:[3],exitReasons:['TP']});
});
test('loading error empty and filtered summary are preserved', () => {
    assert.equal(buildTradeHistoryViewModel({loading:true}).loading,true);
    assert.equal(buildTradeHistoryViewModel({error:'offline'}).error,'offline');
    assert.equal(buildTradeHistoryViewModel().available,false);
    const view=buildTradeHistoryViewModel({data:{available:true,metrics:{tradeCount:20},records:[{}],pagination:{page:2,pageSize:10,total:20,pageCount:2}}});
    assert.equal(view.metrics.tradeCount,20); assert.equal(view.pagination.rangeStart,11);
});

test('custom history queries wait for a complete ordered finite range', () => {
    assert.equal(isTradeHistoryQueryReady({period:'custom'}), false);
    assert.equal(isTradeHistoryQueryReady({period:'custom',fromTimestamp:10}), false);
    assert.equal(isTradeHistoryQueryReady({period:'custom',toTimestamp:20}), false);
    assert.equal(isTradeHistoryQueryReady({period:'custom',fromTimestamp:20,toTimestamp:10}), false);
    assert.equal(isTradeHistoryQueryReady({period:'custom',fromTimestamp:10,toTimestamp:20}), true);
    assert.equal(isTradeHistoryQueryReady({period:'custom',fromTimestamp:10,toTimestamp:30}), true);
    for (const period of ['today','7d','30d','90d','all']) {
        assert.equal(isTradeHistoryQueryReady({period}), true);
    }
});
