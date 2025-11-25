import os
import logging
import sqlite3
import re
import datetime
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from telegram import Update, ChatPermissions
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    ChatMemberHandler,
    filters,
)

# ------------------ ЛОГИ ------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# ------------------ ЗАГРУЗКА .env ------------------
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
GROUP_ID = int(os.getenv("GROUP_ID", "0"))
TIMEZONE = os.getenv("TIMEZONE", "Europe/Moscow")

TZ = ZoneInfo(TIMEZONE)
DB_PATH = os.path.join("data", "bot.db")

# ------------------ РОЛИ ------------------
ROLE_USER = "user"
ROLE_JUNIOR = "junior"
ROLE_ADMIN = "admin"
ROLE_OWNER = "owner"


# ------------------ БАЗА ДАННЫХ ------------------
def db_connect():
    return sqlite3.connect(DB_PATH)


def init_db():
    conn = db_connect()
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            role TEXT DEFAULT 'user',
            nickname TEXT,
            warnings INTEGER DEFAULT 0
        )
        """
    )

    conn.commit()
    conn.close()


def ensure_user_in_db(user_id: int):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    if row is None:
        cur.execute(
            "INSERT INTO users (user_id, role, nickname, warnings) VALUES (?, 'user', NULL, 0)",
            (user_id,),
        )
        conn.commit()
    conn.close()


def get_role(user_id: int) -> str:
    if user_id == OWNER_ID:
        return ROLE_OWNER
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT role FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    if row is None:
        return ROLE_USER
    return row[0]


def set_role(user_id: int, role: str):
    ensure_user_in_db(user_id)
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("UPDATE users SET role = ? WHERE user_id = ?", (role, user_id))
    conn.commit()
    conn.close()


def set_nickname(user_id: int, nickname: str):
    ensure_user_in_db(user_id)
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("UPDATE users SET nickname = ? WHERE user_id = ?", (nickname, user_id))
    conn.commit()
    conn.close()


def get_nickname(user_id: int):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT nickname FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    if row:
        return row[0]
    return None


def inc_warning(user_id: int) -> int:
    ensure_user_in_db(user_id)
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT warnings FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    warnings = row[0] if row else 0
    warnings += 1
    cur.execute(
        "UPDATE users SET warnings = ? WHERE user_id = ?", (warnings, user_id)
    )
    conn.commit()
    conn.close()
    return warnings


# ------------------ РЕЖИМ НОКАУТ ------------------

MODES = {
    "knockout": {
        "display": "Нокаут 5 на 5",
        "image": os.path.join("images", "knockout.png"),
        # бот будет писать в эти часы (00:10, 08:10, 16:10)
        "times": [(0, 10), (8, 10), (16, 10)],
    }
}

# ------------------ ФИЛЬТР ОСКОРБЛЕНИЙ ------------------

PARENT_INSULT_PATTERNS = [
    r"\bсын\s+шлюх[аиуыео]?\b",
    r"\bдочь\s+шлюх[аиуыео]?\b",
    r"\bмать\s+шлюх[аиуыео]?\b",
    r"\bмамк[аи]\s+шлюх[аиуыео]?\b",
    r"\bмамаша\s+шлюх[аиуыео]?\b",
    r"\bтво(я|ей)\s+мать\s+шлюх[аиуыео]?\b",
    r"\bу\s+тебя\s+мать\s+шлюх[аиуыео]?\b",
    r"\bтво(я|ей)\s+мамк[аи]\s+шлюх[аиуыео]?\b",
    r"\bтвоя\s+мать\b.*\bшлюх[аиуыео]?\b",
    r"\bтвою\s+мать\b.*\bшлюх[аиуыео]?\b",
    r"\bмать\b.*\bтвоя\b.*\bшлюх[аиуыео]?\b",
    r"\bмамк[аи]\b.*\bшлюх[аиуыео]?\b",
]

COMPILED_INSULTS = [
    re.compile(pat, flags=re.IGNORECASE | re.DOTALL) for pat in PARENT_INSULT_PATTERNS
]


def has_parent_insult(text: str) -> bool:
    if not text:
        return False
    normalized = re.sub(r"[^\w\s]", " ", text.lower())
    for rx in COMPILED_INSULTS:
        if rx.search(normalized):
            return True
    return False


# ------------------ ПРОВЕРКА ПРАВ ------------------


def can_do(user_id: int, minimal_role: str) -> bool:
    order = {
        ROLE_USER: 0,
        ROLE_JUNIOR: 1,
        ROLE_ADMIN: 2,
        ROLE_OWNER: 3,
    }
    user_role = get_role(user_id)
    return order.get(user_role, 0) >= order.get(minimal_role, 0)


# ------------------ ХЕНДЛЕРЫ ------------------


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start в ЛС с ботом."""
    user = update.effective_user
    if not user:
        return
    text = (
        "Привет! Я бот группы Brawl Stars.\n\n"
        "Что умею:\n"
        "• Модерирую оскорбления родителей\n"
        "• Работаю с ролями (Админ / Мл. Админ)\n"
        "• Напоминаю про Нокаут 5 на 5\n"
        "• Собираю игровые никнеймы (/setnick)\n"
    )
    await update.message.reply_text(text)


