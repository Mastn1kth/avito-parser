# Local maintenance checks

- Tests must redirect all data/configuration paths to temporary directories,
  including `bot_jobs.WATCH_TARGETS`; never delete live watch preferences.
- Watch alert delivery must persist the message before saving its seen marker.
  Exercise restart and offline delivery with a fake notifier; do not send test
  messages to the configured live chat without user authorization.
- Price comparison tests must separate the bounded watch feed from the
  unbounded reference feed. Reference IDs must never enter seen markers.
