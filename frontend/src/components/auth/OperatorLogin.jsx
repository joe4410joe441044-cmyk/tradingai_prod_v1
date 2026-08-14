import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
    OPERATOR_AUTH_STATE,
    createOperatorAuthClient,
    setOperatorAuthStatus,
} from "../../features/auth/operatorAuth.js";

export default function OperatorLogin({
    authClient = null,
    onAuthChange = null,
}) {
    const [credential, setCredential] = useState("");
    const [status, setStatus] = useState(OPERATOR_AUTH_STATE.CHECKING);
    const [error, setError] = useState(null);
    const [loading, setLoading] = useState(false);
    const mountedRef = useRef(true);
    const client = useMemo(
        () => authClient || createOperatorAuthClient(),
        [authClient],
    );

    const checkStatus = useCallback(async () => {
        try {
            const result = await client.getStatus();
            if (mountedRef.current) {
                setStatus(result);
                onAuthChange?.(result);
                setOperatorAuthStatus(result);
            }
        } catch {
            if (mountedRef.current) {
                setStatus(OPERATOR_AUTH_STATE.UNAUTHENTICATED);
                onAuthChange?.(OPERATOR_AUTH_STATE.UNAUTHENTICATED);
                setOperatorAuthStatus(OPERATOR_AUTH_STATE.UNAUTHENTICATED);
            }
        }
    }, [client, onAuthChange]);

    useEffect(() => {
        mountedRef.current = true;
        checkStatus();
        return () => {
            mountedRef.current = false;
        };
    }, [checkStatus]);

    const handleLogin = useCallback(async (event) => {
        event.preventDefault();
        if (!credential.trim() || loading) return;
        setLoading(true);
        setError(null);
        try {
            await client.login(credential);
            if (mountedRef.current) {
                setCredential("");
                setLoading(false);
                checkStatus();
            }
        } catch (err) {
            if (mountedRef.current) {
                setError(err.code === "INVALID_CREDENTIAL"
                    ? "Invalid credential."
                    : "Authentication failed.");
                setStatus(OPERATOR_AUTH_STATE.UNAUTHENTICATED);
                setLoading(false);
                onAuthChange?.(OPERATOR_AUTH_STATE.UNAUTHENTICATED);
                setOperatorAuthStatus(OPERATOR_AUTH_STATE.UNAUTHENTICATED);
            }
        }
    }, [credential, loading, client, checkStatus, onAuthChange]);

    const handleLogout = useCallback(async () => {
        setLoading(true);
        try {
            await client.logout();
            if (mountedRef.current) {
                setStatus(OPERATOR_AUTH_STATE.UNAUTHENTICATED);
                setError(null);
                setLoading(false);
                onAuthChange?.(OPERATOR_AUTH_STATE.UNAUTHENTICATED);
                setOperatorAuthStatus(OPERATOR_AUTH_STATE.UNAUTHENTICATED);
            }
        } catch {
            if (mountedRef.current) {
                setStatus(OPERATOR_AUTH_STATE.UNAUTHENTICATED);
                setLoading(false);
                onAuthChange?.(OPERATOR_AUTH_STATE.UNAUTHENTICATED);
                setOperatorAuthStatus(OPERATOR_AUTH_STATE.UNAUTHENTICATED);
            }
        }
    }, [client, onAuthChange]);

    if (status === OPERATOR_AUTH_STATE.AUTHENTICATED) {
        return (
            <div className="operator-auth" aria-label="Operator session">
                <span className="operator-auth__status operator-auth__status--authenticated">
                    Authenticated（認証済み）
                </span>
                <button
                    disabled={loading}
                    onClick={handleLogout}
                    type="button"
                >
                    Logout（ログアウト）
                </button>
            </div>
        );
    }

    if (status === OPERATOR_AUTH_STATE.CHECKING) {
        return (
            <div className="operator-auth" aria-label="Operator session">
                <span className="operator-auth__status">Checking...</span>
            </div>
        );
    }

    return (
        <div className="operator-auth" aria-label="Operator authentication">
            <form onSubmit={handleLogin}>
                <label htmlFor="operator-credential">Operator Credential</label>
                <input
                    autoComplete="off"
                    disabled={loading}
                    id="operator-credential"
                    onChange={(event) => setCredential(event.target.value)}
                    placeholder="Enter credential"
                    type="password"
                    value={credential}
                />
                <button disabled={loading || !credential.trim()} type="submit">
                    {loading ? "Authenticating..." : "Login"}
                </button>
            </form>
            {error && (
                <p className="operator-auth__error" role="alert">
                    {error}
                </p>
            )}
        </div>
    );
}