async def welcome_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Приветствие нового участника (бот НЕ трогает его права)."""
    message = update.message
    chat = message.chat
    for member in message.new_chat_members:
        if member.is_bot:
            continue

        text = (
            f"Добро пожаловать, {member.mention_html()}!\n\n"
            "Правила:\n"
            "1. Без оскорблений родителей.\n"
            "2. Без спама.\n"
            "3. Уважай остальных.\n\n"
            "Чтобы нормально общаться в чате, укажи свой ник из Brawl Stars:\n"
            "<b>/setnick ТвойНик</b>\n\n"
            "Пока ник не указан, все твои сообщения (кроме /setnick) "
            "будут удаляться ботом."
        )
        await chat.send_message(text, parse_mode="HTML")


async def setnick_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Пользователь указывает игровой ник.
    ВАЖНО: здесь мы ТОЛЬКО сохраняем ник и ставим 'должность'.
    НИКАКИХ ограничений/разрешений прав тут нет.
    """
    user = update.effective_user
    if not user:
        return

    if not context.args:
        return await update.message.reply_text(
            "Напиши так: /setnick ТвойИгровойНик"
        )

    nickname = " ".join(context.args).strip()
    if len(nickname) > 50:
        nickname = nickname[:50]

    # сохраняем ник
    set_nickname(user.id, nickname)

    # пробуем выдать "админа без прав" и поставить ник как должность
    try:
        await update.get_bot().promote_chat_member(
            chat_id=GROUP_ID,
            user_id=user.id,
            is_anonymous=False,
            can_manage_chat=False,
            can_post_messages=False,
            can_edit_messages=False,
            can_delete_messages=False,
            can_manage_video_chats=False,
            can_restrict_members=False,
            can_promote_members=False,
            can_change_info=False,
            can_invite_users=False,
            can_pin_messages=False,
            can_manage_topics=False,
        )

        await update.get_bot().set_chat_administrator_custom_title(
            chat_id=GROUP_ID,
            user_id=user.id,
            custom_title=nickname,
        )
    except Exception as e:
        logger.warning(f"Не удалось выдать фейковый админ-титул: {e}")

    await update.message.reply_text(
        f"Никнейм сохранён: {nickname}."
    )


