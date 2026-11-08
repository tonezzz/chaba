---
category: operations
type: runbook
status: defined
---

# Jack OpenCode Provider and Ada Configuration

## Source of truth

The Jack worker's provider/agent configuration is committed at:

```text
stacks/idc02/jack-ide/opencode/opencode.json
```

The deployed host copy is:

```text
~/.config/jack-ide/opencode.json
```

The Quadlet mounts that file read-only into the container:

```text
~/.config/jack-ide/opencode.json
  -> /home/opencode/.config/opencode/opencode.json
```

The worker's LiteLLM provider and model selector read this mounted file.

## Runtime home versus provider config

The disposable OpenCode home is:

```text
~/.local/share/jack-ide/opencode-home
```

It stores session/cache state and the model cache. It is not the canonical provider config when the Quadlet's explicit read-only config mount is present.

The LiteLLM credential must remain server-side in:

```text
~/.config/secrets/jack-ide.env
```

and/or the protected OpenCode auth store. Never place the key in the committed JSON or browser-visible URL.

An empty file at:

```text
~/.local/share/jack-ide/opencode-home/.config/opencode/opencode.json
```

is not the source of truth under the current Quadlet. Do not fix provider drift by copying secrets into it.

## Ada worker profile

The committed config defines an `ada` primary agent using:

```text
litellm/gemini-3.5-flash-lite
```

This makes Ada selectable in the OpenCode worker while preserving the worker boundary. It does not give the Jack worker Ada voice-memory access; that remains a separate Ada-control-plane integration.

## Verification

On `idc02`:

```bash
systemctl --user restart jack-opencode
podman exec jack-opencode node -e 'fetch("http://127.0.0.1:4096/global/config", {headers:{authorization:"Basic "+Buffer.from("opencode:"+process.env.OPENCODE_SERVER_PASSWORD).toString("base64")}}).then(r=>r.text()).then(console.log)'
```

Confirm:

- `provider.litellm` exists;
- `model` is a served LiteLLM alias;
- `agent.ada.model` is a served LiteLLM alias;
- the auth key is not present in the returned config;
- the OpenCode UI can select the Ada agent and LiteLLM model.
