"""
FIX #2: Timeout for execute_command - PATCH

Replace the execute method in ChatCommandsService with this implementation
to add timeout protection, result validation, and proper error handling.
"""

import asyncio
import logging

logger = logging.getLogger("bot.chat_commands")

COMMAND_EXECUTION_TIMEOUT = 10.0  # seconds
MAX_DISCORD_MESSAGE_LENGTH = 2000

async def execute(self, source: str, user_str: str, text: str) -> str | None:
    """Execute chat command with timeout and result validation
    
    Args:
        source: Platform (twitch, kick, vk, etc)
        user_str: Username/ID
        text: Command text (!help, !play, etc)
    
    Returns:
        Response string, None if not a command, or error message
    """
    # 1. Parse command
    if not text.startswith('!'):
        return None
    
    parts = text.split(maxsplit=1)
    if not parts:
        return None
    
    command_name = parts[0][1:].lower()  # Remove ! and lowercase
    args = parts[1:] if len(parts) > 1 else []
    
    # 2. Validate command exists
    cmd = self.bot.get_command(command_name)
    if cmd is None:
        return None  # Not a valid command
    
    # 3. Check rate limit
    if not await self._rate_limit_ok(user_str):
        return "❌ **Too many commands!** Please wait a moment and try again. (Rate limited)"
    
    # 4. Log attempt
    logger.debug(
        "Executing command: %s from %s (%s) with args: %s",
        command_name, user_str, source, args
    )
    
    # 5. Execute with timeout protection
    try:
        result = await asyncio.wait_for(
            self._invoke_command_safe(cmd, args),
            timeout=COMMAND_EXECUTION_TIMEOUT
        )
    except asyncio.TimeoutError:
        logger.warning(
            "Command execution timeout (%ds): %s from %s via %s",
            COMMAND_EXECUTION_TIMEOUT, command_name, user_str, source
        )
        return f"❌ **Command timeout!** {command_name} took too long (>{COMMAND_EXECUTION_TIMEOUT}s)"
    except Exception as e:
        logger.exception("Command execution error: %s", command_name)
        error_msg = str(e)[:150]  # Truncate long error messages
        return f"❌ **Error:** {error_msg}"
    
    # 6. Validate result
    if result is None:
        return None
    
    # 7. Truncate result to Discord's message limit
    result_str = str(result).strip()
    if not result_str:
        return None
    
    if len(result_str) > MAX_DISCORD_MESSAGE_LENGTH - 6:  # Reserve for "..."
        logger.debug(
            "Command result truncated: %s returned %d chars (limit: %d)",
            command_name, len(result_str), MAX_DISCORD_MESSAGE_LENGTH
        )
        result_str = result_str[:MAX_DISCORD_MESSAGE_LENGTH - 6] + "... [truncated]"
    
    # 8. Log success
    logger.debug("Command executed successfully: %s", command_name)
    return result_str

async def _invoke_command_safe(self, cmd, args) -> str | None:
    """Execute Discord command with proper context
    
    This is separated from execute() to allow timeout wrapping.
    """
    try:
        # Create context for command
        ctx = await self._prepare_context(cmd, args)
        
        # Invoke command
        result = await cmd.invoke(ctx)
        
        return result
    except asyncio.CancelledError:
        # Re-raise cancellation (timeout)
        raise
    except Exception as e:
        logger.exception("Error in command invocation")
        raise

# ============================================================================
# ADD THIS TO __init__ method:
# ============================================================================

# In ChatCommandsService.__init__:
self._timeout_seconds = COMMAND_EXECUTION_TIMEOUT
self._max_message_length = MAX_DISCORD_MESSAGE_LENGTH