async def check_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик текстовых сообщений в группе:
    - проверка ника
    - фильтр оскорблений родителей
    """
    message = update.message
    user = update.effective_user
    chat = update.effective_chat

    if not message or not user or not chat:
        return

    if chat.id != GROUP_ID:
        return

    # Проверка ника
    nick = get_nickname(user.id)
    if not nick:
        # удаляем все сообщения без ника
        try:
            await message.delete()
        except Exception:
            pass
        await chat.send_message(
            f"{user.mention_html()}, сначала укажи свой ник командой "
            "/setnick ТвойНик",
            parse_mode="HTML",
        )
        return

    # Фильтр оскорблений родителей
    if message.text and has_parent_insult(message.text):
        warnings = inc_warning(user.id)
        if warnings == 1:
            await chat.send_message(
                f"{user.mention_html()}, предупреждение за оскорбление родителей.\n"
                "В следующий раз будет мут на 45 минут.",
                parse_mode="HTML",
            )
        else:
            until = datetime.datetime.now(tz=datetime.timezone.utc) + datetime.timedelta(
                minutes=45
            )
            perms = ChatPermissions(can_send_messages=False)
            try:
                await context.bot.restrict_chat_member(
                    chat_id=chat.id,
                    user_id=user.id,
                    permissions=perms,
                    until_date=until,
                )
            except Exception as e:
                logger.warning(f"Не удалось выдать мут: {e}")

            await chat.send_message(
                f"{user.mention_html()} получил мут на 45 минут "
                "за повторное оскорбление родителей.",
                parse_mode="HTML",
            )


# ------------------ КОМАНДЫ АДМИНОВ ------------------


async def mute_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /mute <минут> (реплаем на сообщение пользователя)."""
    user = update.effective_user
    chat = update.effective_chat
    msg = update.message

    if not user or not chat or not msg:
        return

    if chat.id != GROUP_ID:
        return

    if not can_do(user.id, ROLE_JUNIOR):
        return await msg.reply_text("У тебя нет прав использовать /mute.")

    if not msg.reply_to_message or not msg.reply_to_message.from_user:
        return await msg.reply_text(
            "Нужно ответить командой /mute на сообщение пользователя."
        )

    target = msg.reply_to_message.from_user

    if not context.args:
        return await msg.reply_text("Напиши так: /mute <минут>. Например: /mute 30")

    try:
        minutes = int(context.args[0])
    except ValueError:
        return await msg.reply_text("Минуты должны быть числом.")

    role = get_role(user.id)
    if role == ROLE_JUNIOR and minutes > 60:
        return await msg.reply_text("Мл. Админ может мутить максимум на 60 минут.")

    if minutes <= 0:
        minutes = 365 * 24 * 60  # условно бессрочный

    until = datetime.datetime.now(tz=datetime.timezone.utc) + datetime.timedelta(
        minutes=minutes
    )
    perms = ChatPermissions(can_send_messages=False)

    try:
        await context.bot.restrict_chat_member(
            chat_id=chat.id,
            user_id=target.id,
            permissions=perms,
            until_date=until,
        )
    except Exception as e:
        logger.warning(f"Не удалось выдать мут: {e}")
        return await msg.reply_text("Не удалось выдать мут (нет прав бота?).")

    await msg.reply_text(
        f"Пользователь {target.mention_html()} получил мут на {minutes} мин.",
        parse_mode="HTML",
    )


async def ban_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /ban (только Админ/Владелец)."""
    user = update.effective_user
    chat = update.effective_chat
    msg = update.message

    if not user or not chat or not msg:
        return

    if chat.id != GROUP_ID:
        return

    if not can_do(user.id, ROLE_ADMIN):
        return await msg.reply_text("У тебя нет прав использовать /ban.")

    if not msg.reply_to_message or not msg.reply_to_message.from_user:
        return await msg.reply_text(
            "Нужно ответить командой /ban на сообщение пользователя."
        )

    target = msg.reply_to_message.from_user
    try:
        await context.bot.ban_chat_member(chat.id, target.id)
    except Exception as e:
        logger.warning(f"Не удалось заблокировать: {e}")
        return await msg.reply_text("Не удалось заблокировать (нет прав бота?).")

    await msg.reply_text(
        f"Пользователь {target.mention_html()} заблокирован.",
        parse_mode="HTML",
    )


async def add_junior_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /addjunior (Админ/Владелец делает пользователя Мл. Админом)."""
    user = update.effective_user
    chat = update.effective_chat
    msg = update.message

    if not user or not chat or not msg:
        return

    if chat.id != GROUP_ID:
        return

    if not can_do(user.id, ROLE_ADMIN):
        return await msg.reply_text("У тебя нет прав выдавать роли.")

    if not msg.reply_to_message or not msg.reply_to_message.from_user:
        return await msg.reply_text(
            "Нужно ответить командой /addjunior на сообщение пользователя."
        )

    target = msg.reply_to_message.from_user
    set_role(target.id, ROLE_JUNIOR)
    await msg.reply_text(
        f"{target.mention_html()} теперь Мл. Админ.",
        parse_mode="HTML",
    )


