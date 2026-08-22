import assert from 'node:assert/strict';
import test from 'node:test';
import { STAGES, STATUS, createTradingCycleModel } from './tradingCycleModel.js';

test('tradingCycleModel - STAGES should have exactly 15 stages', () => {
    assert.equal(STAGES.length, 15);
});

test('tradingCycleModel - STAGES should have stages in correct order from 0 to 14', () => {
    STAGES.forEach((stage, index) => {
        assert.equal(stage.index, index);
    });
});

test('tradingCycleModel - STOPPED with currentStageIndex null should have no current stage, all NOT_REACHED', () => {
    const model = createTradingCycleModel({
        currentStage: null,
        currentStageIndex: null,
        currentActivity: 'BOT_STOPPED',
        nextStage: null,
    });
    
    assert.strictEqual(model.currentStage, null);
    assert.strictEqual(model.currentStageIndex, null);
    assert.strictEqual(model.currentActivity, 'BOT_STOPPED');
    assert.strictEqual(model.nextStage, null);
    
    const currentStages = model.stages.filter(stage => stage.status === STATUS.CURRENT);
    assert.strictEqual(currentStages.length, 0);
    
    const allNotReached = model.stages.every(stage => stage.status === STATUS.NOT_REACHED);
    assert.strictEqual(allNotReached, true);
});

test('tradingCycleModel - null currentStageIndex should not coerce to 0', () => {
    const model = createTradingCycleModel({
        currentStage: null,
        currentStageIndex: null,
        currentActivity: 'BOT_STOPPED',
        nextStage: null,
    });
    
    assert.notStrictEqual(model.currentStageIndex, 0);
    
    const stage0 = model.stages.find(stage => stage.index === 0);
    assert.notStrictEqual(stage0.status, STATUS.CURRENT);
});

test('tradingCycleModel - MARKET DATA should have only Stage 2 CURRENT', () => {
    const model = createTradingCycleModel({
        currentStage: 'MARKET DATA',
        currentStageIndex: 2,
        currentActivity: 'ANALYZING MARKET',
        nextStage: 'STRATEGY SELECTION',
    });
    
    assert.strictEqual(model.currentStageIndex, 2);
    
    const currentStages = model.stages.filter(stage => stage.status === STATUS.CURRENT);
    assert.strictEqual(currentStages.length, 1);
    assert.strictEqual(currentStages[0].index, 2);
});

test('tradingCycleModel - MICRO EDGE STRATEGY should have only Stage 4 CURRENT', () => {
    const model = createTradingCycleModel({
        currentStage: 'MICRO EDGE STRATEGY',
        currentStageIndex: 4,
        currentActivity: 'ANALYZING MICRO EDGE',
        nextStage: 'MONEY MANAGEMENT',
    });
    
    assert.strictEqual(model.currentStageIndex, 4);
    
    const currentStages = model.stages.filter(stage => stage.status === STATUS.CURRENT);
    assert.strictEqual(currentStages.length, 1);
    assert.strictEqual(currentStages[0].index, 4);
});

test('tradingCycleModel - MONEY MANAGEMENT should have only Stage 6 CURRENT', () => {
    const model = createTradingCycleModel({
        currentStage: 'MONEY MANAGEMENT',
        currentStageIndex: 6,
        currentActivity: 'CALCULATING MM',
        nextStage: 'RISK ASSESSMENT',
    });
    
    assert.strictEqual(model.currentStageIndex, 6);
    
    const currentStages = model.stages.filter(stage => stage.status === STATUS.CURRENT);
    assert.strictEqual(currentStages.length, 1);
    assert.strictEqual(currentStages[0].index, 6);
});

test('tradingCycleModel - should return model with all stages', () => {
    const model = createTradingCycleModel({});
    assert.equal(model.stages.length, 15);
});

test('tradingCycleModel - should have only one current stage', () => {
    const model = createTradingCycleModel({});
    const currentStages = model.stages.filter(stage => stage.status === STATUS.CURRENT);
    assert.ok(currentStages.length <= 1);
});

test('tradingCycleModel - should have completed stages before current', () => {
    const model = createTradingCycleModel({});
    const currentIndex = model.currentStageIndex;
    const completedStages = model.stages.filter(stage => stage.status === STATUS.COMPLETED);
    completedStages.forEach(stage => {
        assert.ok(stage.index < currentIndex);
    });
});

test('tradingCycleModel - should mark future stages as NOT_REACHED', () => {
    const model = createTradingCycleModel({});
    const currentIndex = model.currentStageIndex;
    const futureStages = model.stages.filter(stage => stage.index > currentIndex);
    futureStages.forEach(stage => {
        assert.equal(stage.status, STATUS.NOT_REACHED);
    });
});

test('tradingCycleModel - should handle position open state', () => {
    const decision = {
        currentState: 'POSITION OPEN',
        stages: {
            execution: {
                positionState: 'POSITION OPEN',
            },
        },
    };
    const model = createTradingCycleModel(decision);
    assert.equal(model.currentStageIndex, 9); // POSITION stage
});

test('tradingCycleModel - should return NOT AVAILABLE for selected symbol when not provided', () => {
    const model = createTradingCycleModel({});
    assert.equal(model.selectedSymbol, 'NOT AVAILABLE');
});

test('tradingCycleModel - should display selected symbol from decision data', () => {
    const symbol = 'BTC/USDT';
    const model = createTradingCycleModel({
        stages: {
            market: {
                symbol,
            },
        },
    });
    assert.equal(model.selectedSymbol, symbol);
});

test('tradingCycleModel - should handle AI disabled state', () => {
    const model = createTradingCycleModel({
        tradingAiMode: 'OFF',
        tradingAiStatus: 'NOT_INSTALLED',
    });
    assert.ok(model.currentActivity);
});
