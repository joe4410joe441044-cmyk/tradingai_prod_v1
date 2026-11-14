import { useEffect, useState } from "react";

import {
    OPERATOR_AUTH_STATE,
    getOperatorAuthStatus,
    subscribeOperatorAuthStatus,
} from "../../features/auth/operatorAuth";
import OperatorLogin from "./OperatorLogin";
import { HYRO_TRIAL_OPERATOR_ENABLED } from "../../features/prop-accounts/hyroTrialOperatorFeature.js";

export default function OperationAuthGate({
    authClient = null,
    children,
}) {
    const [status, setStatus] = useState(() => (
        getOperatorAuthStatus() ?? OPERATOR_AUTH_STATE.CHECKING
    ));

    useEffect(() => (
        subscribeOperatorAuthStatus((next) => setStatus(next))
    ), []);

    if (HYRO_TRIAL_OPERATOR_ENABLED) {
        return (
            <fieldset
                className="operation-auth-gate operation-auth-gate--preview-disabled"
                data-testid="preview-disabled-kucoin-controls"
                disabled
            >
                <legend>KuCoin既存PAPER / LIVE操作（隔離プレビューでは操作無効）</legend>
                {children}
            </fieldset>
        );
    }

    const authenticated = status === OPERATOR_AUTH_STATE.AUTHENTICATED;

    return (
        <div className="operation-auth-gate" data-testid="operation-auth-gate">
            <OperatorLogin
                authClient={authClient}
                onAuthChange={setStatus}
            />
            {authenticated ? (
                children
            ) : (
                <div
                    className="operation-auth-gate__notice"
                    role="status"
                    data-testid="operation-auth-gate-notice"
                >
                    Operator認証後に操作を開始できます。 Log in as the
                    operator to enable Operation control.
                </div>
            )}
        </div>
    );
}
