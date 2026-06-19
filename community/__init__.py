from .community import Community

__red_end_user_data_statement__ = (
    "This cog stores Discord user IDs together with recognition data: message "
    "IDs and reaction counts for starred messages, high-five (reputation) "
    "counts, and the calendar dates a member was active. No message content is "
    "stored. A user's data is removed on a Red data-deletion request."
)


async def setup(bot):
    await bot.add_cog(Community(bot))
