import logging
from telegram import (
    Update, 
    ForceReply, 
    ChatPermissions, 
    InlineKeyboardButton, 
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove
)
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
    CallbackQueryHandler,
    ConversationHandler,
    CallbackContext
)
from datetime import datetime, timedelta
from collections import defaultdict, OrderedDict
import pytz
from typing import Dict, List, Tuple, Optional, Set, Any
import random
import json
import os
import sqlite3
from enum import Enum, auto
import asyncio
import re

# ==============================================
# НАСТРОЙКИ ЛОГИРОВАНИЯ И КОНФИГУРАЦИИ
# ==============================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", 
    level=logging.INFO,
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class Config:
    TOKEN = "YOUR_BOT_TOKEN"
    ADMIN_IDS = [123456789]  # Список ID администраторов
    DB_FILE = "user_stats.db"
    BACKUP_INTERVAL = 3600  # Интервал резервного копирования в секундах
    ACHIEVEMENTS_FILE = "achievements.json"
    REPORT_CHANNEL_ID = -1001234567890  # ID канала для репортов
    
    # Настройки антиспама
    SPAM_LIMITS = {
        'max_messages': 5,
        'time_window': 10,
        'warn_limit': 3,
        'mute_duration': 300,
        'max_message_length': 1000
    }
    
    # Настройки приветствия
    GREETINGS = {
        'enabled': True,
        'message': "👋 Добро пожаловать, {mention}! Прочитай правила в закреплённом сообщении.",
        'goodbye_message': "😢 Пользователь {mention} покинул чат.",
        'rules_message': "📜 Правила чата:\n1. Уважайте друг друга\n2. Не спамьте\n3. Не флудите"
    }
    
    # Настройки репортов
    REPORTS = {
        'enabled': True,
        'cooldown': 300,  # 5 минут между репортами от одного пользователя
        'types': [
            "Спам", "Оскорбления", "Неуместный контент", 
            "Мошенничество", "Другое"
        ]
    }

# ==============================================
# ПЕРЕЧИСЛЕНИЯ И КЛАССЫ ДАННЫХ
# ==============================================

class UserRole(Enum):
    MEMBER = auto()
    MODERATOR = auto()
    ADMIN = auto()
    CREATOR = auto()

class MediaType(Enum):
    PHOTO = auto()
    VIDEO = auto()
    VOICE = auto()
    STICKER = auto()
    DOCUMENT = auto()
    AUDIO = auto()
    ANIMATION = auto()
    POLL = auto()
    LOCATION = auto()
    CONTACT = auto()

class ReactionType(Enum):
    LIKE = auto()
    DISLIKE = auto()
    LOVE = auto()
    LAUGH = auto()
    WOW = auto()
    SAD = auto()
    ANGRY = auto()

class AchievementLevel(Enum):
    BRONZE = auto()
    SILVER = auto()
    GOLD = auto()
    PLATINUM = auto()
    DIAMOND = auto()

class ReportStatus(Enum):
    PENDING = auto()
    REVIEWED = auto()
    REJECTED = auto()
    PROCESSED = auto()

# ==============================================
# МОДЕЛИ ДАННЫХ
# ==============================================

class Achievement:
    def __init__(self, name: str, description: str, level: AchievementLevel, icon: str):
        self.name = name
        self.description = description
        self.level = level
        self.icon = icon

class UserActivity:
    def __init__(self):
        self.message_count = 0
        self.command_count = 0
        self.media_count = 0
        self.reaction_count = 0
        self.mention_count = 0
        self.poll_participation = 0
        self.violation_count = 0
        self.last_activity = datetime.now(pytz.utc)
        
    def update_activity(self):
        self.last_activity = datetime.now(pytz.utc)

