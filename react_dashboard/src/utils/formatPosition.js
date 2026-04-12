export function formatPosition(p) {
  return {
    pair: p?.pair ?? "-",
    side: p?.side ?? "-",
    entry: Number(p?.entry ?? 0),
    current: Number(p?.current ?? 0),
    pnl: Number(p?.pnl ?? 0),
    size: p?.size ?? "-"
  };
}