async def add_admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /addadmin (только владелец бота)."""
    user = update.effective_user
    chat = update.effective_chat
    msg = update.message

    if not user or not chat or not msg:
        return

    if chat.id != GROUP_ID:
        return

    if user.id != OWNER_ID:
        return await msg.reply_text("Только владелец бота может выдавать роль Админа.")

    if not msg.reply_to_message or not msg.reply_to_message.from_user:
        return await msg.reply_text(
            "Нужно ответить командой /addadmin на сообщение пользователя."
        )

    target = msg.reply_to_message.from_user
    set_role(target.id, ROLE_ADMIN)
    await msg.reply_text(
        f"{target.mention_html()} теперь Админ.",
        parse_mode="HTML",
    )


async def info_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /info – показывает ник и роль (по реплаю)."""
    msg = update.message
    if not msg or not msg.reply_to_message or not msg.reply_to_message.from_user:
        return await msg.reply_text(
            "Ответь командой /info на сообщение пользователя."
        )

    target = msg.reply_to_message.from_user
    nick = get_nickname(target.id) or "не указан"
    role = get_role(target.id)
    await msg.reply_text(
        f"Пользователь: {target.mention_html()}\n"
        f"Ник в игре: <b>{nick}</b>\n"
        f"Роль: <b>{role}</b>",
        parse_mode="HTML",
    )


# ------------------ JOB QUEUE: НОКАУТ ------------------


async def mode_announcement(context: ContextTypes.DEFAULT_TYPE):
    """Простое объявление: пишет текст и кидает картинку."""
    mode_info = MODES["knockout"]
    caption = "Нокаут 5 на 5 скоро!"
    image_path = mode_info["image"]

    try:
        with open(image_path, "rb") as f:
            await context.bot.send_photo(
                chat_id=GROUP_ID,
                photo=f,
                caption=caption,
            )
    except FileNotFoundError:
        await context.bot.send_message(chat_id=GROUP_ID, text=caption)


def setup_jobs(app):
    """Запускаем задания только для режима Нокаут 5 на 5."""
    times = MODES["knockout"]["times"]
    for hour, minute in times:
        t = datetime.time(hour=hour, minute=minute, tzinfo=TZ)
        app.job_queue.run_daily(
            mode_announcement,
            time=t,
            name=f"knockout_{hour}_{minute}",
        )


# ------------------ СЛУЖЕБНЫЙ ХЕНДЛЕР ------------------


async def my_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"my_chat_member update: {update}")


# ------------------ MAIN ------------------


def main():
    os.makedirs("data", exist_ok=True)
    init_db()

    application = ApplicationBuilder().token(BOT_TOKEN).build()

    # команды
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("setnick", setnick_cmd))
    application.add_handler(CommandHandler("mute", mute_cmd))
    application.add_handler(CommandHandler("ban", ban_cmd))
    application.add_handler(CommandHandler("addjunior", add_junior_cmd))
    application.add_handler(CommandHandler("addadmin", add_admin_cmd))
    application.add_handler(CommandHandler("info", info_cmd))

    # новые участники
    application.add_handler(
        MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_new_member)
    )

    # текст в группе (модерация)
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, check_message)
    )

    application.add_handler(ChatMemberHandler(my_chat_member))

    # джобы по времени
    setup_jobs(application)

    application.run_polling()


if __name__ == "__main__":
    main()
