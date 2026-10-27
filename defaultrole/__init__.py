from .defaultrole import DefaultRole

__red_end_user_data_statement__ = "This cog stores only server settings, not user data."


async def setup(bot):
    await bot.add_cog(DefaultRole(bot))
