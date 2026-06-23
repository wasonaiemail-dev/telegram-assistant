"""
marvin/core/plugin_loader.py
============================
Auto-discovery plugin loader for Marvin.

HOW PLUGINS WORK
────────────────
Each plugin lives in  plugins/<name>/  and exposes a  PLUGIN_META  dict
in its  __init__.py.  At bot startup the loader:

  1. Scans the plugins/ directory for sub-packages with PLUGIN_META.
  2. Validates metadata and collects:
       • Telegram /commands  → registered as CommandHandlers
       • Intents + dispatch  → injected into _dispatch() fallback
       • Keyword rules       → merged into Layer 1 of intent.py
       • GPT intent defs     → appended to the Layer 2 system prompt
       • Background jobs     → scheduled on the job queue
       • Callback patterns   → registered as CallbackQueryHandlers
  3. Exposes a registry that bot.py queries at each step.

PLUGIN_META SPEC
────────────────
A plugin's __init__.py must define:

    PLUGIN_META = {
        "name":        "Sports Pack",             # display name
        "version":     "1.0.0",
        "description": "Live scores, standings, and betting tools",
        "author":      "Marvin",

        # ── Telegram /commands ──────────────────────────────────────
        # Each entry becomes a CommandHandler in bot.py.
        # "handler" is a dotted import path resolved lazily.
        "commands": [
            {
                "command":     "scores",
                "handler":     "plugins.sports.commands.cmd_scores",
                "description": "Live scores and results",
            },
        ],

        # ── Intent routing ──────────────────────────────────────────
        # Maps intent strings to a single dispatcher function.
        # When _dispatch() doesn't match a core intent, it checks plugins.
        "intents": ["sports_scores", "sports_standings", ...],
        "intent_handler": "plugins.sports.dispatch.handle_sports_intent",

        # ── Layer 1 keyword rules (optional) ────────────────────────
        # A dotted path to a function that returns a list of
        # (compiled_regex, handler_fn) tuples — same format as
        # _build_keyword_rules() in intent.py.
        "keyword_rules_fn": "plugins.sports.keywords.build_rules",

        # ── Layer 2 GPT intent definitions (optional) ───────────────
        # A block of text appended to the GPT classification prompt.
        # Must follow the same format as core intents in intent.py.
        "gpt_intent_block": "sports_scores  Get live scores...",

        # ── Background jobs (optional) ──────────────────────────────
        "jobs": [
            {
                "type":    "daily",               # "daily" or "repeating"
                "handler": "plugins.sports.jobs.job_game_alerts",
                "hour":    9,
                "minute":  0,
                "name":    "sports_game_alerts",
            },
        ],

        # ── Callback query patterns (optional) ──────────────────────
        "callbacks": [
            {
                "pattern": "^sports_",
                "handler": "plugins.sports.callbacks.handle_sports_callback",
            },
        ],
    }

PUBLIC INTERFACE
────────────────
  discover_plugins()                   → list[PluginInfo]
  register_commands(app, plugins)      → None  (call in main())
  register_jobs(job_queue, tz, plugins)→ None  (call in _schedule_jobs())
  register_callbacks(app, plugins)     → None  (call in main())
  get_plugin_keyword_rules(plugins)    → list  (merged into intent.py)
  get_plugin_gpt_block(plugins)        → str   (appended to GPT prompt)
  dispatch_plugin_intent(intent_result, update, context, plugins) → bool
"""

import os
import re
import logging
import importlib
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)

# Directory where plugins live (relative to project root)
PLUGINS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "plugins")

# Required keys in PLUGIN_META
_REQUIRED_KEYS = {"name", "version", "description"}


# ═══════════════════════════════════════════════════════════════════════════════
# DATA STRUCTURES
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class PluginInfo:
    """Validated, loaded representation of a plugin."""
    name:             str
    version:          str
    description:      str
    author:           str = ""
    package:          str = ""          # e.g. "plugins.sports"
    commands:         list = field(default_factory=list)
    intents:          set  = field(default_factory=set)
    intent_handler:   Any  = None       # resolved callable
    keyword_rules_fn: Any  = None       # resolved callable
    gpt_intent_block: str  = ""
    jobs:             list = field(default_factory=list)
    callbacks:        list = field(default_factory=list)
    enabled:          bool = True


# ═══════════════════════════════════════════════════════════════════════════════
# IMPORT HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _resolve_dotted(path: str) -> Any:
    """
    Resolve a dotted path like 'plugins.sports.commands.cmd_scores'
    to the actual Python object (function, class, etc.).

    Raises ImportError or AttributeError on failure.
    """
    parts = path.rsplit(".", 1)
    if len(parts) == 2:
        module_path, attr_name = parts
        mod = importlib.import_module(module_path)
        return getattr(mod, attr_name)
    else:
        return importlib.import_module(path)


