from redbot.core.bot import Red

from .quote import Quote

async def setup(bot: Red):
    await bot.add_cog(Quote(bot))
