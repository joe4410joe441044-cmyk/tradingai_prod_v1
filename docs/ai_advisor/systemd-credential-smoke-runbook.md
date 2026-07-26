# AI Advisor isolated systemd credential smoke runbook

This runbook is preparation only. It does not authorize a live request.

## Preconditions

- AI Advisor tests and `git diff --check` pass.
- The normal `tradingbot.service` remains endpoint-disabled, network-disabled,
  live-test-disabled, and kill-switch-active.
- The isolated unit is not installed from an unresolved example template.
- The approved model is `gpt-4o-mini`; output tokens are fixed at 512.
- Retry, streaming, tools, storage, and automatic fallback remain disabled.

## Credential preparation

1. Prefer `LoadCredentialEncrypted` on systemd 252.
2. Use `LoadCredential` only when the encrypted facility cannot be used under
   the approved operator policy.
3. Prepare both credentials without a trailing newline:
   `AI_ADVISOR_AUTH_TOKEN` and `OPENAI_API_KEY`.
4. Never place credential content in the repository, normal EnvironmentFile,
   command line, shell history, unit text, or this runbook.
5. Replace example placeholders only in an operator-controlled unit outside
   the repository. Do not modify `tradingbot.service`.

## Preflight and one-shot

1. Confirm both systemd credential probes return `AVAILABLE`; do not inspect
   content, size, path, timestamps, inode, or hashes.
2. Confirm the isolated unit uses the project virtualenv and invokes only the
   isolated smoke CLI. It must not start Uvicorn or listen on a port.
3. Confirm the official endpoint, model, token budget, timeout, and unused
   one-shot permit.
4. Obtain the separately issued exact one-request approval. Enter it only at
   the isolated operator TTY prompt; it is not authentication or authorization.
5. Start the isolated oneshot once through the approved operator procedure.
6. Record only the safe result and aggregate token usage.
7. Do not make a second provider request. The second-call check is an offline
   gate assertion, not authorization to issue another live call.

## Shutdown and failure

For authentication, authorization, credential, gate, connection, timeout,
provider, parsing, validation, usage, or unexpected failure:

1. Do not retry.
2. Do not regenerate the permit, restart the process, switch models, increase
   token budget, or use the fallback model.
3. Let the isolated oneshot terminate.
4. Remove the operator-controlled isolated unit and credential material using
   the approved secret-management procedure.
5. Confirm no credential remains available to the terminated process.
6. Reconfirm the normal `tradingbot.service` safety state without changing or
   restarting it.
7. Report only the fixed safe failure classification.
