# FeedbackBot by timraay

import asyncio
import discord
from discord.ext import commands
from datetime import datetime
from pathlib import Path
import os

from utils import get_config

intents = discord.Intents.all()

command_prefix = get_config()['bot']['CommandPrefix']

bot = commands.Bot(intents=intents, command_prefix=command_prefix, case_insensitive=True)
bot.remove_command('help')


@bot.check
def is_in_guild(ctx):
    return ctx.guild is not None


@bot.group(invoke_without_command=True, aliases=['cog'])
@commands.is_owner()
async def module(ctx):
    await ctx.send(f"**Available Operations**\n{ctx.prefix}cog reload [cog]\n{ctx.prefix}cog enable <cog>\n{ctx.prefix}cog disable <cog>\n{ctx.prefix}cog info <cog>")

@module.command(aliases=["load"])
@commands.is_owner()
async def enable(ctx, cog: str):
    """ Enable a cog """
    cog = cog.lower()
    if os.path.exists(Path(f"./cogs/{cog}.py")):
        await bot.load_extension(f"cogs.{cog}")
        await ctx.send(f"Enabled {cog}")
    else:
        await ctx.send(f"{cog} doesn't exist")

@module.command(aliases=["unload"])
@commands.is_owner()
async def disable(ctx, cog: str):
    """ Disable a cog """
    cog = cog.lower()
    if os.path.exists(Path(f"./cogs/{cog}.py")):
        await bot.unload_extension(f"cogs.{cog}")
        await ctx.send(f"Disabled {cog}")
    else:
        await ctx.send(f"{cog} doesn't exist")

@module.command()
@commands.is_owner()
async def reload(ctx, cog: str = None):
    """ Reload cogs """

    async def reload_cog(ctx, cog):
        """ Reloads a cog """
        try:
            await bot.reload_extension(f"cogs.{cog}")
            await ctx.send(f"Reloaded {cog}")
        except Exception as e:
            await ctx.send(f"Couldn't reload {cog}, " + str(e))

    if not cog:
        for cog in os.listdir(Path("./cogs")):
            if cog.endswith(".py"):
                cog = cog.replace(".py", "")
                await reload_cog(ctx, cog)
    else:
        if os.path.exists(Path(f"./cogs/{cog}.py")):
            await reload_cog(ctx, cog)
        else:
            await ctx.send(f"{cog} doesn't exist")

@module.command(aliases=["list"])
@commands.is_owner()
async def info(ctx, cog: str = None):
    """ List cogs' commands and events """

    if cog:
        # A single cog
        cog = cog.lower()
        if os.path.exists(Path(f"./cogs/{cog}.py")):
            cog = bot.get_cog(cog)
            if not cog:
                await ctx.send(f"{cog} is not a module")
            else:
                commands_list = [command.name for command in cog.get_commands()]
                events_list = [listener.name for listener in cog.get_listeners()]

                if not commands_list: commands = "None"
                else: commands = ", ".join(commands_list)

                if not events_list: events = "None"
                else: events = ", ".join(events_list)

                embed=discord.Embed(title=f"Module \"{cog.qualified_name}\"")
                embed.add_field(name=f"Commands ({str(len(commands_list))})", value=commands, inline=False)
                embed.add_field(name=f"Events ({str(len(events_list))})", value=events, inline=False)

                await ctx.send(embed=embed)
        else:
            await ctx.send(f"{cog} doesn't exist")
    
    else:
        # All cogs
        embed = discord.Embed(title="All modules")
        for cog in os.listdir(Path("./cogs")):
            if cog.endswith(".py"):
                cog = cog.replace(".py", "")
                cog = bot.get_cog(cog)
                if cog:
                    commands_list = cog.get_commands()
                    events_list = cog.get_listeners()

                    embed.add_field(name=cog.qualified_name, value=f"{str(len(commands_list))} commands & {str(len(events_list))} events", inline=False)
        await ctx.send(embed=embed)

async def setup_hook():
    for cog in os.listdir(Path("./cogs")):
        if cog.endswith(".py"):
            try:
                cog = f"cogs.{cog.replace('.py', '')}"
                await bot.load_extension(cog)
            except Exception as e:
                print(f"{cog} can not be loaded:")
                raise e
    print('Loaded all cogs')

    try:
        await asyncio.wait_for(bot.tree.sync(), timeout=5)
        print('Synced app commands')
    except asyncio.TimeoutError:
        print("Didn't sync app commands. This was likely last done recently, resulting in rate limits.")

    print("\nLaunched " + bot.user.name + " on " + str(datetime.now()))
    print("ID: " + str(bot.user.id))
bot.setup_hook = setup_hook

# Run the bot
token = get_config()['bot']['Token']
bot.run(token)