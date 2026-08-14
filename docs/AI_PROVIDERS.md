# AI Providers

All providers implement `VisionProvider`.

Supported provider names:

- `ollama` for local Ollama;
- `lm_studio` for a local OpenAI-compatible endpoint;
- `openrouter` for OpenRouter;
- `custom` for another OpenAI-compatible endpoint.

Configuration is read from the game profile or supplied by the desktop settings. API keys are resolved from `${env:VARIABLE_NAME}` and are never written to artifacts or logs.

Local providers keep frames on the local machine. Remote providers should be enabled only when the user accepts external data transfer.