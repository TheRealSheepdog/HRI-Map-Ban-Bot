import discord
from discord.ext import commands

from datetime import datetime, timezone
from random import randint
from enum import StrEnum, auto
import re

from typing import Dict, List

from lib.vote import MapVote, MAPS, Team, Faction, Action, MapState, MiddleGroundVote
from lib.streams import Stream
from utils import get_config, unpack_cfg_list

class MiddleGroundMethod(StrEnum):
    always=auto()
    never=auto()
    vote=auto()
    regioned=auto()

MIDDLEGROUND_METHOD: MiddleGroundMethod = MiddleGroundMethod(get_config().get("behavior", "MiddleGroundMethod", fallback=MiddleGroundMethod.never))
MIDDLEGROUND_REGIONS = {
    role: region
    for region, role in [
        (region, role)
        for region, roles in get_config()["behavior.regions"].items()
        for role in unpack_cfg_list(roles)
    ]
}
MIDDLEGROUND_MATCHUPS = {
    region: set(MIDDLEGROUND_REGIONS.values() if regions.strip() == "*" else unpack_cfg_list(regions))
    for region, regions in get_config()["behavior.middlegrounds"].items()
}
MIDDLEGROUND_DEFAULT_VOTE_PROGRESS = {
    MiddleGroundMethod.always: "6101,6202", # "Yes" and "Skipped"
    MiddleGroundMethod.never: "6100,6200", # "No" and "No"
    MiddleGroundMethod.vote: "",
    MiddleGroundMethod.regioned: "6102,6202", # "Skipped" and "Skipped"
}[MIDDLEGROUND_METHOD]

print("Middleground method:", MIDDLEGROUND_METHOD)
print("Regions:", MIDDLEGROUND_REGIONS)
print("Matchups:", MIDDLEGROUND_MATCHUPS)

import sqlite3
db = sqlite3.connect('seasonal.db')
cur = db.cursor()

cur.execute("""CREATE TABLE IF NOT EXISTS "channels" (
	"creation_time"	TEXT,
	"guild_id"	INTEGER,
	"channel_id"	INTEGER,
	"message_id"	INTEGER,
	"title"	TEXT,
	"desc"	TEXT,
	"match_start"	TEXT,
	"map"	TEXT,
	"team1"	TEXT,
	"team2"	TEXT,
	"banner_url"	TEXT,
	"has_vote"	INTEGER,
	"has_predictions"	INTEGER,
	"result"	TEXT,
	"vote_result"	TEXT,
	"vote_coinflip_option"	INTEGER,
	"vote_coinflip"	INTEGER,
	"vote_server_option"	INTEGER,
	"vote_server"	TEXT,
	"vote_first_ban"	INTEGER,
	"vote_progress"	TEXT,
	"predictions_team1"	TEXT,
	"predictions_team2"	TEXT,
	"predictions_team1_emoji"	TEXT,
	"predictions_team2_emoji"	TEXT,
	"stream_delay"	INTEGER,
	PRIMARY KEY("channel_id")
);""")
db.commit()

def get_all_channels(guild_id):
    cur.execute('SELECT channel_id FROM channels WHERE guild_id = ?', (guild_id,))
    res = cur.fetchall()
    return [MatchChannel(channel_id[0]) for channel_id in res]

def get_predictions(guild_id: int):
    cur.execute('SELECT predictions_team1, predictions_team2, result FROM channels WHERE guild_id = ? AND result IS NOT NULL', (guild_id,))

    results: Dict[int, List[int]] = dict()
    for t1_pred, t2_pred, result in cur.fetchall():
        t1_pred = [int(user_id) for user_id in t1_pred.split(',') if user_id]
        t2_pred = [int(user_id) for user_id in t2_pred.split(',') if user_id]

        match = re.match(r"(\d) *[-:] *(\d)", result)
        if not match:
            continue
        t1_score, t2_score = [int(score) for score in match.groups()]
        winner = t1_score > t2_score

        for won, preds in ((winner, t1_pred), (not winner, t2_pred)):
            for pred in preds:
                scores = results.setdefault(pred, [0, 0])
                if won:
                    scores[0] += 1
                else:
                    scores[1] += 1

    return results


