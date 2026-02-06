"""Telegram channel implementation using python-telegram-bot."""

import asyncio
import re

from loguru import logger
from telegram import Update
from telegram.error import Conflict
from telegram.ext import Application, MessageHandler, filters, ContextTypes

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import TelegramConfig


def _markdown_to_telegram_html(text: str) -> str:
    """
    Convert markdown to Telegram-safe HTML.
    """
    if not text:
        return ""
    
    # 1. Extract and protect code blocks (preserve content from other processing)
    code_blocks: list[str] = []
    def save_code_block(m: re.Match) -> str:
        code_blocks.append(m.group(1))
        return f"\x00CB{len(code_blocks) - 1}\x00"
    
    text = re.sub(r'```[\w]*\n?([\s\S]*?)```', save_code_block, text)
    
    # 2. Extract and protect inline code
    inline_codes: list[str] = []
    def save_inline_code(m: re.Match) -> str:
        inline_codes.append(m.group(1))
        return f"\x00IC{len(inline_codes) - 1}\x00"
    
    text = re.sub(r'`([^`]+)`', save_inline_code, text)
    
    # 3. Headers # Title -> just the title text
    text = re.sub(r'^#{1,6}\s+(.+)$', r'\1', text, flags=re.MULTILINE)
    
    # 4. Blockquotes > text -> just the text (before HTML escaping)
    text = re.sub(r'^>\s*(.*)$', r'\1', text, flags=re.MULTILINE)
    
    # 5. Escape HTML special characters
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    
    # 6. Links [text](url) - must be before bold/italic to handle nested cases
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', text)
    
    # 7. Bold **text** or __text__
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'__(.+?)__', r'<b>\1</b>', text)
    
    # 8. Italic _text_ (avoid matching inside words like some_var_name)
    text = re.sub(r'(?<![a-zA-Z0-9])_([^_]+)_(?![a-zA-Z0-9])', r'<i>\1</i>', text)
    
    # 9. Strikethrough ~~text~~
    text = re.sub(r'~~(.+?)~~', r'<s>\1</s>', text)
    
    # 10. Bullet lists - item -> • item
    text = re.sub(r'^[-*]\s+', '• ', text, flags=re.MULTILINE)
    
    # 11. Restore inline code with HTML tags
    for i, code in enumerate(inline_codes):
        # Escape HTML in code content
        escaped = code.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        text = text.replace(f"\x00IC{i}\x00", f"<code>{escaped}</code>")
    
    # 12. Restore code blocks with HTML tags
    for i, code in enumerate(code_blocks):
        # Escape HTML in code content
        escaped = code.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        text = text.replace(f"\x00CB{i}\x00", f"<pre><code>{escaped}</code></pre>")
    
    return text


