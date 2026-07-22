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
});

export const bilingual = (key) => {
    const [english, japanese] = MI_LABELS[key];
    return `${english}（${japanese}）`;
};

export const bilingualText = (english, japanese) => `${english}（${japanese}）`;
