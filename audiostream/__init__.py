from .audiostream import AudioStream

__red_end_user_data_statement__ = (
    "This cog does not persistently store any Discord user data."
)


async def setup(bot):
    await bot.add_cog(AudioStream(bot))