class UserStats:
    def __init__(self, user_id: int):
        self.user_id = user_id
        self.join_date = datetime.now(pytz.utc)
        self.total_messages = 0
        self.total_chars = 0
        self.media_stats = {media_type: 0 for media_type in MediaType}
        self.reaction_stats = {reaction: 0 for reaction in ReactionType}
        self.mentions = 0
        self.warnings = 0
        self.bans = 0
        self.kicks = 0
        self.mutes = 0
        self.role = UserRole.MEMBER
        self.achievements = set()
        self.activity_by_hour = [0] * 24
        self.activity_by_day = [0] * 7
        self.daily_stats = OrderedDict()
        self.last_seen = datetime.now(pytz.utc)
        self.is_online = False
        self.rank_score = 0
        self.last_report_time = None
        
    def add_message(self, text: str = None):
        self.total_messages += 1
        if text:
            self.total_chars += len(text)
        self._update_activity()
        
    def add_media(self, media_type: MediaType):
        self.media_stats[media_type] += 1
        self._update_activity()
        
    def add_reaction(self, reaction_type: ReactionType):
        self.reaction_stats[reaction_type] += 1
        self._update_activity()
        
    def add_mention(self):
        self.mentions += 1
        self._update_activity()
        
    def add_warning(self):
        self.warnings += 1
        self._update_activity()
        
    def add_ban(self):
        self.bans += 1
        self._update_activity()
        
    def add_kick(self):
        self.kicks += 1
        self._update_activity()
        
    def add_mute(self):
        self.mutes += 1
        self._update_activity()
        
    def update_role(self, role: UserRole):
        self.role = role
        self._update_activity()
        
    def add_achievement(self, achievement: Achievement):
        self.achievements.add(achievement)
        self._update_activity()
        
    def can_report(self) -> bool:
        if self.last_report_time is None:
            return True
        return (datetime.now(pytz.utc) - self.last_report_time).total_seconds() >= Config.REPORTS['cooldown']
        
    def report_used(self):
        self.last_report_time = datetime.now(pytz.utc)
        self._update_activity()
        
    def _update_activity(self):
        now = datetime.now(pytz.utc)
        self.last_seen = now
        self.is_online = True
        
        hour = now.hour
        self.activity_by_hour[hour] += 1
        
        weekday = now.weekday()
        self.activity_by_day[weekday] += 1
        
        today = now.date()
        if today not in self.daily_stats:
            self.daily_stats[today] = UserActivity()
            if len(self.daily_stats) > 30:
                self.daily_stats.popitem(last=False)
        
        self.daily_stats[today].message_count += 1
        self.daily_stats[today].update_activity()
        self._update_rank_score()
    
    def _update_rank_score(self):
        base_score = self.total_messages * 1
        media_score = sum(self.media_stats.values()) * 2
        positive_score = (self.reaction_stats[ReactionType.LIKE] + 
                         self.reaction_stats[ReactionType.LOVE]) * 3
        negative_score = (self.warnings + self.bans + self.kicks) * -10
        
        self.rank_score = base_score + media_score + positive_score + negative_score
    
    def get_stats_summary(self) -> Dict:
        return {
            "user_id": self.user_id,
            "join_date": self.join_date.strftime("%Y-%m-%d %H:%M:%S"),
            "last_seen": self.last_seen.strftime("%Y-%m-%d %H:%M:%S"),
            "is_online": self.is_online,
            "total_messages": self.total_messages,
            "avg_message_length": self.total_chars / self.total_messages if self.total_messages else 0,
            "media_count": {media.name: count for media, count in self.media_stats.items()},
            "reactions": {reaction.name: count for reaction, count in self.reaction_stats.items()},
            "mentions": self.mentions,
            "warnings": self.warnings,
            "bans": self.bans,
            "kicks": self.kicks,
            "mutes": self.mutes,
            "role": self.role.name,
            "achievements": [ach.name for ach in self.achievements],
            "rank_score": self.rank_score,
            "most_active_hour": max(range(24), key=lambda h: self.activity_by_hour[h]),
            "most_active_day": max(range(7), key=lambda d: self.activity_by_day[d]),
            "days_in_group": (datetime.now(pytz.utc) - self.join_date).days
        }

class Report:
    def __init__(self, reporter_id: int, reported_id: int, reason: str, message_id: int = None):
        self.reporter_id = reporter_id
        self.reported_id = reported_id
        self.reason = reason
        self.message_id = message_id
        self.status = ReportStatus.PENDING
        self.created_at = datetime.now(pytz.utc)
        self.processed_at = None
        self.processed_by = None
        
    def process(self, moderator_id: int, status: ReportStatus):
        self.status = status
        self.processed_by = moderator_id
        self.processed_at = datetime.now(pytz.utc)
        
    def to_dict(self) -> Dict:
        return {
            "reporter_id": self.reporter_id,
            "reported_id": self.reported_id,
            "reason": self.reason,
            "message_id": self.message_id,
            "status": self.status.name,
            "created_at": self.created_at.isoformat(),
            "processed_at": self.processed_at.isoformat() if self.processed_at else None,
            "processed_by": self.processed_by
        }

# ==============================================
# ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ И КЭШ
# ==============================================

user_stats_cache: Dict[int, UserStats] = {}
admin_ids_cache: Set[int] = set()
user_warnings = defaultdict(int)
user_last_message_time = {}
user_message_count = defaultdict(int)
reports: Dict[int, Report] = {}  # ID сообщения с репортом -> Report
pending_reports: Dict[int, Report] = {}  # ID пользователя -> список репортов
db_conn = None
achievements_list: List[Achievement] = []

# Состояния для ConversationHandler
REPORT_REASON, REPORT_CONFIRM = range(2)

# ==============================================
# ИНИЦИАЛИЗАЦИЯ И УТИЛИТЫ
# ==============================================

