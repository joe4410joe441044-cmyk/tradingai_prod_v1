import { STAGES, STATUS, createTradingCycleModel } from './tradingCycleModel.js';

describe('tradingCycleModel', () => {
    describe('STAGES', () => {
        it('should have exactly 15 stages', () => {
            expect(STAGES.length).toBe(15);
        });

        it('should have stages in correct order from 0 to 14', () => {
            STAGES.forEach((stage, index) => {
                expect(stage.index).toBe(index);
            });
        });
    });

    describe('createTradingCycleModel', () => {
        it('should return model with all stages', () => {
            const model = createTradingCycleModel({});
            expect(model.stages.length).toBe(15);
        });

        it('should have only one current stage', () => {
            const model = createTradingCycleModel({});
            const currentStages = model.stages.filter(stage => stage.status === STATUS.CURRENT);
            expect(currentStages.length).toBeLessThanOrEqual(1);
        });

        it('should have completed stages before current', () => {
            const model = createTradingCycleModel({});
            const currentIndex = model.currentStageIndex;
            const completedStages = model.stages.filter(stage => stage.status === STATUS.COMPLETED);
            completedStages.forEach(stage => {
                expect(stage.index).toBeLessThan(currentIndex);
            });
        });

        it('should mark future stages as NOT_REACHED', () => {
            const model = createTradingCycleModel({});
            const currentIndex = model.currentStageIndex;
            const futureStages = model.stages.filter(stage => stage.index > currentIndex);
            futureStages.forEach(stage => {
                expect(stage.status).toBe(STATUS.NOT_REACHED);
            });
        });

        it('should handle position open state', () => {
            const decision = {
                currentState: 'POSITION OPEN',
                stages: {
                    execution: {
                        positionState: 'POSITION OPEN',
                    },
                },
            };
            const model = createTradingCycleModel(decision);
            expect(model.currentStageIndex).toBe(9); // POSITION stage
        });

        it('should return NOT AVAILABLE for selected symbol when not provided', () => {
            const model = createTradingCycleModel({});
            expect(model.selectedSymbol).toBe('NOT AVAILABLE');
        });

        it('should display selected symbol from decision data', () => {
            const symbol = 'BTC/USDT';
            const model = createTradingCycleModel({
                stages: {
                    market: {
                        symbol,
                    },
                },
            });
            expect(model.selectedSymbol).toBe(symbol);
        });

        it('should handle AI disabled state', () => {
            const model = createTradingCycleModel({
                tradingAiMode: 'OFF',
                tradingAiStatus: 'NOT_INSTALLED',
            });
            expect(model.currentActivity).toBeDefined();
        });
    });
});
