from .casefiles import CaseFiles

__red_end_user_data_statement__ = (
    "This cog stores Discord user IDs together with the content of messages the "
    "admin stamps as confirmed findings, plus the points and rank each user has "
    "earned. Tape images submitted with a case are stored in the cog's data "
    "folder. A user's stamped contributions are removed on a Red data-deletion "
    "request."
)


async def setup(bot):
    await bot.add_cog(CaseFiles(bot))
