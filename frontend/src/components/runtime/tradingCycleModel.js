const STAGES = [
    { index: 0, key: 'parameter', label: 'PARAMETER CONTEXT', japanese: 'パラメータコンテキスト' },
    { index: 1, key: 'marketSelection', label: 'MARKET SELECTION', japanese: '市場選定' },
    { index: 2, key: 'marketData', label: 'MARKET DATA', japanese: '市場データ' },
    { index: 3, key: 'featureBuilder', label: 'FEATURE BUILDER', japanese: 'フィーチャー構築' },
    { index: 4, key: 'microEdgeStrategy', label: 'MICRO EDGE STRATEGY', japanese: 'マイクロエッジ戦略' },
    { index: 5, key: 'aiDecision', label: 'AI DECISION / REVIEW', japanese: 'AI判断/レビュー' },
    { index: 6, key: 'moneyManagement', label: 'MONEY MANAGEMENT', japanese: '資金管理' },
    { index: 7, key: 'governance', label: 'GOVERNANCE', japanese: '安全判定' },
    { index: 8, key: 'execution', label: 'EXECUTION', japanese: '注文実行' },
    { index: 9, key: 'position', label: 'POSITION', japanese: 'ポジション' },
    { index: 10, key: 'exitMonitoring', label: 'EXIT MONITORING', japanese: 'エグジット監視' },
    { index: 11, key: 'settlement', label: 'SETTLEMENT', japanese: '決済' },
    { index: 12, key: 'positionClosed', label: 'POSITION CLOSED', japanese: 'ポジションクローズ' },
    { index: 13, key: 'performanceRecord', label: 'PERFORMANCE RECORD', japanese: 'パフォーマンス記録' },
    { index: 14, key: 'readyForNext', label: 'READY FOR NEXT TRADE', japanese: '次の取引準備完了' },
];

const STATUS = {
    COMPLETED: 'COMPLETED',
    CURRENT: 'CURRENT',
    BLOCKED: 'BLOCKED',
    WAITING: 'WAITING',
    NOT_REACHED: 'NOT_REACHED',
    UNKNOWN: 'UNKNOWN',
};

const display = (value, fallback = 'NOT AVAILABLE') => (
    value === null || value === undefined || value === '' ? fallback : String(value)
);

const yesNo = (value) => (value === true ? 'YES' : value === false ? 'NO' : '--');

const determineStageStatus = (stageIndex, currentStageIndex, blockedStageIndex) => {
    if (stageIndex < currentStageIndex) return STATUS.COMPLETED;
    if (stageIndex === currentStageIndex) return blockedStageIndex === stageIndex ? STATUS.BLOCKED : STATUS.CURRENT;
    if (stageIndex > currentStageIndex) return STATUS.NOT_REACHED;
    return STATUS.UNKNOWN;
};

const getSelectedSymbol = (decision) => {
    // 从现有数据中查找选中的symbol（需要根据实际API调整）
    // 这里假设可能在多个位置有symbol信息
    return decision?.stages?.market?.symbol || decision?.symbol || 'NOT AVAILABLE';
};

const getCurrentActivity = (decision, currentStageKey) => {
    const snapshot = decision || {};
    const stages = snapshot.stages || {};

    switch (currentStageKey) {
        case 'marketSelection':
            // 市场选择阶段的活动状态
            if (!stages.market?.symbol) return 'SCANNING / EVALUATING';
            return 'LOCK-ON';
        case 'marketData':
            if (snapshot.stale) return 'STALE DATA';
            return 'FETCHING / VERIFYING';
        case 'featureBuilder':
            return stages.pythonStrategy?.status ? 'BUILDING FEATURES' : 'WAITING';
        case 'microEdgeStrategy':
            return stages.pythonStrategy?.decision ? 'EVALUATING STRATEGY' : 'RUNNING ANALYSIS';
        case 'aiDecision':
            if (snapshot.tradingAiMode === 'OFF' || snapshot.tradingAiStatus === 'NOT_INSTALLED') return 'BYPASS';
            return 'AI REVIEW';
        case 'moneyManagement':
            return stages.moneyManagement?.status ? 'CALCULATING RISK' : 'WAITING';
        case 'governance':
            return stages.governance?.status ? 'CHECKING SAFETY' : 'WAITING';
        case 'execution':
            return stages.execution?.orderState ? 'EXECUTING ORDER' : 'READY TO EXECUTE';
        case 'position':
            return stages.execution?.positionState === 'POSITION OPEN' ? 'MONITORING POSITION' : 'WAITING';
        case 'exitMonitoring':
            return 'MONITORING EXIT CONDITIONS';
        case 'settlement':
            return 'SETTLING TRADE';
        case 'positionClosed':
            return 'POSITION CLOSED';
        case 'performanceRecord':
            return 'RECORDING PERFORMANCE';
        case 'readyForNext':
            return 'READY FOR NEXT TRADE';
        default:
            return 'UNKNOWN';
    }
};

