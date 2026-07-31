# Provider adapters

## Limit

Use cases should not import SDKs from models, read credentials, or choose
models. `core.providers` declares four ports:

- `LiveConversationProvider`;
- `TextGenerationProvider`;
- `VisionAnalysisProvider`;
- `GroundedSearchProvider`.

Phase 9 migrates productively only `web_search`. The other three contracts
allow subsequent migrations without changing at once audio, camera or
actions that generate text.

## Search Pilot

`JarvisLive` builds `GoogleGroundedSearchProvider` after the
local configuration is available and injects it into both paths of
`web_search`. The action only calls `provider.search(query)` and preserves
Duck DuckGo as a standalone backend.

The adapter owns:

- primary and fallback models;
- HTTP timeout in milliseconds;
- Google settings grounded search;
- extraction and validation of the response;
- Timeout classification, quota, transient failure and permanent failure.

A transient 5xx can test the next model. A 429 does not model
hopping: becomes `ProviderQuotaError` so that the case of use changes from
backend. A 403 or other permanent error also does not retry another model.

## Security

The credential only enters `from_api_key()` and is not saved in errors,
results or logs. Tests use fake clients; do not read `api_keys.json`, no
open network and do not record prompts or real answers.

## Rollback

The public firm `web_search` retains its previous arguments and adds a
optional provider. Removing the pilot requires re-injecting an adapter
compatibility; DDG still works when there is no provider.

## Verification

`tests/test_provider_adapters.py` covers contracts, injection, failback
backend, model fallback, timeout, quota, permanent errors and answers
empty. `tests/test_clock.py` uses a fake provider to verify the date of
news without SDK or network.