class MatchChannel:
    def __init__(self, channel_id):
        cur.execute('SELECT * FROM channels WHERE channel_id = ?', (channel_id,))
        res = cur.fetchone()
        if not res: raise NotFound("There is no match attached to channel %s" % channel_id)

        (self.creation_time, self.guild_id, self.channel_id, self.message_id, self.title, self.desc, self.match_start,
        self.map, self.team1, self.team2, self.banner_url, self.has_vote, self.has_predictions, self.result, self.vote_result,
        self.vote_coinflip_option, self.vote_coinflip, self.vote_server_option, self.vote_server, self.vote_first_ban, self.vote_progress,
        self.predictions_team1, self.predictions_team2, self.predictions_team1_emoji, self.predictions_team2_emoji, self.stream_delay) = res

        self.creation_time = datetime.fromisoformat(self.creation_time) if self.creation_time else datetime.now()
        self.match_start = datetime.fromisoformat(self.match_start) if self.match_start else None
        self.has_vote = bool(self.has_vote)
        self.has_predictions = bool(self.has_predictions)

        self.vote = MapVote(team1=self.team1, team2=self.team2, data=self.vote_progress)

        self.predictions_team1 = self.predictions_team1.split(',') if self.predictions_team1 else []
        self.predictions_team2 = self.predictions_team2.split(',') if self.predictions_team2 else []

    @classmethod
    def new(cls, channel, title: str, desc: str, match_start: datetime = None, map=None, team1 = None, team2 = None, banner_url: str = None, has_vote: bool = False, has_predictions: bool = False, result: str = None):
        creation_time = datetime.now()
        channel_id = channel.id
        guild_id = channel.guild.id
        if match_start and not match_start.tzinfo:
            raise ValueError('match_start should be an aware Datetime object, not naïve')
        message_id = 0
        vote_result = None
        vote_coinflip_option = 0
        vote_coinflip = None
        vote_server_option = 0
        vote_server = None
        vote_first_ban = None
        vote_progress = MIDDLEGROUND_DEFAULT_VOTE_PROGRESS
        predictions_team1 = ''
        predictions_team2 = ''
        predictions_team1_emoji = get_config()['visuals']['DefaultTeam1Emoji']
        predictions_team2_emoji = get_config()['visuals']['DefaultTeam2Emoji']
        stream_delay = 0
        cur.execute(
            "INSERT INTO channels VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (creation_time, guild_id, channel_id, message_id, title, desc, match_start, map, team1, team2, banner_url, int(has_vote), int(has_predictions), result,
            vote_result, vote_coinflip_option, vote_coinflip, vote_server_option, vote_server, vote_first_ban, vote_progress,
            predictions_team1, predictions_team2, predictions_team1_emoji, predictions_team2_emoji, stream_delay)
        )
        db.commit()
        return cls(channel_id)

    def save(self):
        self.vote_progress = ','.join(self.vote.progress)
        cur.execute("""UPDATE channels SET
        creation_time = ?, message_id = ?, title = ?, desc = ?, match_start = ?, map = ?, team1 = ?, team2 = ?,
        banner_url = ?, has_vote = ?, has_predictions = ?, result = ?, vote_result = ?, vote_coinflip_option = ?,
        vote_coinflip = ?, vote_server_option = ?, vote_server = ?, vote_first_ban = ?, vote_progress = ?, predictions_team1 = ?,
        predictions_team2 = ?, predictions_team1_emoji = ?, predictions_team2_emoji = ?, stream_delay = ? WHERE channel_id = ?""",
        (self.creation_time.isoformat(), self.message_id, self.title, self.desc, self.match_start.isoformat() if isinstance(self.match_start, datetime) else None,
        self.map, self.team1, self.team2, self.banner_url, int(self.has_vote), int(self.has_predictions), self.result,
        self.vote_result, self.vote_coinflip_option, self.vote_coinflip, self.vote_server_option, self.vote_server, self.vote_first_ban, self.vote_progress,
        ','.join(self.predictions_team1), ','.join(self.predictions_team2), self.predictions_team1_emoji, self.predictions_team2_emoji,
        self.stream_delay, self.channel_id))
        db.commit()

    def delete(self):
        cur.execute("""DELETE FROM channels WHERE channel_id = ?""", (self.channel_id,))
        db.commit()
        for stream in self.get_streams():
            stream.delete()

    async def get_channel(self, ctx):
        try: return await commands.TextChannelConverter().convert(ctx, self.channel_id)
        except commands.BadArgument: return None
    def get_team1(self, ctx, mention=True):
        try: team = int(self.team1)
        except: team = str(self.team1)
        
        result = ctx.guild.get_role(team)
        if result:
            if result.name.endswith('*'):
                try: result = [role for role in ctx.guild.roles if role.name == result.name[:-1]][0]
                except IndexError: pass

            if mention: return result.mention
            else: return result.name
        else:
            team = str(team)
            return team[:-1] if team.endswith('*') else team
    def get_team2(self, ctx, mention=True):
        try: team = int(self.team2)
        except: team = str(self.team2)
        
        result = ctx.guild.get_role(team)
        if result:
            if result.name.endswith('*'):
                try: result = [role for role in ctx.guild.roles if role.name == result.name[:-1]][0]
                except IndexError: pass

            if mention: return result.mention
            else: return result.name
        else:
            team = str(team)
            return team[:-1] if team.endswith('*') else team
    def get_streams(self):
        return Stream.in_channel(self.channel_id)

    async def to_payload(self, ctx, render_images=False, delay_predictions=False):
        data = {
            'embeds': []
        }
        data['embeds'].append(await self.to_match_embed(ctx))

        if self.has_vote:
            embed, file = await self.to_vote_embed(ctx, render_images)
            data['embeds'].append(embed)
            if render_images:
                data['file'] = file

        if self.should_show_predictions():
            embed = await self.to_predictions_embed(ctx, delay_predictions)
            data['embeds'].append(embed)

        return data
    async def to_match_embed(self, ctx):
        if not self.has_vote:
            embed = discord.Embed(title=self.title, description=self.desc if self.desc else None)
            embed.add_field(inline=True, name='🔵 Team 1 (Allies)', value=self.get_team1(ctx))
            embed.add_field(inline=True, name='🔴 Team 2 (Axis)', value=self.get_team2(ctx))
            embed.add_field(inline=True, name='🗺️ Map', value=str(self.map) if self.map else "Unknown")

        else:
            embed = discord.Embed(title=self.title, description=self.desc if self.desc else None)
            team1 = self.get_team1(ctx)
            team2 = self.get_team2(ctx)
            if not self.vote_result:
                embed.add_field(inline=True, name='🔵 Team 1', value=team1)
                embed.add_field(inline=True, name='🔴 Team 2', value=team2)
            else:
                embed.add_field(inline=True, name=f'🔵 Team 1 ({"Axis" if self.vote_result.startswith("!") else "Allies"})', value=team1)
                embed.add_field(inline=True, name=f'🔴 Team 2 ({"Allies" if self.vote_result.startswith("!") else "Axis"})', value=team2)
            embed.add_field(inline=True, name='🗺️ Map', value=str(self.map) if self.vote_result else "Ban phase ongoing")

        if not self.match_start:
            embed.add_field(inline=True, name='📅 Match Start', value='Unknown')
        else:
            embed.add_field(inline=True, name='📅 Match Start', value=f'<t:{int(self.match_start.timestamp())}:F>')

        if self.result:
            embed.add_field(inline=True, name='🎯 Result', value=f"||{str(self.result)}||")

        streams = self.get_streams()
        if streams:
            embed.add_field(
                name=f'🎙️ Streamers (+{self.stream_delay} min. delay)' if self.stream_delay else '🎙️ Streamers',
                value="\n".join([stream.to_text() for stream in streams]),
                inline=False,
            )

        if self.banner_url:
            embed.set_image(url=self.banner_url)

        return embed
    async def to_vote_embed(self, ctx, render_images=False):
        # Map vote embed
        embed = discord.Embed(title='Map Ban Phase')

        is_middleground = self.use_middleground_server()

        if (is_middleground is not None) and (not self.vote_coinflip):
            if self.vote_coinflip_option == 0:
                self.vote_coinflip = randint(1, 2)
            elif self.vote_coinflip_option in [1, 2]:
                self.vote_coinflip = self.vote_coinflip_option
            self.vote.add_progress(team=self.vote_coinflip, action=4, faction=0, map_index=0)
            self.save()
        
        team1 = self.get_team1(ctx)
        team2 = self.get_team2(ctx)
        if self.vote_coinflip == 1:
            coinflip_winner = team1
        elif self.vote_coinflip == 2:
            coinflip_winner = team2
        else:
            coinflip_winner = 'TBD'

        if self.vote_first_ban:
            first_ban = (team1, team2)[self.vote_first_ban-1]
        else:
            first_ban = 'TBD'
        
        server_host = 'Unknown'
        if not self.vote_server:
            if not self.vote_first_ban:
                server_host = 'TBD'
            elif self.vote_server_option == 0:
                self.vote_server = '2' if self.vote_first_ban == 1 else '1'
            elif self.vote_server_option in [1, 2]:
                self.vote_server = str(self.vote_server_option)
            self.save()

        if self.vote_server == '1':
            server_host = team1
        elif self.vote_server == '2':
            server_host = team2
        elif self.vote_server:
            server_host = self.vote_server

        if is_middleground is True:
            if self.vote_first_ban:
                final_ban = team2 if (coinflip_winner == first_ban) == (coinflip_winner == team1) else team1
            else:
                final_ban = 'TBD'
            embed.add_field(inline=True, name='🎲 Coinflip Winner', value=coinflip_winner)
            embed.add_field(inline=True, name='🔨 Extra Ban', value=first_ban)
            embed.add_field(inline=True, name='🔨 Final Ban', value=final_ban)
        elif is_middleground is False:
            embed.add_field(inline=True, name='🎲 Coinflip Winner', value=coinflip_winner)
            embed.add_field(inline=True, name='🔨 Extra Ban', value=first_ban)
            embed.add_field(inline=True, name='💻 Server Host', value=server_host)

        embed.description = self.parse_progress(self.vote_progress, self.get_team1(ctx), self.get_team2(ctx))

        if not self.vote_result:
            team, turns = self.get_turn()
            team_mention = self.get_team1(ctx) if team == 1 else self.get_team2(ctx)
            if self.vote_first_ban:
                embed.description += f"\n\nYour time to ban, {team_mention}! Type map + faction down below.\nExample: `{MAPS[0]} Allies`."
                if turns > 1:
                    embed.description += f" You can ban **{turns} maps!**"
            elif is_middleground is True:
                embed.description += f'\n\n{team_mention}, do you choose to get an extra ban, or to have the final ban? Type `extra` or `final` below.'
            elif is_middleground is False:
                embed.description += f'\n\n{team_mention}, do you choose to get an extra ban, or to host the server? Type `ban` or `host` below.'
            else:
                teams = []
                if self.vote.mg_vote[Team.One] is None:
                    teams.append(self.get_team1(ctx))
                if self.vote.mg_vote[Team.Two] is None:
                    teams.append(self.get_team2(ctx))
                teams = " & ".join(teams)
                embed.description += (
                    f'\n\n{teams}, decide whether you want to use middleground servers or not. Type `yes` or `no` below.'
                    '\n\nIf both teams accept, the coinflip winner will choose between having an extra'
                    ' or the final ban, instead of host or ban advantage.'
                )

        self.vote.names[Team.One] = self.get_team1(ctx, mention=False)
        self.vote.names[Team.Two] = self.get_team2(ctx, mention=False)

        if render_images:
            img = self.vote.render()
            file = discord.File(img, filename='output.png')
        else:
            file = None
        embed.set_image(url='attachment://output.png')

        return embed, file
    async def to_predictions_embed(self, ctx, delay_predictions=False):
        # Predictions
        embed = discord.Embed(title='Match Predictions')
        embed.description = f'_ _\n{self.predictions_team1_emoji} {self.get_team1(ctx)} (**{len(self.predictions_team1)}** votes)\n{self.predictions_team2_emoji} {self.get_team2(ctx)} (**{len(self.predictions_team2)}** votes)'

        if not self.should_have_predictions():
            embed.set_footer(text='Voting has ended')
        elif self.match_start:
            if delay_predictions:
                embed.set_footer(text="Predictions will be available\nin approx. 10 minutes")
            else:
                embed.set_footer(text='Voting ends at ' + self.match_start.strftime('%A %B %d, %H:%M %p UTC').replace(" 0", " "))
        return embed
    
    def should_have_predictions(self):
        return (
            self.should_show_predictions()
            and not self.result
            and (
                not self.match_start
                or datetime.now(timezone.utc) < self.match_start
            )
        )

    def should_show_predictions(self):
        return self.has_predictions and not (self.has_vote and not self.vote_result)

    def get_prediction_of_user(self, user_id):
        user_id = str(user_id)
        if user_id in self.predictions_team1:
            return 1
        elif user_id in self.predictions_team2:
            return 2
        else:
            return None

    def get_turn(self):
        if self.use_middleground_server() is True:
            num_bans = (len(self.vote.progress) // 2) - 2

            if num_bans < 0:
                return (Team(self.vote_coinflip or 1), 0)

            if (len(MAPS) % 2) == 1:
                choices_left = len(MAPS) * 2
                if (choices_left - num_bans) <= 4:
                    if (self.vote_first_ban == Team.One) == (num_bans % 2 == 0):
                        return (Team.Two, 1)
                    else:
                        return (Team.One, 1)

            turns_left = 2 if (num_bans % 2 == 0) else 1
            if (((num_bans // 2) % 2) == 0) == (self.vote_first_ban == Team.One):
                return (Team.One, turns_left)
            else:
                return (Team.Two, turns_left)
        else:
            return (self.vote.get_last_team(), 1)
    
    def use_middleground_server(self):
        if self.vote:
            t1_vote = self.vote.mg_vote[Team.One]
            t2_vote = self.vote.mg_vote[Team.Two]
            if (
                (t1_vote == MiddleGroundVote.No) or
                (t2_vote == MiddleGroundVote.No)
            ):
                return False
            elif (
                (t1_vote == MiddleGroundVote.Yes) and
                (t2_vote == MiddleGroundVote.Yes or t2_vote == MiddleGroundVote.Skipped)
            ):
                return True
            elif (
                (t1_vote == MiddleGroundVote.Skipped) and
                (t2_vote == MiddleGroundVote.Skipped)
            ):
                region1 = MIDDLEGROUND_REGIONS.get(self.team1)
                region2 = MIDDLEGROUND_REGIONS.get(self.team2)
                if region1 and region2:
                    return region2 in MIDDLEGROUND_MATCHUPS[region1]
                else:
                    return False
                
        return None

    def vote_middleground(self, team: Team, vote: MiddleGroundVote):
        self.vote.vote_middleground(team, vote)
        if self.use_middleground_server() is True:
            self.vote_server = "Middleground"
        self.save()
    def ban_map(self, team: Team, faction: Faction, map: str):
        team = Team(team)
        faction = Faction(faction)
        self.vote.ban(team, faction, map)
        if str(self.vote).count('0') == 2:
            for team, data in self.vote.maps.items():
                for faction, column in data.items():
                    for map, state in column.items():
                        if state == MapState.Available:
                            self.vote.final_pick(team=team, faction=faction, map=map)
                            if not self.vote_result:
                                if team.value == faction.value:
                                    self.vote_result = map
                                else:
                                    self.vote_result = '!' + map
                                self.map = map
                            break
        self.save()
    def undo(self, amount: int = 1):
        for i in range(amount):
            if not len(self.vote.progress) > 3:
                break
            del self.vote.progress[-2:]
        self.save()

    def parse_progress(self, progress, team1, team2):
        output = list()
        for item in progress.split(','):
            if item:
                action = self._parse_individual_progress(item, team1, team2)
                if action:
                    output.append(action)

        output = "\n".join(output)
        
        for team in (team1, team2):
            esc_team = re.escape(team)
            output = re.sub(
                esc_team + r" banned (\*\*.+ (?:Allies|Axis)\*\*).\n" + esc_team + r" banned (\*\*.+ (?:Allies|Axis)\*\*).",
                team + r" banned \1 and \2.",
                output
            )
        output = re.sub(
            r".+ wants to use a middleground server.\n.+ wants to use a middleground server.",
            r"Both teams decided a middleground server will be used.",
            output,
            count=1
        )

        return output
    def _parse_individual_progress(self, progress, team1, team2):
        data = self.vote._translate_action(progress)

        if data['team'] == Team.One:
            data['team'] = team1
            data['other'] = team2
        elif data['team'] == Team.Two:
            data['team'] = team2
            data['other'] = team1
        
        if data['action'] == Action.BannedMap:
            action = "{team} banned **{map} {faction}**.".format(**data)
        elif data['action'] == Action.FinalPick:
            action = "{map} {faction} is final pick for {team}.".format(**data)
        elif data['action'] == Action.WonCoinflip:
            action = "{team} won the coinflip.".format(**data)
        elif data['action'] == Action.HasFirstBan:
            if self.use_middleground_server() is True:
                if self.vote_coinflip == self.vote_first_ban:
                    action = "{team} chooses an extra ban. {other} gets the final ban.".format(**data)
                else:
                    action = "{other} gives {team} an extra ban, and will be getting the final ban.".format(**data)
            else:
                if self.vote_coinflip == self.vote_first_ban:
                    action = "{team} chooses to ban first. {other} may host the server.".format(**data)
                else:
                    action = "{other} lets {team} ban first, and will be hosting the server.".format(**data)
        elif data['action'] == Action.ChoseMiddleGround:
            if MIDDLEGROUND_METHOD != MiddleGroundMethod.vote:
                action = None
            else:
                vote = MiddleGroundVote(data['map_index'])
                if vote == MiddleGroundVote.Yes:
                    action = "{team} wants to use a middleground server.".format(**data)
                elif vote == MiddleGroundVote.No:
                    action = "{team} decided no middleground server will be used.".format(**data)
                else:
                    action = None
        else:
            action = None
        return action


class NotFound(Exception):
    """Raised when a database row couldn't be found"""
    pass


if __name__ == '__main__':
    channel = MatchChannel(1)
