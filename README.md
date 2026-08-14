# Game AI Editor

Локальный AI-инструмент для поиска и монтажа лучших моментов из игровых видео. Первая поддерживаемая игра - **Arma Reforger**.

Программа анализирует видео, находит интересные моменты, оценивает их, собирает таймлайн, рендерит MP4 и запускает проверки качества.

## Как это работает

```text
video -> audio/motion/transcription -> events -> scores -> highlights -> timeline -> MP4 -> QC
```

Проект использует:

- Python 3.11+
- FFmpeg и FFprobe
- OpenCV
- faster-whisper для распознавания речи
- Pydantic и JSON-профили игр
- Ollama Vision для дополнительного анализа сцен

## Установка

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

FFmpeg и FFprobe должны быть доступны в `PATH`.

## Основные команды

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

Другие полезные команды:

```powershell
game-ai-editor prefilter input\video.mp4
game-ai-editor batch input
game-ai-editor vision-scan input\video.mp4 --prefilter
```

## Структура проекта

- `src/game_ai_editor/` - основной код;
- `config/games/` - настройки игр;
- `input/` - исходные видео;
- `work/` - промежуточные файлы анализа;
- `output/` и `finalvids/` - готовые видео;
- `tests/` - автоматические тесты.

Каждый запуск сохраняет JSON-файлы с метаданными, движением, транскрипцией, событиями, кандидатами, выбором моментов, таймлайном и результатами QC.

## Текущее состояние

Проект находится в стадии активного MVP. Это рабочая основа, но ещё не законченный продукт.

Уже реализовано:

- получение метаданных и анализ аудио;
- анализ движения и поиск событий-кандидатов;
- распознавание речи;
- оценка и выбор лучших моментов;
- построение таймлайна и preview/render через FFmpeg;
- пакетная обработка видео и продолжение незавершённых запусков;
- отдельные тесты и сканирование через Ollama Vision;
- автоматические тесты основного пайплайна и vision-модулей.

В разработке:

- точность определения игровых событий;
- качество автоматического выбора сцен;
- эффекты монтажа, субтитры и правила QC;
- поддержка игр помимо Arma Reforger.
