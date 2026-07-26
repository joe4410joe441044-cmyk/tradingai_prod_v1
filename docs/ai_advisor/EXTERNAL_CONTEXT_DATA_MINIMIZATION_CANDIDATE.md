# AI Advisor External Context Data-Minimization Candidate

Status: `CANDIDATE / NOT APPROVED / NOT ACTIVE`

This contract does not authorize credentials, network access, provider calls,
Knowledge activation, or external transmission.

## Release modes

| Mode | Allowed payload | Maximum | Forbidden | Current decision |
|---|---|---:|---|---|
| Isolated Smoke | One fixed synthetic prompt and opaque request metadata | 16,384 UTF-8 bytes input; 512 output tokens | Project documents, Runtime, conversation, identity, trading data, personal data | Eligible only for separately approved one-shot |
| Browser General Guidance | None | 0 | All user and project context | Unavailable; external transmission not approved |
| Grounded Specification | None | 0 | Source text, excerpts, paths, Runtime and conversation | Unavailable; manifest and external transmission not approved |

## Field policy

Allowed for an approved isolated smoke:

- fixed synthetic prompt;
- opaque request ID;
- provider/model identifier selected by server policy;
- strict response-format identifier;
- request-scoped size and timeout limits.

Always forbidden:

- source document or excerpt;
- Runtime, market, Money Management, Governance or Execution data;
- conversation history or persistent conversation identity;
- browser principal, cookie, authorization header or session;
- API keys, credential references, environment data and file paths;
- raw logs, manager objects, private reasoning and system prompts;
- provider, model, endpoint, tool or network override from a client.

## Undecided approvals

The following remain undecided and therefore fail closed:

- provider retention;
- provider training-use;
- region and legal review;
- approved document/excerpt size;
- approved source types and versions;
- data-subject and tenant separation;
- audit retention and deletion.

## Controls

The live kill switch remains active by default. Network invocation, endpoint,
Knowledge retrieval and external context transmission are separate gates.
Enabling one gate never enables another.

Audit may contain only opaque request ID, fixed category/status, safe failure
code, approved source IDs, freshness, latency and token counts. Prompt,
response, source content, identity and credentials are forbidden.
