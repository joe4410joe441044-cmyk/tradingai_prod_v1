export const MI_LABELS = Object.freeze({
    position: ["Position", "対象ポジション"], mode: ["Mode", "モード"], timestamp: ["Timestamp", "時刻"],
    quality: ["Quality", "品質"], status: ["Status", "状態"], exchange: ["Exchange", "取引所"],
    market: ["Market", "市場"], symbol: ["Symbol", "銘柄"], source: ["Source", "データ元"],
    orderBook: ["ORDER BOOK / DOM", "板情報"], recentTrades: ["RECENT TRADES", "約定履歴"],
    aiFinalDecision: ["AI FINAL DECISION", "AI最終判断"], replayController: ["REPLAY CONTROLLER", "リプレイ操作"],
    decisionRailway: ["DECISION RAILWAY", "AI判断フロー"], replayInspector: ["REPLAY INSPECTOR", "リプレイ詳細"],
    replayTimeline: ["REPLAY TIMELINE", "イベントタイムライン"], price: ["Price", "価格"], size: ["Size", "数量"],
    total: ["Total", "累積"], time: ["Time", "時刻"], side: ["Side", "売買"], marker: ["Marker", "マーカー"],
    finalDirection: ["Final Direction", "最終方向"], confidence: ["Confidence", "信頼度"], reason: ["Reason", "理由"],
    strategyCandidate: ["Strategy Candidate", "戦略候補"], aiReviewResult: ["AI Review Result", "AI審査結果"],
    governanceResult: ["Governance Result", "安全判定"], executionResult: ["Execution Result", "実行結果"],
    dataQuality: ["Data Quality", "データ品質"], currentEvent: ["Current Event", "現在イベント"],
    eventType: ["Event Type", "イベント種別"], sequence: ["Sequence", "順序"], progress: ["Progress", "進捗"],
    currentCursor: ["Current Cursor", "現在カーソル"], seek: ["Seek", "移動"],

    /* G6 — Market Intelligence bilingual label additions (EN / 日本語). */
    marketView: ["MARKET VIEW", "市場情報"],
    currentPrice: ["CURRENT PRICE", "現在価格"],
    bestBid: ["BEST BID", "最良買値"], bestAsk: ["BEST ASK", "最良売値"], spread: ["SPREAD", "スプレッド"],
    both: ["BOTH", "両方"], bids: ["BIDS", "買板"], asks: ["ASKS", "売板"],
    rows: ["ROWS", "行数"], askLevels: ["ASK LEVELS", "売板"], bidLevels: ["BID LEVELS", "買板"],
    timeLocal: ["TIME (LOCAL)", "時刻"], priceUpper: ["PRICE", "価格"], sizeUpper: ["SIZE", "数量"],
    sideUpper: ["SIDE", "売買"], markerUpper: ["MARKER", "マーカー"],
    visibleDepthRatio: ["VISIBLE DEPTH RATIO", "表示板厚比率"],
    bookSummary: ["Book Summary", "板サマリー"], tradeSummary: ["Trade Summary", "約定サマリー"],
    marketMetrics: ["Market Metrics", "市場指標"],
    diagnosticsSection: ["Diagnostics", "診断"],
    marketAnalysisDetails: ["Market Analysis Details", "市場分析詳細"],
    markerDetails: ["Marker Details", "マーカー詳細"],
    markerInspector: ["MARKER INSPECTOR", "マーカー検査"], selectMarker: ["SELECT A MARKER", "マーカーを選択"],
    markerType: ["Marker Type", "マーカー種別"], quantity: ["Quantity", "数量"],
});

export const bilingual = (key) => {
    const [english, japanese] = MI_LABELS[key];
    return `${english}（${japanese}）`;
};

export const bilingualText = (english, japanese) => `${english}（${japanese}）`;

/* Preferred G6 standard: ENGLISH / 日本語. */
export const bilingualSlash = (key) => {
    const [english, japanese] = MI_LABELS[key];
    return `${english} / ${japanese}`;
};

export const bilingualSlashText = (english, japanese) => `${english} / ${japanese}`;
