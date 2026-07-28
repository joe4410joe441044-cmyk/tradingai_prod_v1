import { useState } from "react";

import MoneyManagementCardShell from "./MoneyManagementCardShell";

function ConfigurationField({
    disabled,
    error,
    field,
    onChange,
    value,
}) {
    const inputId = `mm-configuration-${field.key}`;
    const errorId = `${inputId}-error`;
    return (
        <div className="mm-configuration-field">
            <label htmlFor={inputId}>{field.label}</label>
            {field.type === "boolean" ? (
                <input
                    checked={value === true}
                    disabled={disabled}
                    id={inputId}
                    onChange={(event) => onChange({
                        [field.key]: event.target.checked,
                    })}
                    type="checkbox"
                />
            ) : (
                <div>
                    <input
                        aria-describedby={error ? errorId : undefined}
                        aria-invalid={Boolean(error)}
                        autoComplete="off"
                        disabled={disabled}
                        id={inputId}
                        inputMode="decimal"
                        onChange={(event) => onChange({
                            [field.key]: event.target.value,
                        })}
                        spellCheck="false"
                        type="text"
                        value={value ?? ""}
                    />
                    {error && (
                        <p className="mm-field-error" id={errorId}>
                            {error}
                        </p>
                    )}
                </div>
            )}
        </div>
    );
}

function ConfigurationConflictNotice({ conflict }) {
    if (!conflict) return null;
    return (
        <div className="mm-operation-notice mm-operation-notice--danger" role="alert">
            <strong>CONFIGURATION CONFLICT</strong>
            <p>
                Backend configuration changed while this draft was being
                edited. Latest backend configuration has been reloaded.
                Your unsaved draft has been preserved. Review the
                differences before saving again.
            </p>
            {conflict.rows.map((row) => (
                <dl className="mm-conflict-row" key={row.key}>
                    <dt>{row.label}</dt>
                    <dd>
                        <span>Backend</span>
                        <code>{row.backendValue}</code>
                        <span>Your Draft</span>
                        <code>{row.draftValue}</code>
                    </dd>
                </dl>
            ))}
        </div>
    );
}

export default function MoneyManagementConfigurationCard({
    draft,
    interaction,
    onDraftChange,
    onReset,
    onSave,
}) {
    const [feedback, setFeedback] = useState(null);
    const configuration = interaction.configuration;
    const editingDisabled =
        configuration.draftStatus === "SAVING CONFIGURATION";
    const showDisabledReason = configuration.saveDisabledReason &&
        !configuration.saveDisabledReason.includes("no unsaved changes");

    const change = (patch) => {
        setFeedback(null);
        onDraftChange(patch);
    };
    const reset = () => {
        setFeedback(null);
        onReset();
    };
    const save = async () => {
        setFeedback(null);
        const result = await onSave();
        if (result?.ok) setFeedback("Configuration saved");
    };

    return (
        <MoneyManagementCardShell
            className="mm-card--configuration"
            title="Configuration"
        >
            <dl className="mm-configuration-meta">
                <div>
                    <dt>Backend Revision</dt>
                    <dd>{configuration.revision}</dd>
                </div>
                <div>
                    <dt>Draft Status</dt>
                    <dd
                        data-status={configuration.draftStatus}
                    >
                        {configuration.draftStatus}
                    </dd>
                </div>
            </dl>
            <ConfigurationConflictNotice
                conflict={configuration.conflict}
            />
            {configuration.errorMessage && (
                <p className="mm-operation-notice mm-operation-notice--danger" role="alert">
                    {configuration.errorMessage}
                </p>
            )}
            <div className="mm-configuration-fields">
                {configuration.fields.map((field) => (
                    <ConfigurationField
                        disabled={editingDisabled}
                        error={configuration.fieldErrors[field.key]}
                        field={field}
                        key={field.key}
                        onChange={change}
                        value={draft?.[field.key]}
                    />
                ))}
            </div>
            <div className="mm-action-row">
                <button
                    disabled={Boolean(configuration.resetDisabledReason)}
                    onClick={reset}
                    title={configuration.resetDisabledReason ?? "Reset to backend configuration"}
                    type="button"
                >
                    Reset Draft
                </button>
                <button
                    disabled={Boolean(configuration.saveDisabledReason)}
                    onClick={save}
                    title={configuration.saveDisabledReason ?? "Save configuration"}
                    type="button"
                >
                    Save Configuration
                </button>
            </div>
            {showDisabledReason && (
                <p className="mm-disabled-reason">
                    {configuration.saveDisabledReason}
                </p>
            )}
            {feedback && (
                <p aria-live="polite" className="mm-operation-success">
                    {feedback}
                </p>
            )}
        </MoneyManagementCardShell>
    );
}
