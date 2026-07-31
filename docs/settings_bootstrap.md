# Bootstrap of settings

## Scope

`config.settings.AppSettings` is the entire configuration contract
process. Bootstrap was expanded during Phase 10 to replace readers
and direct writers of UI, actions, dashboard, memory and local customers.

## Invariants

- The document must be JSON and its root must be an object.
- `gemini_api_key` and `os_system` must be strings.
- Standard OS can only be `windows`, `mac` or `linux`.
- The absence of the file allows you to boot UI/configuration without inventing a
credential.
- A consumer who needs Gemini calls
`require_gemini_api_key()` and receive `SettingsError` if missing.
- The key is excluded from the `repr` of the dataclass.
- Each route is read once and cached to a recharge or update
explicit.

The non-migrated fields are preserved in a mapping of extras and
`config.get_config()` maintains a dict view for compatibility.

## Reconfiguration

`update_settings()` is the only productive writer. It merges changes with the
view, validates the complete document and only then publishes an
temporary from the same directory using `fsync` + `os.replace`. The cache is
update under the same lock. UI, vision and memory use that operation; the loop
Live reuses snapshot to reconnect and reconstruct the adapter
search when an invalid key was replaced.

An event bus is not used for configuration, according to the steering document.

## Outstanding risks

The cache is local to each process: a manual external edition is not observed
up to `refresh_settings()` or a new process. No interprocess lock for
two simultaneous writers. Inherited adapters retain their functions
Auxiliaries, but delegate to the central owner.

## Rollback

`config.get_config()` and inherited auxiliary functions retain their
The rollback can redirect consumers to that view without changing the
physical format of the document.

## Verification

`tests/test_settings.py` covers missing file, corrupt JSON, invalid types,
cache, explicit refresh, atomic update, extras preservation,
no replacement rejection, missing key error, `repr` writing and
unique reading/writing ownership.