const determineCurrentStage = (decision) => {
    const snapshot = decision || {};
    const stages = snapshot.stages || {};

    // 优先根据已有的tradingDecision或blockingStage判断
    if (snapshot.currentState === 'POSITION OPEN') return 9; // POSITION
    if (stages.execution?.positionState === 'POSITION OPEN') return 9; // POSITION
    
    // 基于blockingStage判断
    const blockingStage = String(snapshot.blockingStage || '').toUpperCase();
    if (blockingStage === 'MARKET') return 2; // MARKET DATA
    if (blockingStage === 'PYTHON STRATEGY') return 4; // MICRO EDGE STRATEGY
    if (blockingStage === 'MONEY MANAGEMENT') return 6;
    if (blockingStage === 'GOVERNANCE') return 7;
    if (blockingStage === 'EXECUTION') return 8;
    if (blockingStage === 'POSITION') return 9;

    // 默认阶段
    return 1; // MARKET SELECTION
};

const createTradingCycleModel = (decision) => {
    const snapshot = decision || {};
    const stages = snapshot.stages || {};
    
    // Priority: Use backend-projected values if available
    let currentStageIndex = snapshot.currentStageIndex;
    let currentActivity = snapshot.currentActivity;
    let selectedSymbol = snapshot.selectedSymbol || getSelectedSymbol(decision);
    let nextStage = null;

    // Handle STOPPED state specially
    if (currentStageIndex === null) {
        // No current stage when stopped
        const stageStatuses = STAGES.map(stage => ({
            ...stage,
            status: STATUS.NOT_REACHED,
        }));
        
        return {
            stages: stageStatuses,
            currentStage: null,
            currentStageIndex: null,
            currentActivity: currentActivity || 'BOT_STOPPED',
            nextStage: null,
            selectedSymbol,
        };
    }

    // Fallback to frontend logic if backend values not available
    if (currentStageIndex === undefined) {
        currentStageIndex = determineCurrentStage(decision);
    }

    if (!currentActivity) {
        const fallbackStage = STAGES.find(s => s.index === currentStageIndex);
        currentActivity = getCurrentActivity(decision, fallbackStage?.key);
    }

    // Determine stage statuses
    const blockedStageIndex = snapshot.blockingStage ? currentStageIndex : -1;
    const stageStatuses = STAGES.map(stage => ({
        ...stage,
        status: determineStageStatus(stage.index, currentStageIndex, blockedStageIndex),
    }));

    const currentStage = stageStatuses.find(s => s.index === currentStageIndex);
    
    // Get next stage from backend or calculate
    if (snapshot.nextStage) {
        nextStage = STAGES.find(s => s.label === snapshot.nextStage);
    } else if (currentStageIndex !== null && currentStageIndex < STAGES.length - 1) {
        nextStage = stageStatuses.find(s => s.index === currentStageIndex + 1);
    }

    return {
        stages: stageStatuses,
        currentStage,
        currentStageIndex,
        currentActivity,
        nextStage,
        selectedSymbol,
    };
};

export {
    STAGES,
    STATUS,
    createTradingCycleModel,
    display,
    yesNo,
};
