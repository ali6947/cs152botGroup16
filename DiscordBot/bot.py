# bot.py
import discord
from discord.ext import commands
import os
import json
import logging
import re
import requests
from report import Report
import pdb

# Set up logging to the console
logger = logging.getLogger('discord')
logger.setLevel(logging.DEBUG)
handler = logging.FileHandler(filename='discord.log', encoding='utf-8', mode='w')
handler.setFormatter(logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s'))
logger.addHandler(handler)

# There should be a file called 'tokens.json' inside the same folder as this file
token_path = 'tokens.json'
if not os.path.isfile(token_path):
    raise Exception(f"{token_path} not found!")
with open(token_path) as f:
    # If you get an error here, it means your token is formatted incorrectly. Did you put it in quotes?
    tokens = json.load(f)
    discord_token = tokens['discord']



class ModBot(discord.Client):
    def __init__(self): 
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix='.', intents=intents)
        self.group_num = None
        self.mod_channels = {} # Map from guild to the mod channel id for that guild
        self.reports = {} # Map from user IDs to the state of their report
        self.report_against={} # key is user_id , value is an integet telling number of reports
        self.false_report_count={}
        self.all_reports={} # mapping report ID to report object
        self.current_rep_id=0
        
        

    async def on_ready(self):
        print(f'{self.user.name} has connected to Discord! It is these guilds:')
        for guild in self.guilds:
            print(f' - {guild.name}')
        print('Press Ctrl-C to quit.')

        # Parse the group number out of the bot's name
        match = re.search('[gG]roup (\d+) [bB]ot', self.user.name)
        if match:
            self.group_num = match.group(1)
        else:
            raise Exception("Group number not found in bot's name. Name format should be \"Group # Bot\".")

        # Find the mod channel in each guild that this bot should report to
        for guild in self.guilds:
            for channel in guild.text_channels:
                if channel.name == f'group-{self.group_num}-mod':
                    self.mod_channels[guild.id] = channel


        for guild in self.guilds:
            for channel in guild.text_channels:
                if channel.name == f'group-16-mod':
                    self.my_mod_channel = channel
                    break

    async def on_message(self, message):
        '''
        This function is called whenever a message is sent in a channel that the bot can see (including DMs). 
        Currently the bot is configured to only handle messages that are sent over DMs or in your group's "group-#" channel. 
        '''
        # Ignore messages from the bot 
        if message.author.id == self.user.id:
            return

        # Check if this message was sent in a server ("guild") or if it's a DM
        if message.guild:
            await self.handle_channel_message(message)
        else:
            await self.handle_dm(message)

    async def handle_dm(self, message):
        # Handle a help message
        if message.content == Report.HELP_KEYWORD:
            reply =  "Use the `report` command to begin the reporting process.\n"
            reply += "Use the `cancel` command to cancel the report process.\n"
            await message.channel.send(reply)
            return


        author_id = message.author.id
        responses = []

        # Only respond to messages if they're part of a reporting flow
        if author_id not in self.reports and not message.content.startswith(Report.START_KEYWORD):
            return

        # If we don't currently have an active report for this user, add one
        if author_id not in self.reports:
            self.reports[author_id] = Report(self,message.author)

        # Let the report class handle this message; forward all the messages it returns to uss
        responses = await self.reports[author_id].handle_message(message)
        for r in responses:
            await message.channel.send(r)

        # If the report is complete or cancelled, remove it from our map
        if self.reports[author_id].report_complete():
            rep=self.reports[author_id]
            id_num=self.current_rep_id
            self.current_rep_id+=1
            self.all_reports[id_num]=rep

            if rep.forward_to_mod():
                author_name=message.author.name
                abuser=rep.message.author.name
                abuser_id=rep.message.author.id
                self.report_against[abuser_id]=self.report_against.get(abuser_id,0)+1
                rep_reason=str(rep.report_reason)
                decision_to_block='yes' if rep.did_block else 'no'
                relation_to_abuser='Not Applicable' if rep.bully_type is None else str(rep.bully_type)
                abuser_history = []
                try:
                    offensive_msg_body=rep.message.content
                except:
                    offensive_msg_body=rep.deleted_msg_content

                async for hs in rep.message.channel.history(limit=50):
                    if hs.author.id==abuser_id:
                        abuser_history.append(hs)
                        if len(abuser_history)>=10:
                            break
               
                await self.fwd_report_text(id_num,author_name,author_id,abuser,abuser_id,decision_to_block,rep_reason,relation_to_abuser,abuser_history,self.report_against[abuser_id],offensive_msg_body)
            
            self.reports.pop(author_id)

    async def handle_channel_message(self, message):

        if message.channel.name == f'group-{self.group_num}-mod' and message.content.startswith('.'):
            cmd=message.content.split(" ")[0][1:] # to remove dot
            mod_channel = self.mod_channels[message.guild.id]
            if cmd=='false_report':
                try:
                    arg=int(message.content.split(" ")[1])
                except:
                    await mod_channel.send('Please recheck argument')
                else:
                    try:
                        rep_user=self.all_reports[arg].report_author
                    except:
                        await mod_channel.send('Report with this ID was not found')
                    else:
                        self.false_report_count[rep_user.id]=self.false_report_count.get(rep_user.id,0)+1
                        user_to_dm = await self.fetch_user(rep_user.id)
                        await user_to_dm.send("The message you reported was found to be within our guidelines and no action is taken")

            elif cmd in ['temp_ban','ban']:
                try:
                    arg=int(message.content.split(" ")[1])
                except:
                    await mod_channel.send('Please recheck argument')
                else:
                    try:
                        user_to_dm = await self.fetch_user(self.all_reports[arg].message.author.id)
                    except:
                        await mod_channel.send('Report with this ID was not found')
                    else:
                        if cmd=='temp_ban':
                            await user_to_dm.send("Your account has been suspended for 6 months from the platform for sending message that do not adhere to community guidelines.\nPlease reach out to customer service if you feel this is a mistake.")
                        else:
                            await user_to_dm.send("Your account has been suspended indefinitely from the platform for sending message that do not adhere to community guidelines.\nPlease reach out to customer service if you feel this is a mistake.")



        # Only handle messages sent in the "group-#" channel
        if not message.channel.name == f'group-{self.group_num}':
            return

        # Forward the message to the mod channel
        mod_channel = self.mod_channels[message.guild.id]
        await mod_channel.send(f'Forwarded message:\n{message.author.name}: "{message.content}"')
        scores = self.eval_text(message.content)
        await mod_channel.send(self.code_format(scores))


    async def fwd_report_text(self,rep_id,author_name,author_id,abuser_name,abuser_id,decision_to_block,rep_reason,relation_to_abuser,abuser_history,num_reports,offensive_msg_body):
        msg=f'Report ID: {rep_id}\n'
        msg+=f'Report by {author_id} (username: {author_name}) against {abuser_id} (username: {abuser_name})\n'
        msg+=f'Previous false reports by author: {self.false_report_count.get(author_id,0)}\n'
        msg+=f'Content of message: {offensive_msg_body}\n'
        msg+=f'Number of reports made against abuser: {num_reports}\n'
        msg+=f'Reaon for Report: {rep_reason}\n'
        msg+=f'Relation to abuser, if applicable: {relation_to_abuser}\n'
        msg+=f'Was user blocked? {decision_to_block}\n'
        msg+=f'Last few abuser\'s messages to victim:\n'
        for idx,item in enumerate(abuser_history):
            msg+=f'{idx+1}): {item.content}\n'

        await self.my_mod_channel.send(f'****NEW REPORT****\n{msg}')

    
    def eval_text(self, message):
        ''''
        TODO: Once you know how you want to evaluate messages in your channel, 
        insert your code here! This will primarily be used in Milestone 3. 
        '''
        return message

    
    def code_format(self, text):
        ''''
        TODO: Once you know how you want to show that a message has been 
        evaluated, insert your code here for formatting the string to be 
        shown in the mod channel. 
        '''
        return "Evaluated: '" + text+ "'"



client = ModBot()

client.run(discord_token)