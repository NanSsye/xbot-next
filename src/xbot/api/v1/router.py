from __future__ import annotations

from fastapi import APIRouter

from xbot.api.v1 import adapters, agent, bot, config, conversations, messages, plugins, skills, system

router = APIRouter()
router.include_router(system.router, prefix="/system", tags=["system"])
router.include_router(bot.router, prefix="/bot", tags=["bot"])
router.include_router(adapters.router, prefix="/adapters", tags=["adapters"])
router.include_router(plugins.router, prefix="/plugins", tags=["plugins"])
router.include_router(skills.router, prefix="/skills", tags=["skills"])
router.include_router(agent.router, prefix="/agent", tags=["agent"])
router.include_router(messages.router, prefix="/messages", tags=["messages"])
router.include_router(conversations.router, prefix="/conversations", tags=["conversations"])
router.include_router(config.router, prefix="/config", tags=["config"])