def init_database():
    global db_conn
    db_conn = sqlite3.connect(Config.DB_FILE)
    cursor = db_conn.cursor()
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS user_stats (
        user_id INTEGER PRIMARY KEY,
        join_date TEXT NOT NULL,
        last_seen TEXT NOT NULL,
        total_messages INTEGER DEFAULT 0,
        total_chars INTEGER DEFAULT 0,
        warnings INTEGER DEFAULT 0,
        bans INTEGER DEFAULT 0,
        kicks INTEGER DEFAULT 0,
        mutes INTEGER DEFAULT 0,
        role TEXT DEFAULT 'MEMBER',
        rank_score INTEGER DEFAULT 0,
        last_report_time TEXT
    )
    """)
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS user_media_stats (
        user_id INTEGER,
        media_type TEXT,
        count INTEGER DEFAULT 0,
        PRIMARY KEY (user_id, media_type),
        FOREIGN KEY (user_id) REFERENCES user_stats (user_id)
    )
    """)
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS user_reaction_stats (
        user_id INTEGER,
        reaction_type TEXT,
        count INTEGER DEFAULT 0,
        PRIMARY KEY (user_id, reaction_type),
        FOREIGN KEY (user_id) REFERENCES user_stats (user_id)
    )
    """)
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS user_achievements (
        user_id INTEGER,
        achievement_name TEXT,
        PRIMARY KEY (user_id, achievement_name),
        FOREIGN KEY (user_id) REFERENCES user_stats (user_id)
    )
    """)
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS reports (
        report_id INTEGER PRIMARY KEY AUTOINCREMENT,
        reporter_id INTEGER NOT NULL,
        reported_id INTEGER NOT NULL,
        reason TEXT NOT NULL,
        message_id INTEGER,
        status TEXT NOT NULL,
        created_at TEXT NOT NULL,
        processed_at TEXT,
        processed_by INTEGER,
        FOREIGN KEY (reporter_id) REFERENCES user_stats (user_id),
        FOREIGN KEY (reported_id) REFERENCES user_stats (user_id)
    )
    """)
    
    db_conn.commit()

def load_achievements():
    global achievements_list
    try:
        with open(Config.ACHIEVEMENTS_FILE, 'r', encoding='utf-8') as f:
            achievements_data = json.load(f)
            
        for ach_data in achievements_data:
            achievement = Achievement(
                name=ach_data['name'],
                description=ach_data['description'],
                level=AchievementLevel[ach_data['level']],
                icon=ach_data['icon']
            )
            achievements_list.append(achievement)
            
        logger.info(f"Loaded {len(achievements_list)} achievements")
    except Exception as e:
        logger.error(f"Failed to load achievements: {e}")
        achievements_list = [
            Achievement("Новичок", "Отправил первое сообщение", AchievementLevel.BRONZE, "👶"),
            Achievement("Активный", "100 сообщений", AchievementLevel.SILVER, "💬"),
            Achievement("Болтун", "500 сообщений", AchievementLevel.GOLD, "🗣"),
            Achievement("Писатель", "1000 сообщений", AchievementLevel.PLATINUM, "✍️"),
            Achievement("Ветеран", "30 дней в группе", AchievementLevel.SILVER, "🕰"),
            Achievement("Медиамагнат", "50 медиафайлов", AchievementLevel.GOLD, "📷"),
            Achievement("Примерный", "100 сообщений без нарушений", AchievementLevel.SILVER, "👍"),
            Achievement("Популярный", "50 упоминаний", AchievementLevel.GOLD, "🌟"),
            Achievement("Лидер", "Топ-1 в рейтинге", AchievementLevel.DIAMOND, "🏆"),
            Achievement("Страж", "Отправил 10 репортов", AchievementLevel.SILVER, "🛡️")
        ]

async def backup_stats():
    while True:
        await asyncio.sleep(Config.BACKUP_INTERVAL)
        try:
            save_stats_to_db()
            logger.info("Stats backup completed successfully")
        except Exception as e:
            logger.error(f"Backup failed: {e}")

def save_stats_to_db():
    if not db_conn:
        return
        
    cursor = db_conn.cursor()
    
    for user_id, stats in user_stats_cache.items():
        cursor.execute("""
        INSERT OR REPLACE INTO user_stats 
        (user_id, join_date, last_seen, total_messages, total_chars, warnings, bans, kicks, mutes, role, rank_score, last_report_time)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            user_id,
            stats.join_date.isoformat(),
            stats.last_seen.isoformat(),
            stats.total_messages,
            stats.total_chars,
            stats.warnings,
            stats.bans,
            stats.kicks,
            stats.mutes,
            stats.role.name,
            stats.rank_score,
            stats.last_report_time.isoformat() if stats.last_report_time else None
        ))
        
        for media_type, count in stats.media_stats.items():
            cursor.execute("""
            INSERT OR REPLACE INTO user_media_stats 
            (user_id, media_type, count)
            VALUES (?, ?, ?)
            """, (user_id, media_type.name, count))
            
        for reaction_type, count in stats.reaction_stats.items():
            cursor.execute("""
            INSERT OR REPLACE INTO user_reaction_stats 
            (user_id, reaction_type, count)
            VALUES (?, ?, ?)
            """, (user_id, reaction_type.name, count))
            
        for achievement in stats.achievements:
            cursor.execute("""
            INSERT OR IGNORE INTO user_achievements 
            (user_id, achievement_name)
            VALUES (?, ?)
            """, (user_id, achievement.name))
    
    # Сохраняем репорты
    for report in reports.values():
        cursor.execute("""
        INSERT OR REPLACE INTO reports 
        (reporter_id, reported_id, reason, message_id, status, created_at, processed_at, processed_by)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            report.reporter_id,
            report.reported_id,
            report.reason,
            report.message_id,
            report.status.name,
            report.created_at.isoformat(),
            report.processed_at.isoformat() if report.processed_at else None,
            report.processed_by
        ))
    
    db_conn.commit()

def load_stats_from_db():
    if not db_conn:
        return
        
    cursor = db_conn.cursor()
    
    cursor.execute("SELECT * FROM user_stats")
    for row in cursor.fetchall():
        user_id = row[0]
        stats = UserStats(user_id)
        
        stats.join_date = datetime.fromisoformat(row[1])
        stats.last_seen = datetime.fromisoformat(row[2])
        stats.total_messages = row[3]
        stats.total_chars = row[4]
        stats.warnings = row[5]
        stats.bans = row[6]
        stats.kicks = row[7]
        stats.mutes = row[8]
        stats.role = UserRole[row[9]]
        stats.rank_score = row[10]
        stats.last_report_time = datetime.fromisoformat(row[11]) if row[11] else None
        
        user_stats_cache[user_id] = stats
    
    cursor.execute("SELECT * FROM user_media_stats")
    for row in cursor.fetchall():
        user_id = row[0]
        if user_id in user_stats_cache:
            media_type = MediaType[row[1]]
            count = row[2]
            user_stats_cache[user_id].media_stats[media_type] = count
    
    cursor.execute("SELECT * FROM user_reaction_stats")
    for row in cursor.fetchall():
        user_id = row[0]
        if user_id in user_stats_cache:
            reaction_type = ReactionType[row[1]]
            count = row[2]
            user_stats_cache[user_id].reaction_stats[reaction_type] = count
    
    cursor.execute("SELECT * FROM user_achievements")
    for row in cursor.fetchall():
        user_id = row[0]
        if user_id in user_stats_cache:
            achievement_name = row[1]
            achievement = next((a for a in achievements_list if a.name == achievement_name), None)
            if achievement:
                user_stats_cache[user_id].achievements.add(achievement)
    
    # Загружаем репорты
    cursor.execute("SELECT * FROM reports")
    for row in cursor.fetchall():
        report = Report(
            reporter_id=row[1],
            reported_id=row[2],
            reason=row[3],
            message_id=row[4]
        )
        report.status = ReportStatus[row[5]]
        report.created_at = datetime.fromisoformat(row[6])
        report.processed_at = datetime.fromisoformat(row[7]) if row[7] else None
        report.processed_by = row[8]
        
        reports[row[0]] = report
    
    logger.info(f"Loaded stats for {len(user_stats_cache)} users and {len(reports)} reports from database")

# ==============================================
# ОСНОВНЫЕ ФУНКЦИИ БОТА
# ==============================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    chat = update.effective_chat
    
    if chat.type == "private":
        await update.message.reply_text(
            "Привет! Я бот для сбора статистики и модерации чатов. "
            "Добавь меня в группу и дай права администратора для полного функционала."
        )
    else:
        await update.message.reply_text(
            f"Привет, {user.mention_html()}! Я бот для сбора статистики и модерации. "
            "Используй /help для списка команд.",
            parse_mode="HTML"
        )
        
        stats = await get_user_stats(update, context, user.id)
        if stats.total_messages == 0:
            await check_achievements(stats, "first_message")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    help_text = """
📚 <b>Доступные команды:</b>

<b>Основные:</b>
/start - Начать работу с ботом
/help - Показать это сообщение
/stats - Ваша статистика
/top - Топ активных пользователей
/me - Информация о вас
/achievements - Ваши достижения
/rules - Правила чата
/report - Пожаловаться на пользователя

<b>Модерация (для админов):</b>
/ban - Забанить пользователя
/unban - Разбанить
/mute - Заглушить
/unmute - Разглушить
/kick - Кикнуть
/warn - Выдать предупреждение
/pin - Закрепить сообщение
/admin - Список администраторов
/settings - Настройки
/pingall - Упомянуть всех пользователей
/reports - Список репортов

<b>Триггеры команд:</b>
"мойстат" - /stats
"топ" - /top
"помощь" - /help
"админы" - /admin
"варн" - /warn
"бан" - /ban
"кик" - /kick
"мут" - /mute
"репорт" - /report
"""
    await update.message.reply_text(help_text, parse_mode="HTML")

async def get_user_stats(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int = None) -> Optional[UserStats]:
    if not user_id:
        if not update.effective_user:
            return None
        user_id = update.effective_user.id
    
    if user_id not in user_stats_cache:
        user_stats_cache[user_id] = UserStats(user_id)
    
    return user_stats_cache[user_id]

# ... (остальные функции из предыдущего кода, такие как user_statistics, top_users, user_profile и т.д.)

# ==============================================
# СИСТЕМА ПРИВЕТСТВИЙ
# ==============================================

async def greet_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Приветствие новых участников"""
    if not Config.GREETINGS['enabled']:
        return
        
    for member in update.message.new_chat_members:
        if member.id == context.bot.id:  # Если добавили самого бота
            await update.message.reply_text(
                "Спасибо за добавление! Дайте мне права администратора для полноценной работы."
            )
            continue
            
        stats = await get_user_stats(update, context, member.id)
        greeting = Config.GREETINGS['message'].format(
            mention=member.mention_html(),
            username=member.username or member.full_name
        )
        
        # Добавляем кнопку с правилами
        keyboard = [
            [InlineKeyboardButton("📜 Правила", callback_data="show_rules")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            greeting,
            parse_mode="HTML",
            reply_markup=reply_markup
        )
        
        # Проверяем достижения
        if stats.total_messages == 0:
            await check_achievements(stats, "first_message")

async def goodbye_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Сообщение при выходе участника"""
    if not Config.GREETINGS['enabled']:
        return
        
    left_member = update.message.left_chat_member
    goodbye_msg = Config.GREETINGS['goodbye_message'].format(
        mention=left_member.mention_html(),
        username=left_member.username or left_member.full_name
    )
    
    await update.message.reply_text(goodbye_msg, parse_mode="HTML")

async def show_rules_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик кнопки с правилами"""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        text=f"{query.message.text}\n\n{Config.GREETINGS['rules_message']}",
        parse_mode="HTML"
    )

async def rules_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Команда /rules для показа правил"""
    await update.message.reply_text(
        Config.GREETINGS['rules_message'],
        parse_mode="HTML"
    )

# ==============================================
# СИСТЕМА РЕПОРТОВ
# ==============================================

async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Начало процесса отправки репорта"""
    if not Config.REPORTS['enabled']:
        await update.message.reply_text("Система репортов отключена.")
        return
    
    # Проверяем, есть ли reply
    if not update.message.reply_to_message:
        await update.message.reply_text(
            "Используйте эту команду в ответ на сообщение пользователя, "
            "на которого хотите пожаловаться."
        )
        return
    
    reported_user = update.message.reply_to_message.from_user
    reporter_user = update.message.from_user
    
    # Нельзя жаловаться на себя
    if reported_user.id == reporter_user.id:
        await update.message.reply_text("Вы не можете пожаловаться на себя!")
        return
    
    # Проверяем cooldown
    stats = await get_user_stats(update, context, reporter_user.id)
    if not stats.can_report():
        time_left = Config.REPORTS['cooldown'] - (datetime.now(pytz.utc) - stats.last_report_time).total_seconds()
        await update.message.reply_text(
            f"Вы можете отправлять репорты раз в {Config.REPORTS['cooldown']//60} минут. "
            f"Попробуйте через {int(time_left//60)} минут {int(time_left%60)} секунд."
        )
        return
    
    # Сохраняем информацию о репорте в контексте
    context.user_data['report'] = {
        'reported_id': reported_user.id,
        'reported_name': reported_user.username or reported_user.full_name,
        'message_id': update.message.reply_to_message.message_id
    }
    
    # Создаем клавиатуру с типами репортов
    keyboard = [
        [InlineKeyboardButton(reason, callback_data=f"report_{i}")]
        for i, reason in enumerate(Config.REPORTS['types'])
    ]
    keyboard.append([InlineKeyboardButton("Отмена", callback_data="report_cancel")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "Выберите причину жалобы:",
        reply_markup=reply_markup
    )
    
    return REPORT_REASON

async def report_reason_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик выбора причины репорта"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "report_cancel":
        await query.edit_message_text("Отправка репорта отменена.")
        return ConversationHandler.END
    
    # Получаем тип репорта
    report_type = int(query.data.split("_")[1])
    reason = Config.REPORTS['types'][report_type]
    
    # Сохраняем причину
    context.user_data['report']['reason'] = reason
    
    # Запрашиваем подтверждение
    reported_name = context.user_data['report']['reported_name']
    
    await query.edit_message_text(
        f"Вы хотите пожаловаться на пользователя {reported_name} "
        f"по причине: {reason}.\n\n"
        f"Подтвердите отправку жалобы:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Подтвердить", callback_data="report_confirm")],
            [InlineKeyboardButton("❌ Отменить", callback_data="report_cancel")]
        ])
    )
    
    return REPORT_CONFIRM