def _safe_resolve(path: str, label: str) -> Any:
    """Resolve a dotted path, logging errors instead of crashing."""
    try:
        return _resolve_dotted(path)
    except Exception as e:
        logger.error(f"plugin_loader: could not resolve {label} '{path}': {e}")
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# DISCOVERY
# ═══════════════════════════════════════════════════════════════════════════════

def discover_plugins() -> list:
    """
    Scan the plugins/ directory for sub-packages with PLUGIN_META.

    Returns a list of validated PluginInfo objects, one per discovered plugin.
    Plugins that fail validation are logged and skipped — never crash the bot.
    """
    plugins = []

    if not os.path.isdir(PLUGINS_DIR):
        logger.info("plugin_loader: plugins/ directory not found — no plugins loaded.")
        return plugins

    for entry in sorted(os.listdir(PLUGINS_DIR)):
        entry_path = os.path.join(PLUGINS_DIR, entry)

        # Skip __pycache__, files, hidden dirs
        if entry.startswith("_") or entry.startswith(".") or not os.path.isdir(entry_path):
            continue

        init_path = os.path.join(entry_path, "__init__.py")
        if not os.path.exists(init_path):
            continue

        package_name = f"plugins.{entry}"

        try:
            mod = importlib.import_module(package_name)
        except Exception as e:
            logger.error(f"plugin_loader: failed to import {package_name}: {e}")
            continue

        meta = getattr(mod, "PLUGIN_META", None)
        if meta is None:
            logger.debug(f"plugin_loader: {package_name} has no PLUGIN_META — skipping.")
            continue

        if not isinstance(meta, dict):
            logger.warning(f"plugin_loader: {package_name} PLUGIN_META is not a dict — skipping.")
            continue

        # Validate required keys
        missing = _REQUIRED_KEYS - set(meta.keys())
        if missing:
            logger.warning(
                f"plugin_loader: {package_name} missing required keys: {missing} — skipping."
            )
            continue

        # Build PluginInfo
        plugin = PluginInfo(
            name=meta["name"],
            version=meta["version"],
            description=meta["description"],
            author=meta.get("author", ""),
            package=package_name,
            gpt_intent_block=meta.get("gpt_intent_block", ""),
            enabled=meta.get("enabled", True),
        )

        # Resolve commands
        for cmd_spec in meta.get("commands", []):
            handler = _safe_resolve(cmd_spec["handler"], f"{package_name} command")
            if handler:
                plugin.commands.append({
                    "command":     cmd_spec["command"],
                    "handler":     handler,
                    "description": cmd_spec.get("description", ""),
                })

        # Resolve intents + dispatcher
        plugin.intents = set(meta.get("intents", []))
        handler_path = meta.get("intent_handler")
        if handler_path:
            plugin.intent_handler = _safe_resolve(handler_path, f"{package_name} intent_handler")

        # Resolve keyword rules builder
        kw_path = meta.get("keyword_rules_fn")
        if kw_path:
            plugin.keyword_rules_fn = _safe_resolve(kw_path, f"{package_name} keyword_rules_fn")

        # Resolve jobs
        for job_spec in meta.get("jobs", []):
            handler = _safe_resolve(job_spec["handler"], f"{package_name} job")
            if handler:
                plugin.jobs.append({
                    "type":    job_spec.get("type", "daily"),
                    "handler": handler,
                    "hour":    job_spec.get("hour", 9),
                    "minute":  job_spec.get("minute", 0),
                    "interval": job_spec.get("interval", 300),
                    "name":    job_spec.get("name", f"{entry}_job"),
                    "weekday": job_spec.get("weekday", None),
                })

        # Resolve callbacks
        for cb_spec in meta.get("callbacks", []):
            handler = _safe_resolve(cb_spec["handler"], f"{package_name} callback")
            if handler:
                plugin.callbacks.append({
                    "pattern": cb_spec["pattern"],
                    "handler": handler,
                })

        if plugin.enabled:
            plugins.append(plugin)
            logger.info(
                f"plugin_loader: loaded '{plugin.name}' v{plugin.version} "
                f"({len(plugin.commands)} cmds, {len(plugin.intents)} intents, "
                f"{len(plugin.jobs)} jobs)"
            )
        else:
            logger.info(f"plugin_loader: '{plugin.name}' is disabled — skipping.")

    return plugins


# ═══════════════════════════════════════════════════════════════════════════════
# REGISTRATION HOOKS — called from bot.py
# ═══════════════════════════════════════════════════════════════════════════════

def register_commands(app, plugins: list) -> list:
    """
    Register all plugin /commands as Telegram CommandHandlers.

    Call this in main() after building the Application but before run_polling().
    Returns a flat list of BotCommand tuples for set_my_commands().
    """
    from telegram.ext import CommandHandler as CH

    bot_commands = []
    for plugin in plugins:
        for cmd in plugin.commands:
            try:
                app.add_handler(CH(cmd["command"], cmd["handler"]))
                bot_commands.append((cmd["command"], cmd["description"]))
                logger.debug(f"plugin_loader: registered /{cmd['command']} from {plugin.name}")
            except Exception as e:
                logger.error(f"plugin_loader: failed to register /{cmd['command']}: {e}")

    return bot_commands


