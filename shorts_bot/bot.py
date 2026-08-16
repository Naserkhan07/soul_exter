from __future__ import annotations

import logging
from pathlib import Path

from telegram import BotCommand, Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from .config import Settings
from .db import JobRepository
from .downloader import extract_youtube_urls
from .models import Job, JobStatus
from .pipeline import JobQueue, WorkflowPipeline, WorkflowServices

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

_HELP = """Send one or more authorized YouTube links and I will create one Short per link.

Commands:
/short <url> [url ...] — queue videos
/status [job_id] — show recent jobs or one job
/help — show this message

You can also paste links without a command. This bot only accepts YouTube URLs. The channel owner
must own the videos or have explicit permission to download, edit, and republish them."""


def _authorized(update: Update, settings: Settings) -> bool:
    user = update.effective_user
    return bool(user and user.id in settings.allowed_telegram_user_ids)


async def _reject_unauthorized(update: Update) -> None:
    if update.effective_message:
        user_id = update.effective_user.id if update.effective_user else "unknown"
        await update.effective_message.reply_text(
            "This is a private bot and your account is not allowed. "
            f"Your Telegram user ID is {user_id}."
        )


def _format_job(job: Job) -> str:
    icon = {
        JobStatus.QUEUED: "⏳",
        JobStatus.DOWNLOADING: "⬇️",
        JobStatus.ANALYZING: "🧠",
        JobStatus.RENDERING: "🎬",
        JobStatus.UPLOADING: "⬆️",
        JobStatus.COMPLETE: "✅",
        JobStatus.FAILED: "❌",
    }[job.status]
    lines = [f"{icon} Job {job.id}: {job.status.value}", job.progress_message]
    if job.source_title:
        lines.append(f"Source: {job.source_title}")
    if job.short_title:
        lines.append(f"Title: {job.short_title}")
    if job.youtube_url:
        lines.append(job.youtube_url)
    if job.error:
        lines.append(f"Error: {job.error}")
    return "\n".join(lines)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    if not _authorized(update, settings):
        await _reject_unauthorized(update)
        return
    await update.effective_message.reply_text(
        "YouTube Shorts workflow is ready.\n\n" + _HELP  # type: ignore[union-attr]
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    if not _authorized(update, settings):
        await _reject_unauthorized(update)
        return
    await update.effective_message.reply_text(_HELP)  # type: ignore[union-attr]


async def short_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.effective_message.text if update.effective_message else ""
    await _queue_urls(update, context, text)


async def links_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.effective_message.text if update.effective_message else ""
    if extract_youtube_urls(text):
        await _queue_urls(update, context, text)
    elif _authorized(update, context.application.bot_data["settings"]):
        await update.effective_message.reply_text("Send a YouTube URL or use /help.")  # type: ignore[union-attr]
    else:
        await _reject_unauthorized(update)


async def _queue_urls(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
) -> None:
    settings: Settings = context.application.bot_data["settings"]
    if not _authorized(update, settings):
        await _reject_unauthorized(update)
        return
    message = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    if not message or not user or not chat:
        return

    urls = extract_youtube_urls(text)
    if not urls:
        await message.reply_text("Usage: /short <YouTube URL> [more YouTube URLs]")
        return
    if len(urls) > settings.max_urls_per_command:
        await message.reply_text(
            f"Please send at most {settings.max_urls_per_command} links at once."
        )
        return

    repository: JobRepository = context.application.bot_data["repository"]
    queue: JobQueue = context.application.bot_data["queue"]
    progress_messages: dict[str, tuple[int, int]] = context.application.bot_data[
        "progress_messages"
    ]
    for url in urls:
        job = repository.create(chat.id, user.id, url)
        progress = await message.reply_text(_format_job(job))
        progress_messages[job.id] = (chat.id, progress.message_id)
        await queue.enqueue(job.id)


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    if not _authorized(update, settings):
        await _reject_unauthorized(update)
        return
    message = update.effective_message
    user = update.effective_user
    if not message or not user:
        return

    repository: JobRepository = context.application.bot_data["repository"]
    if context.args:
        job = repository.get(context.args[0])
        if not job or job.user_id != user.id:
            await message.reply_text("Job not found.")
            return
        await message.reply_text(_format_job(job))
        return

    jobs = repository.list_recent(user.id, limit=10)
    if not jobs:
        await message.reply_text("No jobs yet. Use /short with a YouTube URL.")
        return
    await message.reply_text("\n\n".join(_format_job(job) for job in jobs))


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Telegram update failed", exc_info=context.error)


def build_application(settings: Settings) -> Application:
    settings.validate_bot()
    settings.prepare_directories()

    repository = JobRepository(settings.database_path)
    media_services = WorkflowServices.from_settings(settings)
    media_services.media.check_tools()
    progress_messages: dict[str, tuple[int, int]] = {}
    application_holder: dict[str, Application] = {}

    async def notify(job: Job, _message: str) -> None:
        application = application_holder["application"]
        location = progress_messages.get(job.id)
        if location:
            chat_id, message_id = location
            try:
                await application.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=_format_job(job),
                )
            except Exception:
                logger.debug("Could not edit progress message for %s", job.id, exc_info=True)

        if job.status == JobStatus.COMPLETE:
            await _send_completed_file(application, job)
        elif job.status == JobStatus.FAILED and not location:
            await application.bot.send_message(chat_id=job.chat_id, text=_format_job(job))

    pipeline = WorkflowPipeline(settings, repository, media_services, on_status=notify)
    queue = JobQueue(pipeline)

    async def post_init(application: Application) -> None:
        interrupted = repository.fail_interrupted()
        if interrupted:
            logger.warning("Marked %d interrupted jobs as failed", interrupted)
        queue.start()
        for job in repository.list_queued():
            await queue.enqueue(job.id)
        await application.bot.set_my_commands(
            [
                BotCommand("short", "Create Shorts from YouTube links"),
                BotCommand("status", "Show workflow status"),
                BotCommand("help", "Show instructions"),
            ]
        )

    async def post_shutdown(_application: Application) -> None:
        await queue.stop()

    application = (
        ApplicationBuilder()
        .token(settings.telegram_bot_token)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )
    application_holder["application"] = application
    application.bot_data.update(
        {
            "settings": settings,
            "repository": repository,
            "queue": queue,
            "progress_messages": progress_messages,
        }
    )
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("short", short_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, links_message))
    application.add_error_handler(error_handler)
    return application


async def _send_completed_file(application: Application, job: Job) -> None:
    if job.youtube_url:
        await application.bot.send_message(
            chat_id=job.chat_id,
            text=f"Published: {job.youtube_url}\n\n{job.short_title or ''}",
        )
        return
    if not job.output_path:
        return
    output = Path(job.output_path)
    if output.exists() and output.stat().st_size <= 49 * 1024 * 1024:
        await application.bot.send_chat_action(job.chat_id, ChatAction.UPLOAD_VIDEO)
        with output.open("rb") as video:
            await application.bot.send_video(
                chat_id=job.chat_id,
                video=video,
                caption=(job.short_title or "Short is ready")[:1024],
                supports_streaming=True,
            )
    else:
        await application.bot.send_message(
            chat_id=job.chat_id,
            text=(
                "The Short is ready but is too large to send through Telegram. "
                f"It is saved at {output}."
            ),
        )


def main() -> None:
    settings = Settings.from_env()
    application = build_application(settings)
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