async def report_confirm_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик подтверждения репорта"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "report_cancel":
        await query.edit_message_text("Отправка репорта отменена.")
        return ConversationHandler.END
    
    # Получаем данные из контекста
    report_data = context.user_data['report']
    reporter_id = query.from_user.id
    reported_id = report_data['reported_id']
    reason = report_data['reason']
    message_id = report_data['message_id']
    
    # Создаем репорт
    report = Report(
        reporter_id=reporter_id,
        reported_id=reported_id,
        reason=reason,
        message_id=message_id
    )
    
    # Отправляем репорт админам
    try:
        # Формируем текст репорта
        reporter = await context.bot.get_chat(reporter_id)
        reported = await context.bot.get_chat(reported_id)
        
        report_text = (
            f"⚠️ <b>Новый репорт</b> ⚠️\n\n"
            f"👤 <b>Жалоба от:</b> {reporter.mention_html()}\n"
            f"🆔 ID: <code>{reporter_id}</code>\n\n"
            f"👥 <b>На пользователя:</b> {reported.mention_html()}\n"
            f"🆔 ID: <code>{reported_id}</code>\n\n"
            f"📌 <b>Причина:</b> {reason}\n"
            f"🕒 <b>Время:</b> {datetime.now(pytz.utc).strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            f"Сообщение: https://t.me/c/{update.effective_chat.id}/{message_id}"
        )
        
        # Кнопки для действий
        keyboard = [
            [
                InlineKeyboardButton("⚠️ Выдать предупреждение", callback_data=f"warn_{reported_id}_{message_id}"),
                InlineKeyboardButton("🔇 Замутить", callback_data=f"mute_{reported_id}_{message_id}")
            ],
            [
                InlineKeyboardButton("⛔ Забанить", callback_data=f"ban_{reported_id}_{message_id}"),
                InlineKeyboardButton("❌ Отклонить репорт", callback_data=f"reject_{message_id}")
            ]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Отправляем в канал репортов
        report_msg = await context.bot.send_message(
            chat_id=Config.REPORT_CHANNEL_ID,
            text=report_text,
            parse_mode="HTML",
            reply_markup=reply_markup
        )
        
        # Сохраняем репорт
        report.message_id = report_msg.message_id
        reports[report_msg.message_id] = report
        
        # Обновляем статистику пользователя
        stats = await get_user_stats(update, context, reporter_id)
        stats.report_used()
        
        # Проверяем достижения
        report_count = sum(1 for r in reports.values() if r.reporter_id == reporter_id)
        if report_count >= 10:
            achievement = next((a for a in achievements_list if a.name == "Страж"), None)
            if achievement and achievement not in stats.achievements:
                stats.add_achievement(achievement)
                await query.edit_message_text(
                    f"✅ Ваш репорт отправлен администраторам!\n\n"
                    f"🏆 Вы получили достижение: {achievement.icon} {achievement.name} - {achievement.description}"
                )
                return ConversationHandler.END
        
        await query.edit_message_text("✅ Ваш репорт отправлен администраторам!")
        
    except Exception as e:
        logger.error(f"Ошибка при отправке репорта: {e}")
        await query.edit_message_text("Произошла ошибка при отправке репорта. Попробуйте позже.")
    
    return ConversationHandler.END

async def report_cancel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик отмены репорта"""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text("Отправка репорта отменена.")
    return ConversationHandler.END

async def report_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик кнопок действий с репортами"""
    query = update.callback_query
    await query.answer()
    
    data = query.data.split("_")
    action = data[0]
    reported_id = int(data[1])
    message_id = int(data[2])
    
    # Находим репорт
    report = reports.get(message_id)
    if not report:
        await query.answer("Репорт не найден!")
        return
    
    # Проверяем права пользователя
    if query.from_user.id not in Config.ADMIN_IDS and query.from_user.id not in admin_ids_cache:
        await query.answer("У вас нет прав для этого действия!")
        return
    
    # Обрабатываем действие
    if action == "warn":
        # Выдаем предупреждение
        stats = await get_user_stats(update, context, reported_id)
        stats.add_warning()
        
        # Уведомляем пользователя
        try:
            await context.bot.send_message(
                chat_id=reported_id,
                text=f"⚠️ Вы получили предупреждение от администратора.\nПричина: {report.reason}"
            )
        except Exception as e:
            logger.error(f"Не удалось отправить уведомление пользователю {reported_id}: {e}")
        
        report.process(query.from_user.id, ReportStatus.PROCESSED)
        await query.edit_message_text(
            f"{query.message.text}\n\n"
            f"✅ Администратор {query.from_user.mention_html()} выдал предупреждение.",
            parse_mode="HTML"
        )
        
    elif action == "mute":
        # Мьютим пользователя
        try:
            until_date = datetime.now(pytz.utc) + timedelta(minutes=30)
            await context.bot.restrict_chat_member(
                chat_id=query.message.chat_id,
                user_id=reported_id,
                permissions=ChatPermissions(
                    can_send_messages=False,
                    can_send_media_messages=False,
                    can_send_polls=False,
                    can_send_other_messages=False,
                    can_add_web_page_previews=False,
                    can_change_info=False,
                    can_invite_users=False,
                    can_pin_messages=False
                ),
                until_date=until_date
            )
            
            stats = await get_user_stats(update, context, reported_id)
            stats.add_mute()
            
            # Уведомляем пользователя
            try:
                await context.bot.send_message(
                    chat_id=reported_id,
                    text=f"🔇 Вы были замучены на 30 минут администратором.\nПричина: {report.reason}"
                )
            except Exception as e:
                logger.error(f"Не удалось отправить уведомление пользователю {reported_id}: {e}")
            
            report.process(query.from_user.id, ReportStatus.PROCESSED)
            await query.edit_message_text(
                f"{query.message.text}\n\n"
                f"✅ Администратор {query.from_user.mention_html()} замутил пользователя на 30 минут.",
                parse_mode="HTML"
            )
            
        except Exception as e:
            logger.error(f"Ошибка при муте пользователя: {e}")
            await query.answer("Не удалось замутить пользователя!")
            
    elif action == "ban":
        # Баним пользователя
        try:
            await context.bot.ban_chat_member(
                chat_id=query.message.chat_id,
                user_id=reported_id
            )
            
            stats = await get_user_stats(update, context, reported_id)
            stats.add_ban()
            
            report.process(query.from_user.id, ReportStatus.PROCESSED)
            await query.edit_message_text(
                f"{query.message.text}\n\n"
                f"✅ Администратор {query.from_user.mention_html()} забанил пользователя.",
                parse_mode="HTML"
            )
            
        except Exception as e:
            logger.error(f"Ошибка при бане пользователя: {e}")
            await query.answer("Не удалось забанить пользователя!")
            
    elif action == "reject":
        # Отклоняем репорт
        report.process(query.from_user.id, ReportStatus.REJECTED)
        await query.edit_message_text(
            f"{query.message.text}\n\n"
            f"❌ Администратор {query.from_user.mention_html()} отклонил репорт.",
            parse_mode="HTML"
        )

async def reports_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Команда для просмотра репортов (/reports)"""
    if update.effective_user.id not in Config.ADMIN_IDS and update.effective_user.id not in admin_ids_cache:
        await update.message.reply_text("У вас нет прав для просмотра репортов.")
        return
    
    pending_count = sum(1 for r in reports.values() if r.status == ReportStatus.PENDING)
    processed_count = sum(1 for r in reports.values() if r.status == ReportStatus.PROCESSED)
    rejected_count = sum(1 for r in reports.values() if r.status == ReportStatus.REJECTED)
    
    await update.message.reply_text(
        f"📊 <b>Статистика репортов:</b>\n\n"
        f"⏳ Ожидают рассмотрения: {pending_count}\n"
        f"✅ Обработано: {processed_count}\n"
        f"❌ Отклонено: {rejected_count}\n"
        f"Всего: {len(reports)}",
        parse_mode="HTML"
    )

# ==============================================
# СИСТЕМА ПИНГА ПОЛЬЗОВАТЕЛЕЙ
# ==============================================

async def ping_all_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Команда для упоминания всех пользователей (/pingall)"""
    if update.effective_user.id not in Config.ADMIN_IDS and update.effective_user.id not in admin_ids_cache:
        await update.message.reply_text("У вас нет прав для использования этой команды.")
        return
    
    chat_id = update.effective_chat.id
    
    try:
        # Получаем список участников чата
        members = []
        async for member in context.bot.get_chat_members(chat_id):
            if not member.user.is_bot and member.user.username:
                members.append(f"@{member.user.username}")
        
        if not members:
            await update.message.reply_text("Не найдено пользователей для упоминания.")
            return
        
        # Разбиваем на части по 50 пользователей (ограничение Telegram)
        chunks = [members[i:i + 50] for i in range(0, len(members), 50)]
        
        # Отправляем сообщения с упоминаниями
        for chunk in chunks:
            await context.bot.send_message(
                chat_id=chat_id,
                text=" ".join(chunk),
                reply_to_message_id=update.message.message_id
            )
            
    except Exception as e:
        logger.error(f"Ошибка при выполнении pingall: {e}")
        await update.message.reply_text("Произошла ошибка при упоминании пользователей.")

# ==============================================
# УЛУЧШЕННАЯ СИСТЕМА МОДЕРАЦИИ
# ==============================================

async def auto_moderate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Автоматическая модерация сообщений"""
    message = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    
    if not message or not user or chat.type == "private":
        return
    
    # Получаем статистику пользователя
    stats = await get_user_stats(update, context, user.id)
    
    # Проверка на спам
    await check_spam(update, context)
    
    # Проверка на запрещенные слова
    await check_bad_words(update, context)
    
    # Проверка на длинные сообщения
    if message.text and len(message.text) > Config.SPAM_LIMITS['max_message_length']:
        await message.delete()
        warn_msg = await message.reply_text(
            f"{user.mention_html()}, ваше сообщение слишком длинное. "
            f"Максимальная длина: {Config.SPAM_LIMITS['max_message_length']} символов.",
            parse_mode="HTML"
        )
        stats.add_warning()
        
        # Удаляем предупреждение через 10 секунд
        await asyncio.sleep(10)
        try:
            await warn_msg.delete()
        except Exception as e:
            logger.error(f"Не удалось удалить предупреждение: {e}")

async def check_spam(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Проверка на спам"""
    user = update.effective_user
    message = update.effective_message
    
    if not user or not message:
        return
    
    user_id = user.id
    now = datetime.now(pytz.utc)
    
    # Инициализируем данные пользователя, если их нет
    if user_id not in user_last_message_time:
        user_last_message_time[user_id] = now
        user_message_count[user_id] = 1
        return
    
    # Проверяем временное окно
    time_diff = (now - user_last_message_time[user_id]).total_seconds()
    
    if time_diff < Config.SPAM_LIMITS['time_window']:
        user_message_count[user_id] += 1
        
        # Проверяем превышение лимита сообщений
        if user_message_count[user_id] > Config.SPAM_LIMITS['max_messages']:
            stats = await get_user_stats(update, context, user_id)
            stats.add_warning()
            user_warnings[user_id] += 1
            
            # Удаляем спам-сообщения
            try:
                await message.delete()
            except Exception as e:
                logger.error(f"Не удалось удалить сообщение: {e}")
            
            warn_msg = await message.reply_text(
                f"{user.mention_html()}, не спамьте! Предупреждение {user_warnings[user_id]}/{Config.SPAM_LIMITS['warn_limit']}",
                parse_mode="HTML"
            )
            
            # Если превышено количество предупреждений - мут
            if user_warnings[user_id] >= Config.SPAM_LIMITS['warn_limit']:
                try:
                    until_date = now + timedelta(seconds=Config.SPAM_LIMITS['mute_duration'])
                    await context.bot.restrict_chat_member(
                        chat_id=update.effective_chat.id,
                        user_id=user_id,
                        permissions=ChatPermissions(
                            can_send_messages=False,
                            can_send_media_messages=False,
                            can_send_polls=False,
                            can_send_other_messages=False,
                            can_add_web_page_previews=False,
                            can_change_info=False,
                            can_invite_users=False,
                            can_pin_messages=False
                        ),
                        until_date=until_date
                    )
                    
                    stats.add_mute()
                    user_warnings[user_id] = 0
                    
                    mute_msg = await message.reply_text(
                        f"{user.mention_html()} получил мут на "
                        f"{Config.SPAM_LIMITS['mute_duration']//60} минут за спам.",
                        parse_mode="HTML"
                    )
                    
                    # Удаляем сообщения через 10 секунд
                    await asyncio.sleep(10)
                    try:
                        await warn_msg.delete()
                        await mute_msg.delete()
                    except Exception as e:
                        logger.error(f"Не удалось удалить сообщения: {e}")
                        
                except Exception as e:
                    logger.error(f"Ошибка при муте пользователя: {e}")
    else:
        # Сбрасываем счетчик, если временное окно истекло
        user_last_message_time[user_id] = now
        user_message_count[user_id] = 1

async def check_bad_words(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Проверка на запрещенные слова"""
    message = update.effective_message
    user = update.effective_user
    
    if not message or not message.text or not user:
        return
    
    # Список запрещенных слов (можно вынести в конфиг)
    bad_words = [
        "мат1", "мат2", "мат3", "оскорбление1", "оскорбление2"
    ]
    
    # Проверяем сообщение на наличие запрещенных слов
    text_lower = message.text.lower()
    found_words = [word for word in bad_words if word in text_lower]
    
    if found_words:
        stats = await get_user_stats(update, context, user.id)
        stats.add_warning()
        
        try:
            await message.delete()
        except Exception as e:
            logger.error(f"Не удалось удалить сообщение: {e}")
            return
        
        warn_msg = await message.reply_text(
            f"{user.mention_html()}, пожалуйста, соблюдайте правила чата и избегайте запрещенных слов.",
            parse_mode="HTML"
        )
        
        # Удаляем предупреждение через 10 секунд
        await asyncio.sleep(10)
        try:
            await warn_msg.delete()
        except Exception as e:
            logger.error(f"Не удалось удалить предупреждение: {e}")

# ==============================================
# ЗАПУСК БОТА
# ==============================================

def main() -> None:
    """Запускает бота"""
    # Инициализация базы данных и загрузка данных
    init_database()
    load_achievements()
    load_stats_from_db()
    
    # Создаем Application
    application = Application.builder().token(Config.TOKEN).build()
    
    # Регистрируем обработчики команд
    command_handlers = [
        CommandHandler("start", start),
        CommandHandler("help", help_command),
        CommandHandler("stats", user_statistics),
        CommandHandler("top", top_users),
        CommandHandler("me", user_profile),
        CommandHandler("achievements", show_achievements),
        CommandHandler("rules", rules_command),
        CommandHandler("pingall", ping_all_command),
        CommandHandler("reports", reports_command),
    ]
    
    for handler in command_handlers:
        application.add_handler(handler)
    
    # Обработчик для репортов (ConversationHandler)
    report_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("report", report_command)],
        states={
            REPORT_REASON: [CallbackQueryHandler(report_reason_handler, pattern="^report_")],
            REPORT_CONFIRM: [CallbackQueryHandler(report_confirm_handler, pattern="^report_confirm$")]
        },
        fallbacks=[
            CallbackQueryHandler(report_cancel_handler, pattern="^report_cancel$"),
            CommandHandler("cancel", report_cancel_handler)
        ]
    )
    application.add_handler(report_conv_handler)
    
    # Обработчик кнопок репортов
    application.add_handler(CallbackQueryHandler(report_button_handler, pattern="^(warn|mute|ban|reject)_"))
    
    # Обработчик кнопки правил
    application.add_handler(CallbackQueryHandler(show_rules_callback, pattern="^show_rules$"))
    
    # Регистрируем обработчики сообщений
    application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, collect_stats))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, auto_moderate))
    
    # Обработчики событий чата
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, greet_new_member))
    application.add_handler(MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER, goodbye_member))
    
    # Регистрируем обработчик ошибок
    application.add_error_handler(error_handler)
    
    # Запускаем бота
    application.run_polling(allowed_updates=Update.ALL_TYPES)
    
    # Запускаем фоновые задачи
    asyncio.get_event_loop().create_task(backup_stats())

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик ошибок"""
    logger.error(f"Ошибка при обработке обновления {update}: {context.error}")
    
    if update.effective_message:
        await update.effective_message.reply_text(
            "Произошла ошибка при обработке команды. Пожалуйста, попробуйте позже."
        )

if __name__ == "__main__":
    main()
