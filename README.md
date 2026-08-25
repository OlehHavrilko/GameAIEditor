# GameAIEditor

> Рабочий production MVP для локального анализа игровых записей и сборки highlight-монтажей. Это ещё не коммерческий видеоредактор: текущий фокус — надёжный pipeline, resumable sessions и FFmpeg.

**[⬇ Скачать Windows-инсталлятор (последняя версия)](https://github.com/OlehHavrilko/GameAIEditor/releases/latest)** — не требует прав администратора; ставится только FFmpeg (см. предупреждение при установке).

Инструмент для поиска и монтажа лучших моментов из игровых видео, полностью локальный и работающий из коробки без AI-провайдера: motion/audio/speech-сигналы и классификация событий по ключевым словам транскрипта уже дают полноценный результат. Ollama Vision — опциональный, выключенный по умолчанию слой для более тонкого разбора сцен; включать его не обязательно. Первый game profile — **Arma Reforger**, а pipeline не содержит game-specific orchestration.

Программа анализирует видео, находит интересные моменты, оценивает их, собирает таймлайн, рендерит MP4 и запускает проверки качества.

## Производительность

Анализ 10-минутного геймплейного ролика (720p) выполняется целиком за секунды, а не за минуты:

| Стадия | Раньше | Сейчас |
|---|---|---|
| Motion-анализ | покадровый decode через OpenCV, ~22.5 сек | один проход ffmpeg с downscale, ~3.2 сек |
| Audio + motion + transcription | последовательно, ~26.8 сек | параллельно (ThreadPoolExecutor), ~4 сек |
| Prefilter | всегда выполнялся | пропускается полностью, если Vision выключен |
| **Весь пайплайн end-to-end** | — | **~10 сек** |

## Как это работает

```text
video -> metadata -> [prefilter + Vision, опционально] -> signals (motion/audio/speech, параллельно) -> fusion -> Event Arc -> scoring -> selection -> timeline -> MP4 -> QC
```

Классификация типа события (headshot, multi_kill, ambush, squad_coordination и т.д.) определяется по ключевым словам в транскрипте речи/рации плюс motion/audio-эвристике — без обращения к AI. Vision, если включён, дополняет эту классификацию, а не заменяет её.

Проект использует:

- Python 3.11+
- FFmpeg и FFprobe
- OpenCV
- faster-whisper для распознавания речи
- Pydantic и JSON-профили игр
- Ollama Vision (опционально, выключено по умолчанию) для дополнительного анализа сцен
- PySide6 desktop application

## Установка

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

FFmpeg и FFprobe должны быть доступны в `PATH`. `torch` — опциональная зависимость (нужна только для GPU-диагностики в desktop-приложении, не для самого пайплайна); ставится отдельно через `pip install -e ".[gpu-diagnostics]"`, если нужна.

## Основные команды

Desktop application:

```powershell
game-ai-editor desktop
```

Можно запускать этапы отдельно:

```powershell
game-ai-editor analyze input\video.mp4
game-ai-editor detect work\video_session
game-ai-editor select work\video_session
game-ai-editor edit work\video_session
game-ai-editor render work\video_session
game-ai-editor qc work\video_session
```

Запуск полного пайплайна:

```powershell
game-ai-editor all input\video.mp4 --aspect 9:16 --subtitles
```

`--aspect` (`16:9`/`9:16`/`1:1`, по умолчанию — формат исходника) и `--subtitles` (burn-in субтитров из транскрипта) доступны в `all`, `edit` и `batch`.

`all` и `batch` используют `ProductionOrchestrator`. При включённом Vision он анализирует только окна, прошедшие prefilter; при выключенном (по умолчанию) сама стадия prefilter не запускается. Пустой результат получает статус `NO_HIGHLIGHTS`, fake video не создаётся.

Другие полезные команды:

```powershell
game-ai-editor prefilter input\video.mp4
game-ai-editor batch input
game-ai-editor vision-scan input\video.mp4 --prefilter
```

Batch продолжает обработку после ошибки одного видео и сохраняет production session artifacts в `work/sessions/<session_id>/`; результаты публикуются только в canonical `output/<project_id>/`.

## AI providers (опционально)

Vision по умолчанию выключен (`vision.enabled: false` в game profile) — pipeline не запускает ни один AI provider, а prefilter-стадия при этом полностью пропускается, так что запуск без Vision не платит и за неё. Включать Vision имеет смысл только когда нужна более точная классификация сцен сверх того, что уже даёт motion/audio/keyword-анализ.

Если решишь включить, provider выбирается через game profile или desktop settings:

- `ollama` — local-first endpoint, по умолчанию `http://localhost:11434`;
- `lm_studio` — OpenAI-compatible local endpoint;
- `openrouter` — OpenAI-compatible remote endpoint;
- `custom` — OpenAI-compatible endpoint.

Ollama и LM Studio не отправляют кадры в интернет. Для OpenRouter API key передаётся через environment variable и не хранится в Git.

В профиле Vision используются `enabled`, `provider`, `base_url`, `model`, `timeout`.

## Структура проекта и storage contract

- `input/` - исходные пользовательские видео, которые не должны копироваться в Git и не должны попадать в `work/` без явной необходимости;
- `work/` - промежуточные artifacts и session-local data, включая `work/sessions/<session_id>/...`;
- `output/` - пользовательские готовые видео, только здесь должен жить production output;
- `finalvids/` - legacy/deprecated compatibility directory, не использовать для новых production paths;
- `tests/` - автоматические тесты.

Расположение `input/`/`work/`/`output/` резолвится через `game_ai_editor.paths.data_root()`: в dev-режиме это корень репозитория, в собранном Windows-инсталляторе — папка рядом с exe, а desktop-приложение может переопределить его на выбранную пользователем директорию.

Canonical production output:

```text
output/<project_id>/final.mp4
output/<project_id>/preview.mp4
```

`status.json` и backend result payload обязаны содержать абсолютный или repo-relative путь к финальному output. UI получает путь из backend artifact contract и не вычисляет его самостоятельно.

Каждый запуск сохраняет JSON-файлы с метаданными, движением, транскрипцией, событиями, кандидатами, выбором моментов, таймлайном и результатами QC.

## Текущее состояние

Проект находится в стадии **Production MVP hardening**. Legacy stage commands сохранены для совместимости, но production-команды используют единый `ProductionOrchestrator`.

Уже реализовано:

- получение метаданных и анализ аудио;
- анализ движения (ffmpeg-based) и поиск событий-кандидатов, включая keyword-классификацию по транскрипту (headshot, multi_kill, ambush, squad_coordination и другие типы сверх базовой motion-эвристики);
- распознавание речи;
- параллельная обработка audio/motion/transcription стадий;
- оценка и выбор лучших моментов;
- построение таймлайна и preview/render через FFmpeg, с опциональными пресетами формата (16:9/9:16/1:1) и burn-in субтитров;
- пакетная обработка видео и продолжение незавершённых запусков;
- отдельные тесты и сканирование через Ollama Vision;
- автоматические тесты основного пайплайна и vision-модулей;
- synthetic orchestrator E2E с mock Vision и реальным FFmpeg/QC.

Дополнительно реализованы:

- first-run diagnostics и optional local AI setup;
- cancellable model download и analysis workers;
- persistent queue с pause/resume/cancel/retry и stale-session recovery;
- Results workflow из реальных artifacts с изменением selection и повторным render;
- structured error UX и degraded Vision mode;
- PyInstaller one-directory packaging для Windows.

Сознательно отложено: музыкальная дорожка и intro/outro — ждут отдельной фичи-библиотеки ассетов (по аналогии с CapCut), а не auto-mixing произвольных файлов.

Ограничения текущей версии: коммерческий installer/updater, сложные эффекты, полноценная non-linear редактура, дополнительные game profiles требуют следующих этапов.

## Проверка

```powershell
.venv\Scripts\pytest -q
.venv\Scripts\python.exe -c "from game_ai_editor.desktop.app import MainWindow; print('ui-import-ok')"
.venv\Scripts\python.exe -m game_ai_editor system-status
.venv\Scripts\python.exe -m game_ai_editor runtime-status
```

Реальный Ollama smoke test является manual-only и не запускается обычным `pytest`.

## Packaging

```powershell
.venv\Scripts\python.exe -m pip install pyinstaller
.venv\Scripts\python.exe -m PyInstaller packaging\game_ai_editor.spec
```

Подробности: [docs/PACKAGING.md](docs/PACKAGING.md). Для разработки PyInstaller не обязателен.

## Документация

- [Architecture](ARCHITECTURE.md)
- [Development guide](docs/DEVELOPMENT.md)
- [Production pipeline](docs/PIPELINE.md)
- [AI providers](docs/AI_PROVIDERS.md)
- [Packaging](docs/PACKAGING.md)
- [Contributing](CONTRIBUTING.md)