def register_jobs(job_queue, tz, plugins: list) -> None:
    """
    Schedule all plugin background jobs.

    Call this in _schedule_jobs() after scheduling core jobs.
    """
    import datetime as _dt

    for plugin in plugins:
        for job in plugin.jobs:
            try:
                if job["type"] == "daily":
                    jtime = _dt.time(
                        hour=job["hour"],
                        minute=job["minute"],
                        tzinfo=tz,
                    )
                    if job.get("weekday") is not None:
                        # Run only on a specific weekday (0=Mon, 6=Sun)
                        job_queue.run_daily(
                            job["handler"],
                            time=jtime,
                            days=(job["weekday"],),
                            name=job["name"],
                        )
                    else:
                        job_queue.run_daily(
                            job["handler"],
                            time=jtime,
                            name=job["name"],
                        )
                elif job["type"] == "repeating":
                    job_queue.run_repeating(
                        job["handler"],
                        interval=job["interval"],
                        first=10,
                        name=job["name"],
                    )
                logger.debug(
                    f"plugin_loader: scheduled job '{job['name']}' from {plugin.name}"
                )
            except Exception as e:
                logger.error(
                    f"plugin_loader: failed to schedule job '{job['name']}': {e}"
                )


def register_callbacks(app, plugins: list) -> None:
    """
    Register all plugin callback query handlers.

    Call this in main() BEFORE the general fallback CallbackQueryHandler.
    """
    from telegram.ext import CallbackQueryHandler as CQH

    for plugin in plugins:
        for cb in plugin.callbacks:
            try:
                app.add_handler(CQH(cb["handler"], pattern=cb["pattern"]))
                logger.debug(
                    f"plugin_loader: registered callback pattern '{cb['pattern']}' "
                    f"from {plugin.name}"
                )
            except Exception as e:
                logger.error(
                    f"plugin_loader: failed to register callback '{cb['pattern']}': {e}"
                )


# ═══════════════════════════════════════════════════════════════════════════════
# INTENT INTEGRATION
# ═══════════════════════════════════════════════════════════════════════════════

def get_plugin_keyword_rules(plugins: list) -> list:
    """
    Collect keyword rules from all plugins.

    Returns a flat list of (compiled_regex, handler_fn) tuples that
    intent.py merges into its Layer 1 rules.
    """
    rules = []
    for plugin in plugins:
        if plugin.keyword_rules_fn:
            try:
                plugin_rules = plugin.keyword_rules_fn()
                if isinstance(plugin_rules, list):
                    rules.extend(plugin_rules)
                    logger.debug(
                        f"plugin_loader: {len(plugin_rules)} keyword rules from {plugin.name}"
                    )
            except Exception as e:
                logger.error(
                    f"plugin_loader: keyword_rules_fn failed for {plugin.name}: {e}"
                )
    return rules


def get_plugin_gpt_block(plugins: list) -> str:
    """
    Collect GPT intent definition blocks from all plugins.

    Returns a single string to append to the core GPT system prompt.
    """
    blocks = []
    for plugin in plugins:
        if plugin.gpt_intent_block:
            blocks.append(f"\n# ── {plugin.name} ──\n{plugin.gpt_intent_block}")
    return "\n".join(blocks)


def get_all_plugin_intents(plugins: list) -> set:
    """Return the union of all intent strings registered by plugins."""
    intents = set()
    for plugin in plugins:
        intents.update(plugin.intents)
    return intents


async def dispatch_plugin_intent(intent_result, update, context, plugins: list) -> bool:
    """
    Try to dispatch an intent to a plugin handler.

    Called from bot.py's _dispatch() when no core intent matches.

    Returns:
        True  — a plugin handled it
        False — no plugin claimed this intent
    """
    intent = intent_result.intent

    for plugin in plugins:
        if intent in plugin.intents and plugin.intent_handler:
            try:
                await plugin.intent_handler(intent_result, update, context)
                return True
            except Exception as e:
                logger.error(
                    f"plugin_loader: {plugin.name} handler error for '{intent}': {e}"
                )
                await update.message.reply_text(
                    f"Something went wrong with the {plugin.name} plugin. "
                    f"Try again or use the /help command."
                )
                return True  # Claimed but errored — don't fall through

    return False


# ═══════════════════════════════════════════════════════════════════════════════
# UTILITY
# ═══════════════════════════════════════════════════════════════════════════════

def list_plugins(plugins: list) -> str:
    """Format a user-facing list of loaded plugins."""
    if not plugins:
        return "No plugins installed."

    lines = []
    for p in plugins:
        cmds = ", ".join(f"/{c['command']}" for c in p.commands)
        lines.append(f"• <b>{p.name}</b> v{p.version} — {p.description}")
        if cmds:
            lines.append(f"  Commands: {cmds}")
    return "\n".join(lines)
