# Бот столовой МЕСТО ЕСТЬ для мессенджера MAX

Python 3.10+ (рекомендуется 3.12/3.14).

## Запуск

```bash
/opt/homebrew/bin/python3.14 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python run.py
```

## Настройка `.env`

1. Напишите боту в MAX команду `/id` — появится ваш user_id. Пропишите его в `STAFF_USER_ID`.
2. Добавьте бота в группу, напишите `/id` в группе — пропишите `GROUP_CHAT_ID`.
3. `GROUP_FORWARD_USER_ID` можно не заполнять: тогда сообщения из группы уйдут сотруднику.

Постоянное меню берётся из [Google Sheets](https://docs.google.com/spreadsheets/d/1Ytx243Yf3TaQ7d6zD3Gf1lRNVugmWNvjD71HbsZdAUU/edit?gid=1957930968#gid=1957930968).
