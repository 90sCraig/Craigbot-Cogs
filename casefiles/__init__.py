from .casefiles import CaseFiles

__red_end_user_data_statement__ = (
    "This cog stores Discord user IDs together with the case-identification "
    "leads (message text) those users post in the case channel, plus a count "
    "of cases each user has helped solve. Tape images submitted to the bot are "
    "stored in the cog's data folder. A user's leads and solve credit are "
    "removed on a Red data-deletion request."
)


async def setup(bot):
    await bot.add_cog(CaseFiles(bot))
