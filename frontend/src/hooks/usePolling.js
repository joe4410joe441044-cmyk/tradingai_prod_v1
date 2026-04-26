import { useEffect, useRef, useState } from "react";

/**
 * usePolling（安定版）
 * --------------------------------
 * - 初回即実行
 * - 定期polling
 * - 重複実行防止
 * - メモリリーク防止
 * - エラー管理
 * - UIは純粋にstate参照のみ
 */
export default function usePolling(fetchFn, interval = 5000) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(false);
  const [loading, setLoading] = useState(true);

  const savedFn = useRef(fetchFn);
  const timerRef = useRef(null);
  const runningRef = useRef(false);

  // 最新関数を保持
  useEffect(() => {
    savedFn.current = fetchFn;
  }, [fetchFn]);

  // 実行関数
  const run = async () => {
    // 🚨 重複実行防止（重要）
    if (runningRef.current) return;

    runningRef.current = true;

    try {
      setError(false);

      const result = await savedFn.current();

      setData(result);
    } catch (err) {
      console.error("usePolling error:", err);
      setError(true);
    } finally {
      setLoading(false);
      runningRef.current = false;
    }
  };

  useEffect(() => {
    let isMounted = true;

    const start = async () => {
      if (!isMounted) return;

      // 初回即実行
      await run();

      // 定期実行
      timerRef.current = setInterval(() => {
        run();
      }, interval);
    };

    start();

    // cleanup（重要）
    return () => {
      isMounted = false;

      if (timerRef.current) {
        clearInterval(timerRef.current);
      }
    };
  }, [interval]);

  return {
    data,
    error,
    loading,
  };
}