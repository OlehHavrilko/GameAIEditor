# Game AI Editor

Локальный AI-инструмент для поиска и монтажа лучших моментов из игровых видео. Первый game profile — **Arma Reforger**, а pipeline не содержит game-specific orchestration.

Программа анализирует видео, находит интересные моменты, оценивает их, собирает таймлайн, рендерит MP4 и запускает проверки качества.

## Как это работает

```text
video -> metadata -> prefilter -> signals + Vision -> fusion -> Event Arc -> scoring -> selection -> timeline -> MP4 -> QC
```

Проект использует:

- Python 3.11+
- FFmpeg и FFprobe
- OpenCV
- faster-whisper для распознавания речи
- Pydantic и JSON-профили игр
- Ollama Vision для дополнительного анализа сцен
- PySide6 desktop application

## Установка

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

FFmpeg и FFprobe должны быть доступны в `PATH`.

## Основные команды

Desktop application:

```powershell
game-ai-editor desktop
```

Единый production pipeline:

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
game-ai-editor all input\video.mp4
```

`all` и `batch` используют `ProductionOrchestrator`. При включённом Vision он анализирует только окна, прошедшие prefilter. Пустой результат получает статус `NO_HIGHLIGHTS`, fake video не создаётся.

Другие полезные команды:

```powershell
game-ai-editor prefilter input\video.mp4
game-ai-editor batch input
game-ai-editor vision-scan input\video.mp4 --prefilter
```

Batch продолжает обработку после ошибки одного видео и сохраняет session artifacts в `work/batch/`.

## AI providers

Provider выбирается через game profile или desktop settings:

- `ollama` — local-first endpoint, по умолчанию `http://localhost:11434`;
- `lm_studio` — OpenAI-compatible local endpoint;
- `openrouter` — OpenAI-compatible remote endpoint;
- `custom` — OpenAI-compatible endpoint.

Ollama и LM Studio не отправляют кадры в интернет. Для OpenRouter API key передаётся через environment variable и не хранится в Git.

В профиле Vision используются `enabled`, `provider`, `base_url`, `model`, `timeout`.

## Структура проекта

- `src/game_ai_editor/` - основной код;
- `config/games/` - настройки игр;
- `input/` - исходные видео;
- `work/` - промежуточные файлы анализа;
- `output/` и `finalvids/` - готовые видео;
- `tests/` - автоматические тесты.

Каждый запуск сохраняет JSON-файлы с метаданными, движением, транскрипцией, событиями, кандидатами, выбором моментов, таймлайном и результатами QC.

## Текущее состояние

Проект находится в стадии первого рабочего MVP. Legacy stage commands сохранены для совместимости, но production-команды используют единый orchestrator.

Уже реализовано:

- получение метаданных и анализ аудио;
- анализ движения и поиск событий-кандидатов;
- распознавание речи;
- оценка и выбор лучших моментов;
- построение таймлайна и preview/render через FFmpeg;
- пакетная обработка видео и продолжение незавершённых запусков;
- отдельные тесты и сканирование через Ollama Vision;
- автоматические тесты основного пайплайна и vision-модулей.
- synthetic orchestrator E2E с mock Vision и реальным FFmpeg/QC.

Планируемые ограничения текущей версии: субтитры, сложные эффекты, полноценная редактура клипов в UI и дополнительные game profiles требуют следующих этапов.
