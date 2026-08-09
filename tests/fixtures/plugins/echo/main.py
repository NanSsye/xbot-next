from xbot.plugins.base import PluginBase


class EchoPlugin(PluginBase):
    name = "echo"
    version = "0.1.0"

    async def on_message(self, message, ctx):
        return None

