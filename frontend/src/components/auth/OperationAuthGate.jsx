import { useEffect, useState } from "react";

import {
    OPERATOR_AUTH_STATE,
    getOperatorAuthStatus,
    subscribeOperatorAuthStatus,
} from "../../features/auth/operatorAuth";
import OperatorLogin from "./OperatorLogin";

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
