# AI Advisor Production Configuration Matrix Candidate

Status: `CANDIDATE / NOT ACTIVE`

| Configuration | Safe default | Isolated smoke | General production candidate | Owner | Approval | Rollback | Class |
|---|---|---|---|---|---|---|---|
| `AI_ADVISOR_ENDPOINT_ENABLED` | false | true for isolated unit only | true after gateway prerequisites | Backend owner | Endpoint | false | Non-secret |
| `AI_ADVISOR_NETWORK_ALLOWED` | false | true for one-shot only | false until external review | Security owner | Network | false | Non-secret |
| `AI_ADVISOR_LIVE_TEST_ALLOWED` | false | true for one-shot only | false | Operator | Live request | false | Non-secret |
| `AI_ADVISOR_LIVE_KILL_SWITCH` | true | false only during one-shot | true until explicit approval | Operator | Kill switch | true | Non-secret |
| `AI_ADVISOR_BROWSER_GATEWAY_ENABLED` | false | false | true after proxy/bind review | Backend owner | Gateway | false | Non-secret |
| Trusted Proxy Allowlist | empty | empty | exact direct Nginx peer | Security owner | Proxy trust | empty | Non-secret |
| Exact Origin Allowlist | empty | empty | exact approved HTTPS origin | Security owner | Browser origin | empty | Non-secret |
| Authentication credential source | absent | encrypted artifact `/etc/credstore.encrypted/tradingai-ai-advisor-live-validation/AI_ADVISOR_AUTH_TOKEN` | separate production decision | Security owner | Credential placement | delete exact encrypted artifact | Secret reference |
| Provider credential source | absent | encrypted artifact `/etc/credstore.encrypted/tradingai-ai-advisor-live-validation/OPENAI_API_KEY` | unavailable pending approval | Security owner | Credential placement | revoke externally, then delete exact encrypted artifact | Secret reference |
| Isolated live unit | absent | transient `tradingai-ai-advisor-live-validation.service` via `systemd-run --wait --collect` | prohibited | Operator | Unit creation and live request are separate | collect transient unit; no daemon reload | Non-secret |
| Model | server default | `gpt-4o-mini` | server allowlist only | AI owner | Model | disabled | Non-secret |
| Official endpoint | unset | official allowlisted endpoint | official allowlisted endpoint | Security owner | Endpoint | unset | Non-secret |
| Output token budget | 4096 | 512 | separately approved | AI owner | Cost/data | 512 or disabled | Non-secret |
| Provider / endpoint timeout | 30s / 35s | 30s / 35s | 30s / 35s | Backend owner | Operations | defaults | Non-secret |
| Rate limit | 10 per 60s | one process invocation | 10 per 60s | Backend owner | Operations | disabled | Non-secret |
| Concurrency | 2 | one | 2 | Backend owner | Operations | disabled | Non-secret |
| Knowledge Retrieval | false | false | false pending manifest approval | Knowledge owner | Knowledge | false | Non-secret |
| External Context Transmission | false | false | false pending legal/security review | Security owner | External data | false | Non-secret |
| Observability Sink | no-op | request-scoped/no-op | approved content-free sink | Operations | Retention | no-op | Non-secret |

No row authorizes deployment. Secret values must never be added to this file.
