from .spotlight import Spotlight

__red_end_user_data_statement__ = (
    "This cog stores the content and metadata of messages that server administrators "
    "add to Spotlight, including the original author's Discord user ID and display "
    "name. Deleting that user's data removes their active Spotlights."
)


async def setup(bot):
    await bot.add_cog(Spotlight(bot))
