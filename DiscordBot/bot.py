# bot.py
import discord
from discord.ext import commands
import os
import json
import logging
import re
import requests
from report import Report, AutomaticReport
import pdb
import openai
import pickle
from copy import deepcopy
from googleapiclient import discovery

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
    perspective_token=tokens['perspective']



class ModBot(discord.Client):
    def __init__(self): 
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix='.', intents=intents)
        self.group_num = None
        self.mod_channels = {} # Map from guild to the mod channel id for that guild
        self.reports = {} # Map from user IDs to the state of their report
        self.report_against={} # key is user_id , value is an integet telling number of reports
        self.false_report_count={}
        self.all_reports={} # mapping report ID to report object
        self.current_rep_id=0
        self.last_message_sent =None
        self.user_ML_reports={} #user ID to list of wrongful messages sent by user as flagged by ML system
        self.perm_banned_user=set()
        self.temp_banned_user=set()

        self.DM_owner=None
        self.automatic_report_question=False #used when the automatic flagging starts a report
        self.automatic_reported_message=None # message object for the wrongful message flagged above
        self.msg_by_bot=None # the censored message the bot sent
        self.all_automatic_report={} #mapping automatic report ID to object
        self.current_auto_report_id=0

        with open('openai_org.txt','r') as f:
            openai.organization=(f.read().strip())

        with open('openai_key.txt','r') as f:
            openai.api_key=(f.read().strip())
        self.model="gpt-4"

        with open('DiscordBot/LRmodel_pipe_cyberbullying.pkl','rb') as f:
            self.LR_pipe=pickle.load(f)

        self.misclassifications_file=open('misclassified_instances.txt','a+')

        self.perspective_token=perspective_token
        self.user_ML_reports_harras={} # key is  user ID, value if flagged harrasment messages

    def get_toxic_perspective_score(self,x,attr='TOXICITY'):

      client = discovery.build(
        "commentanalyzer",
        "v1alpha1",
        developerKey=self.perspective_token,
        discoveryServiceUrl="https://commentanalyzer.googleapis.com/$discovery/rest?version=v1alpha1",
        static_discovery=False,
      )

      analyze_request = {
        'comment': { 'text': x },
        'requestedAttributes': {attr: {}}
      }

      response = client.comments().analyze(body=analyze_request).execute()
      return response['attributeScores'][attr]['summaryScore']['value']


    def LR_classify_bullying(self,sent):
        output = self.LR_pipe.predict([sent])
        print(output)
        return list(output)


    def gpt4_classify_bullying(self,sent):
        response = openai.ChatCompletion.create(
            model=self.model,
            messages=[
            {"role": "system", "content": "You are a cyber bullying detection system. For each message, you should either output \"no cyber bullying detected\" or classify the detected cyber bullying into gender, religion, age or ethinicity. If you find the input to belong to multiple categories, give a comma separated list. If no category works but you feel it is cyber bullying, output \"other\""},
            {"role": "user", "content": "I love you"},
            {"role": "assistant", "content": "no cyber bullying detected"},
            {"role": "user", "content": "These Muslims girls should be killed already."},
            {"role": "assistant", "content": "religion, gender"},
            {"role": "user","content":sent}
            ]
            )

        output = response['choices'][0]['message']['content']
        classes_found=[]
        if "no cyber bullying" in output.lower():
            classes_found.append(0)
        if "gender" in output.lower():
            classes_found.append(1)
        if "religion" in output.lower():
            classes_found.append(2)
        if "age" in output.lower():
            classes_found.append(3)
        if "ethinicity" in output.lower():
            classes_found.append(4)
        if "other" in output.lower():
            classes_found.append(5)

        return classes_found

       

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

        for guild in self.guilds:
            for channel in guild.text_channels:
                if channel.name == f'group-16':
                    for member in channel.members:
                        if member.name=='alirehan':
                            self.DM_owner=member
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

    async def on_raw_reaction_add(self,payload):
        if not payload.guild_id:
            if self.last_message_sent is None:
                return
            if (payload.message_id)==self.last_message_sent.id:
                if payload.user_id in self.reports:
                    responses= await self.reports[payload.user_id].process_rxn(payload.emoji)
                    user_to_dm = await self.fetch_user(payload.user_id)
                    for r in responses:
                        self.last_message_sent = await user_to_dm.send(r)



    async def initiate_automatic_report(self,message):
        author_id = message.author.id
        if author_id not in self.reports:
            self.reports[author_id] = Report(self,message.author,True,self.automatic_reported_message,self.msg_by_bot)
            # responses = await self.reports[author_id].handle_message(message)

            # for r in responses:
            self.last_message_sent = await message.channel.send('Please tell how do you know the sender by choosing a number:\n1)Family member/relative\n2)Peer\n3)Stranger\n4)Prefer not to say')


    async def stop_automatic_report(self,message):
        self.last_message_sent = await message.channel.send("Please reach out in the future if you feel you are being bullied.")


    async def handle_dm(self, message):

        if self.automatic_report_question:
            
            if message.content.lower().startswith('y'):
                await self.initiate_automatic_report(message)
                self.automatic_report_question=False
                return            
            elif message.content.lower().startswith('n'):
                await self.stop_automatic_report(message)
                self.automatic_report_question=False
                return
            else:
                await message.channel.send('I did not get that. Please respond with yes/no')
                return
            
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
            self.last_message_sent = await message.channel.send(r)

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

    def get_report_type_id(self,report_body):
        entries=report_body.split('\n')
        if 'automatic' in entries[0].lower():
            autom=True
        elif 'report' in entries[0].lower():
            autom=False
        else:
            raise Exception
        rep_id=int(entries[1].split(' ')[-1].strip())
        return autom,rep_id


    async def handle_channel_message(self, message):

        if message.channel.name == f'group-{self.group_num}-mod' and message.reference is not None and message.content.startswith('.'):

            replied_message = await message.channel.fetch_message(message.reference.message_id)
            mod_channel = self.mod_channels[message.guild.id]

            try:
                autom,arg =  self.get_report_type_id(replied_message.content)
            except:
                await message.reply('Report in the message could not be parsed. Please check the message tagged')
                return

            cmd=message.content 

            if '1' in cmd :
                if not autom:
                    try:
                        rep_user=self.all_reports[arg].report_author
                    except:
                        await message.reply('Report with this ID was not found')
                    else:
                        self.false_report_count[rep_user.id]=self.false_report_count.get(rep_user.id,0)+1
                        user_to_dm = await self.fetch_user(rep_user.id)
                        await user_to_dm.send("The message you reported was found to be within our guidelines and no action is taken")

                else:
                    try:
                        report=self.all_automatic_report[arg]
                    except:
                        await message.reply('Automatic flagging report with this ID was not found')
                    else:
                        for x in report.bully_type:
                            self.user_ML_reports[report.message.author.id][x-1]-=1
                        self.misclassifications_file.write(report.message.content+'\n')
                        await message.reply('User statistics updated accordingly. Message stored for classifier improvement')

            elif '2' in cmd or '3' in cmd:
                    try:
                        if autom:
                            user_to_dm_id=self.all_automatic_report[arg].message.author.id
                            user_to_dm = await self.fetch_user(user_to_dm_id)
                        else:
                            user_to_dm_id=self.all_reports[arg].message.author.id
                            user_to_dm = await self.fetch_user(user_to_dm_id)
                    except:
                        await message.reply('Report with this ID was not found')
                    else:    
                        if '2' in cmd:
                            if user_to_dm_id in self.temp_banned_user:
                                await message.reply('User already temporarily banned')
                            elif user_to_dm_id in self.perm_banned_user:
                                await message.reply('User already permanently banned')
                            else:
                                self.temp_banned_user.add(user_to_dm_id)
                                await user_to_dm.send("Your account has been suspended for 6 months from the platform for sending messages that do not adhere to community guidelines.\nPlease reach out to customer service if you feel this is a mistake.")
                        else:
                            if user_to_dm_id in self.perm_banned_user:
                                await message.reply('User already permanently banned')
                            else:
                                if user_to_dm_id in self.temp_banned_user:
                                    self.temp_banned_user.remove(user_to_dm_id)
                                self.perm_banned_user.add(user_to_dm_id)
                                await user_to_dm.send("Your account has been suspended indefinitely from the platform for sending messages that do not adhere to community guidelines.\nPlease reach out to customer service if you feel this is a mistake.")
            else:
                await message.reply('Please recheck the command number')



        elif message.channel.name == f'group-{self.group_num}':
            # Forward the message to the mod channel


            mod_channel = self.mod_channels[message.guild.id]
            # await mod_channel.send(f'Forwarded message:\n{message.author.name}: "{message.content}"')
            scores = self.eval_text(message) #for cyberbullying
            if scores[0]:
                await mod_channel.send(self.code_format(scores[1],message))
                await self.censor_msg(message)
            else: # for harrasment
                harras_score=self.get_toxic_perspective_score(message.content)
                if harras_score>=0.5:
                    self.user_ML_reports_harras[message.author.id]=self.user_ML_reports_harras.get(message.author.id,0)+1
                    await mod_channel.send(self.code_format(None,message,2))
                    await self.censor_msg(message)



    async def censor_msg(self,message):
        msg_id1=await message.channel.send('||'+message.content+f'||\nThe above message by {message.author.name}  was blurred because it might have sensitive content')
        if not self.DM_owner.id in self.reports:
            await self.DM_owner.send('Are you being recently bullied or harrased?')
            self.automatic_report_question=True
            self.automatic_reported_message=message
            self.msg_by_bot=msg_id1
        await message.delete()



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
        msg+='Please reply to this option with a \'.\' followed by the appropriate action number:\n1)Falsify Report\n2)Temporarily ban abuser\n3)Permanently ban abuser'

        await self.my_mod_channel.send(f'****NEW REPORT****\n{msg}')

    
    def eval_text(self, message):
        ''''
        TODO: Once you know how you want to evaluate messages in your channel, 
        insert your code here! This will primarily be used in Milestone 3. 
        '''
        classi=self.gpt4_classify_bullying(message.content)
        if len(classi)==1 and classi[0]==0:
            return False,[]
        abuse_list=[x for x in classi if x!=0]
        if message.author.id not in self.user_ML_reports:
            self.user_ML_reports[message.author.id]=[0,0,0,0,0]
        for abuse in abuse_list:
            self.user_ML_reports[message.author.id][abuse-1]+=1
        return True,abuse_list

    def bully_mapper(self,x):
        if 1 ==x:
            return "gender"
        if  2 ==x:
            return "religion"
        if 3  ==x:
            return "age"
        if 4 ==x:
            return "ethinicity"
        if 5 ==x:
            return "miscellaneous"
    
    def code_format(self,bullying_types,message,main_reason=1):
        # main_reason=1 for cyberbullying , 2 for harrasment
        ''''
        TODO: Once you know how you want to show that a message has been 
        evaluated, insert your code here for formatting the string to be 
        shown in the mod channel. 
        '''
        self.all_automatic_report[self.current_auto_report_id]=AutomaticReport(message,bullying_types)
        msg='****NEW AUTOMATIC FLAGGING****\n'
        msg+=f'Report ID: {self.current_auto_report_id}\n'
        msg+=f'The following message by  {message.author.id} (username: {message.author.name}) was automatically flagged to contain ' 
        if main_reason==1:
            msg+='cyber bullying based on '
            bully_string=', '.join([self.bully_mapper(x) for x in bullying_types])
            msg+=bully_string+'.\n'
            msg+='Number of offender\'s flagged messages by category:\n'
            data=self.user_ML_reports.get(message.author.id,[0,0,0,0,0])
            for idx,entry in enumerate(data):
                msg+=f'{self.bully_mapper(idx+1)}: {entry}\n'
        elif main_reason==2:
            msg+='harrasment.\n'
            msg+=f'Number of previous messages flagged for harrasment:{self.user_ML_reports_harras.get(message.author.id,0)}\n'

        msg+=f'Number of user report against offender:{self.report_against.get(message.author.id,0)}\n'
        msg+='The body of the message is given below:\n'+message.content+'\n'
        msg+='Please reply to this option with a \'.\' followed by the appropriate action number:\n1)Falsify Report\n2)Temporarily ban abuser\n3)Permanently ban abuser'
        self.current_auto_report_id+=1
        return msg



client = ModBot()

client.run(discord_token)