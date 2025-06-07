import textwrap
from io import BytesIO

import discord
from PIL import Image, ImageDraw, ImageFont
from redbot.core import commands


class Quote(commands.Cog):
    """Create a stylized quote image from a replied message."""

    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    async def quote(self, ctx: commands.Context):
        """Quote the replied message as an image."""
        if not ctx.message.reference or not isinstance(ctx.message.reference.resolved, discord.Message):
            return await ctx.send("Please reply to a message to quote it.")

        message: discord.Message = ctx.message.reference.resolved
        author = message.author
        avatar_asset = author.display_avatar.replace(size=128)
        avatar_bytes = await avatar_asset.read()
        avatar_img = Image.open(BytesIO(avatar_bytes)).convert("RGBA").resize((128, 128))

        text = f"\u201c{message.content}\u201d"
        font = ImageFont.load_default()
        wrapped = textwrap.wrap(text, width=40)
        line_height = font.getbbox("A")[3] + 4
        text_height = line_height * len(wrapped)
        width = 600
        height = max(150, text_height + 40)
        img = Image.new("RGBA", (width, height), "white")
        draw = ImageDraw.Draw(img)

        text_x = 150
        text_y = (height - text_height) // 2
        for line in wrapped:
            draw.text((text_x, text_y), line, font=font, fill="black")
            text_y += line_height

        mask = avatar_img.split()[3]
        img.paste(avatar_img, (10, (height - 128) // 2), mask)

        buffer = BytesIO()
        img.save(buffer, format="PNG")
        buffer.seek(0)

        file = discord.File(fp=buffer, filename="quote.png")
        await ctx.send(file=file)