class TelegramChannel(BaseChannel):
    """
    Telegram channel using long polling.
    
    Simple and reliable - no webhook/public IP needed.
    """
    
    name = "telegram"
    
    def __init__(self, config: TelegramConfig, bus: MessageBus, groq_api_key: str = ""):
        super().__init__(config, bus)
        self.config: TelegramConfig = config
        self.groq_api_key = groq_api_key
        self._app: Application | None = None
        self._chat_ids: dict[str, int] = {}  # Map sender_id to chat_id for replies
        self._polling_task: asyncio.Task | None = None
        self._polling_started = False
    
    async def start(self) -> None:
        """Start the Telegram bot with long polling and robust error recovery."""
        if not self.config.token:
            logger.error("Telegram bot token not configured")
            return
        
        self._running = True
        max_retries = 5
        retry_count = 0
        retry_backoff = 2  # Start with 2 second backoff
        
        while self._running and retry_count < max_retries:
            try:
                # Build the application (fresh each retry)
                self._app = (
                    Application.builder()
                    .token(self.config.token)
                    .build()
                )
                
                # Add message handler for text, photos, voice, documents
                self._app.add_handler(
                    MessageHandler(
                        (filters.TEXT | filters.PHOTO | filters.VOICE | filters.AUDIO | filters.Document.ALL)
                        & ~filters.COMMAND, 
                        self._on_message
                    )
                )
                
                # Add /start command handler
                from telegram.ext import CommandHandler
                self._app.add_handler(CommandHandler("start", self._on_start))
                
                logger.info("Starting Telegram bot (polling mode)...")
                
                # Initialize and start
                await self._app.initialize()
                await self._app.start()
                
                # Get bot info
                bot_info = await self._app.bot.get_me()
                logger.info(f"Telegram bot @{bot_info.username} connected")
                
                # Start polling in a separate task so we can monitor it
                self._polling_task = asyncio.create_task(
                    self._app.updater.start_polling(
                        allowed_updates=["message"],
                        drop_pending_updates=True
                    )
                )
                
                self._polling_started = True
                retry_count = 0  # Reset retry count on success
                logger.info("Telegram polling started successfully")
                
                # Monitor polling task - wait for it to complete or for stop signal
                while self._running:
                    try:
                        # Check if polling task is still running
                        if self._polling_task.done():
                            # Polling task ended unexpectedly
                            try:
                                # This will raise the exception if task failed
                                await asyncio.wait_for(self._polling_task, timeout=0.1)
                            except (asyncio.TimeoutError, asyncio.CancelledError):
                                pass
                            except Conflict as e:
                                logger.error(f"Polling conflict detected: {e}")
                                raise e
                            except Exception as e:
                                logger.error(f"Polling task failed unexpectedly: {type(e).__name__}: {e}")
                                raise e
                        
                        # Normal monitoring sleep
                        await asyncio.sleep(5)
                    except asyncio.CancelledError:
                        logger.info("Polling monitor cancelled")
                        break
                    except (Conflict, Exception):
                        # Re-raise to outer exception handler for retry logic
                        raise
                
                # Normal exit
                break
                
            except Conflict as e:
                logger.error(
                    f"Telegram polling conflict: another getUpdates client running "
                    f"(attempt {retry_count + 1}/{max_retries})"
                )
                logger.debug(f"Conflict detail: {e}")
                
                # Cleanup on conflict
                self._polling_started = False
                if self._polling_task:
                    self._polling_task.cancel()
                    self._polling_task = None
                
                if self._app:
                    try:
                        await self._app.stop()
                        await self._app.shutdown()
                    except Exception as cleanup_err:
                        logger.debug(f"Cleanup error: {cleanup_err}")
                    self._app = None
                
                # Attempt diagnostic
                try:
                    import httpx
                    token = self.config.token
                    if token:
                        webhook_url = f"https://api.telegram.org/bot{token}/getWebhookInfo"
                        async with httpx.AsyncClient(timeout=5.0) as c:
                            resp = await c.get(webhook_url)
                        if resp.status_code == 200:
                            logger.info(f"Webhook info: {resp.text}")
                except Exception as diagnostic_err:
                    logger.debug(f"Diagnostic check failed: {diagnostic_err}")
                
                # Exponential backoff retry
                retry_count += 1
                if retry_count < max_retries and self._running:
                    wait_time = retry_backoff ** retry_count
                    logger.info(f"Retrying in {wait_time}s... ({retry_count}/{max_retries})")
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(
                        "Max retries reached for Telegram polling. "
                        "Please check:\n"
                        "  1. Kill other bot processes: pkill -f 'python.*nanobot'\n"
                        "  2. Check Docker: docker ps | grep telegram\n"
                        "  3. Disable webhook: curl https://api.telegram.org/bot{token}/deleteWebhook"
                    )
                    break
                    
            except Exception as e:
                logger.error(f"Telegram error (attempt {retry_count + 1}/{max_retries}): {type(e).__name__}: {e}")
                
                # Cleanup
                self._polling_started = False
                if self._polling_task:
                    self._polling_task.cancel()
                    self._polling_task = None
                
                if self._app:
                    try:
                        await self._app.stop()
                        await self._app.shutdown()
                    except Exception:
                        pass
                    self._app = None
                
                retry_count += 1
                if retry_count < max_retries and self._running:
                    wait_time = retry_backoff ** retry_count
                    logger.info(f"Retrying in {wait_time}s... ({retry_count}/{max_retries})")
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(f"Telegram channel stopped after {retry_count} failed attempts")
                    break
        
        # Final cleanup
        self._polling_started = False
        if self._polling_task:
            self._polling_task.cancel()
            self._polling_task = None
    async def stop(self) -> None:
        """Stop the Telegram bot cleanly."""
        logger.info("Stopping Telegram bot...")
        self._running = False
        
        # Cancel polling task if running
        if self._polling_task and not self._polling_task.done():
            self._polling_task.cancel()
            try:
                await asyncio.wait_for(self._polling_task, timeout=2.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass
        
        self._polling_task = None
        
        # Stop the app
        if self._app:
            try:
                logger.debug("Stopping updater...")
                await self._app.updater.stop()
                logger.debug("Stopping app...")
                await self._app.stop()
                logger.debug("Shutting down app...")
                await self._app.shutdown()
            except Exception as e:
                logger.warning(f"Error during Telegram cleanup: {e}")
            finally:
                self._app = None
        
        self._polling_started = False
        logger.info("Telegram bot stopped")
    
    async def send(self, msg: OutboundMessage) -> None:
        """Send a message through Telegram."""
        if not self._app:
            logger.warning("Telegram bot not initialized or stopped")
            return
        
        if not self._polling_started:
            logger.warning("Telegram polling not active, cannot send message")
            return
        
        try:
            # chat_id should be the Telegram chat ID (integer)
            chat_id = int(msg.chat_id)
            # Convert markdown to Telegram HTML
            html_content = _markdown_to_telegram_html(msg.content)
            await self._app.bot.send_message(
                chat_id=chat_id,
                text=html_content,
                parse_mode="HTML"
            )
            logger.debug(f"Message sent to {chat_id}")
        except ValueError:
            logger.error(f"Invalid chat_id: {msg.chat_id}")
        except Exception as e:
            logger.warning(f"Failed to send HTML message: {type(e).__name__}: {e}, falling back to plain text")
            try:
                await self._app.bot.send_message(
                    chat_id=int(msg.chat_id),
                    text=msg.content
                )
                logger.debug(f"Plain text message sent to {msg.chat_id}")
            except Exception as e2:
                logger.error(f"Failed to send plain text message: {type(e2).__name__}: {e2}")
    
    async def _on_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /start command."""
        if not update.message or not update.effective_user:
            return
        
        user = update.effective_user
        await update.message.reply_text(
            f"👋 Hi {user.first_name}! I'm nanobot.\n\n"
            "Send me a message and I'll respond!"
        )
    
    async def _on_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle incoming messages (text, photos, voice, documents)."""
        if not update.message or not update.effective_user:
            return
        
        message = update.message
        user = update.effective_user
        chat_id = message.chat_id
        
        # Use stable numeric ID, but keep username for allowlist compatibility
        sender_id = str(user.id)
        if user.username:
            sender_id = f"{sender_id}|{user.username}"
        
        # Store chat_id for replies
        self._chat_ids[sender_id] = chat_id
        
        # Build content from text and/or media
        content_parts = []
        media_paths = []
        
        # Text content
        if message.text:
            content_parts.append(message.text)
        if message.caption:
            content_parts.append(message.caption)
        
        # Handle media files
        media_file = None
        media_type = None
        
        if message.photo:
            media_file = message.photo[-1]  # Largest photo
            media_type = "image"
        elif message.voice:
            media_file = message.voice
            media_type = "voice"
        elif message.audio:
            media_file = message.audio
            media_type = "audio"
        elif message.document:
            media_file = message.document
            media_type = "file"
        
        # Download media if present
        if media_file and self._app:
            try:
                file = await self._app.bot.get_file(media_file.file_id)
                ext = self._get_extension(media_type, getattr(media_file, 'mime_type', None))
                
                # Save to workspace/media/
                from pathlib import Path
                media_dir = Path.home() / ".nanobot" / "media"
                media_dir.mkdir(parents=True, exist_ok=True)
                
                file_path = media_dir / f"{media_file.file_id[:16]}{ext}"
                await file.download_to_drive(str(file_path))
                
                media_paths.append(str(file_path))
                
                # Handle voice transcription
                if media_type == "voice" or media_type == "audio":
                    from nanobot.providers.transcription import GroqTranscriptionProvider
                    transcriber = GroqTranscriptionProvider(api_key=self.groq_api_key)
                    transcription = await transcriber.transcribe(file_path)
                    if transcription:
                        logger.info(f"Transcribed {media_type}: {transcription[:50]}...")
                        content_parts.append(f"[transcription: {transcription}]")
                    else:
                        content_parts.append(f"[{media_type}: {file_path}]")
                else:
                    content_parts.append(f"[{media_type}: {file_path}]")
                    
                logger.debug(f"Downloaded {media_type} to {file_path}")
            except Exception as e:
                logger.error(f"Failed to download media: {e}")
                content_parts.append(f"[{media_type}: download failed]")
        
        content = "\n".join(content_parts) if content_parts else "[empty message]"
        
        logger.debug(f"Telegram message from {sender_id}: {content[:50]}...")
        
        # Forward to the message bus
        await self._handle_message(
            sender_id=sender_id,
            chat_id=str(chat_id),
            content=content,
            media=media_paths,
            metadata={
                "message_id": message.message_id,
                "user_id": user.id,
                "username": user.username,
                "first_name": user.first_name,
                "is_group": message.chat.type != "private"
            }
        )
    
    def _get_extension(self, media_type: str, mime_type: str | None) -> str:
        """Get file extension based on media type."""
        if mime_type:
            ext_map = {
                "image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif",
                "audio/ogg": ".ogg", "audio/mpeg": ".mp3", "audio/mp4": ".m4a",
            }
            if mime_type in ext_map:
                return ext_map[mime_type]
        
        type_map = {"image": ".jpg", "voice": ".ogg", "audio": ".mp3", "file": ""}
        return type_map.get(media_type, "")
