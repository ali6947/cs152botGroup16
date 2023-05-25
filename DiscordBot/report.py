from enum import Enum, auto
import discord
import re

class State(Enum):
    REPORT_START = auto()
    AWAITING_MESSAGE = auto()
    MESSAGE_IDENTIFIED = auto()
    REPORT_COMPLETE = auto()
    REASON_ASKED=auto()
    BLOCK_ASKED=auto()
    SPAM_TYPE=auto()
    BULLY_TYPE=auto()
    ASK_DELETE=auto()


class ReportType(Enum):
    DONTLIKE=auto()
    SPAM=auto()
    BULLY=auto()
    SEXUAL_HARASS=auto()

class SpamType(Enum):
    FRAUD=auto()
    SOLICITATION=auto()
    IMPERSONATION=auto()

class BullyType(Enum):
    FAMILY=auto()
    PEER=auto()
    STRANGER=auto()
    UNKWOWN=auto()

class Report:
    START_KEYWORD = "report"
    CANCEL_KEYWORD = "cancel"
    HELP_KEYWORD = "help"

    def __init__(self, client):
        self.state = State.REPORT_START
        self.client = client
        self.message = None # use this to get author
        self.report_reason=None
        self.did_block=None
        self.block_ask='Would you like to block this user? This user will not know that you have blocked them. Please respond with yes/no'
        self.remove_ask='Would you like to have the message removed? Please respond with yes/no.\nThe moderation team will continue to have access for subsequent moderation decisions.'
        self.spam_type = None
        self.bully_type=None
        self.to_forward_to_mod=False
        self.forward_to_mod_text="""The following information (if available from your report) is sent to moderation team to inform subsequent moderation decisions: 
1) User Relationship with Sender
2) Decision to Block
3) Reason for Reporting
4) Last 10 messages from sender"""
        self.final_text="Thank you for reporting. Our content moderation team will review the message and decide on appropriate action which may involve account removal"

        self.link_database={
        (ReportType.BULLY,BullyType.FAMILY):"https://www.verywellfamily.com/dealing-with-the-family-bully-460696",
        (ReportType.BULLY,BullyType.PEER):"https://www.wikihow.com/Cope-With-Classmates-Hating-You",
        (ReportType.BULLY,BullyType.STRANGER):"https://www.endcyberbullying.net/what-to-do-if-youre-a-victim",
        (ReportType.BULLY,BullyType.UNKWOWN):"https://www.endcyberbullying.net/what-to-do-if-youre-a-victim",
        (ReportType.SEXUAL_HARASS,BullyType.FAMILY):"https://www.rainn.org/news/surviving-sexual-abuse-family-member",
        (ReportType.SEXUAL_HARASS,BullyType.PEER):"https://www.verywellmind.com/healing-from-sexual-harassment-in-the-workplace-4151996",
        (ReportType.SEXUAL_HARASS,BullyType.STRANGER):"https://www.soundvision.com/article/15-tips-for-victims-on-how-to-deal-with-sexual-assault-abuse-and-harassment-in-the-west",
        (ReportType.SEXUAL_HARASS,BullyType.UNKWOWN):"https://www.soundvision.com/article/15-tips-for-victims-on-how-to-deal-with-sexual-assault-abuse-and-harassment-in-the-west",
        }
    
    async def handle_message(self, message):
        '''
        This function makes up the meat of the user-side reporting flow. It defines how we transition between states and what 
        prompts to offer at each of those states. You're welcome to change anything you want; this skeleton is just here to
        get you started and give you a model for working with Discord. 
        '''

        if message.content == self.CANCEL_KEYWORD:
            self.state = State.REPORT_COMPLETE
            return ["Report cancelled."]
        
        if self.state == State.REPORT_START:
            reply =  "Thank you for starting the reporting process. "
            reply += "Say `help` at any time for more information.\n\n"
            reply += "Please copy paste the link to the message you want to report.\n"
            reply += "You can obtain this link by right-clicking the message and clicking `Copy Message Link`."
            self.state = State.AWAITING_MESSAGE
            return [reply]
        
        if self.state == State.AWAITING_MESSAGE:
            # Parse out the three ID strings from the message link
            m = re.search('/(\d+)/(\d+)/(\d+)', message.content)
            if not m:
                return ["I'm sorry, I couldn't read that link. Please try again or say `cancel` to cancel."]
            guild = self.client.get_guild(int(m.group(1)))
            if not guild:
                return ["I cannot accept reports of messages from guilds that I'm not in. Please have the guild owner add me to the guild and try again."]
            channel = guild.get_channel(int(m.group(2)))
            if not channel:
                return ["It seems this channel was deleted or never existed. Please try again or say `cancel` to cancel."]
            try:
                message = await channel.fetch_message(int(m.group(3)))
            except discord.errors.NotFound:
                return ["It seems this message was deleted or never existed. Please try again or say `cancel` to cancel."]

            # Here we've found the message - it's up to you to decide what to do next!
            self.state = State.REASON_ASKED
            self.message=message
            return ["I found this message:", "```" + message.author.name + ": " + message.content + "```", \
                    'Please select the reason for reporting the message by choosing the number.\n1)I don\'t like this message\n2)Spam\n3)Bully/Hate Speech\n4)Sexual Harrasment']
                    # "This is all I know how to do right now - it's up to you to build out the rest of my reporting flow!"]
        
        # if self.state == State.MESSAGE_IDENTIFIED:
        #     # guild = self.client.get_guild(int(m.group(1)))
        #     # channel = guild.get_channel(int(m.group(2)))
        #     self.state=State.REASON_ASKED
        #     return ['Please select the reason for reporting the message by choosing the number.\n1)I don\'t like this message\n2)Spam\n3)Cyberbully/Harrasment']
            # if message.content.lower().startswith('y'):
                # await self.message.delete()

        if self.state==State.REASON_ASKED:
            if '1' in message.content or 'one' in message.content or 'first' in message.content:
                self.state=State.BLOCK_ASKED
                self.report_reason=ReportType.DONTLIKE
                return [self.block_ask]

            elif '2' in message.content or 'two' in message.content or 'second' in message.content:
                self.state=State.SPAM_TYPE
                self.report_reason=ReportType.SPAM
                return ['Please select the type of spam by choosing a number:\n1)Fraud/scam\n2)Solicitation\n3)Impersonation']

            elif '3' in message.content or 'three' in message.content or 'third' in message.content:
                self.state=State.BULLY_TYPE
                self.report_reason=ReportType.BULLY
                return ['Please tell how do you know the sender by choosing a number:\n1)Family member/relative\n2)Peer\n3)Stranger\n4)Prefer not to say']

            elif '4' in message.content or 'four' in message.content or 'fourth' in message.content:
                self.state=State.BULLY_TYPE
                self.report_reason=ReportType.SEXUAL_HARASS
                return ['Please tell how do you know the sender by choosing a number:\n1)Family member/relative\n2)Peer\n3)Stranger\n4)Prefer not to say']

            else:
                return ['I did not get that, please choose a number']


        if self.state==State.SPAM_TYPE:
            
            if '1' in message.content or 'one' in message.content or 'first' in message.content:
                self.spam_type= SpamType.FRAUD
                self.state=State.BLOCK_ASKED
                return [self.block_ask]
            elif '2' in message.content or 'two' in message.content or 'second' in message.content:
                self.spam_type=SpamType.SOLICITATION
                self.state=State.BLOCK_ASKED
                return [self.block_ask]
            elif '3' in message.content or 'three' in message.content or 'third' in message.content:
                self.spam_type=SpamType.IMPERSONATION
                self.state=State.BLOCK_ASKED
                return [self.block_ask]
            else:
                return ['I did not get that, please choose a number']
            ##Cannot edit message: will have to delete and send a new one with the below 2 line
            # await self.message.channel.send('||'+self.message.content+'||')

        if self.state==State.BULLY_TYPE:
            if '1' in message.content or 'one' in message.content or 'first' in message.content:
                self.bully_type= BullyType.FAMILY
                self.state=State.BLOCK_ASKED
                return [self.block_ask]
            elif '2' in message.content or 'two' in message.content or 'second' in message.content:
                self.bully_type=BullyType.PEER
                self.state=State.BLOCK_ASKED
                return [self.block_ask]
            elif '3' in message.content or 'three' in message.content or 'third' in message.content:
                self.bully_type=BullyType.STRANGER
                self.state=State.BLOCK_ASKED
                return [self.block_ask]
            elif '4' in message.content or 'four' in message.content or 'fourth' in message.content:
                self.bully_type=BullyType.UNKWOWN
                self.state=State.BLOCK_ASKED
                return [self.block_ask]
            else:
                return ['I did not get that, please choose a number']

        if self.state==State.BLOCK_ASKED:
            if  message.content.lower().startswith('y'):
                self.did_block=True
                self.state=State.ASK_DELETE
                return [f'User ```{message.author.name}``` has been blocked',self.remove_ask]
            elif message.content.lower().startswith('n'):
                self.state=State.ASK_DELETE
                self.did_block=False
                return [self.remove_ask]
            else:
                return ['I did not get that, please reply with yes/no']

        if self.state==State.ASK_DELETE:

            if  message.content.lower().startswith('y'):
                self.state=State.REPORT_COMPLETE
                await self.message.delete()
                self.to_forward_to_mod=True
                msg_list=['The message has been deleted',self.forward_to_mod_text,self.final_text]
                if (self.report_reason,self.bully_type) in self.link_database:
                    msg_list.append(f'More resources to deal with what you are facing are available here ({self.link_database[(self.report_reason,self.bully_type)]})')
                return msg_list
            elif message.content.lower().startswith('n'):
                self.state=State.REPORT_COMPLETE
                self.to_forward_to_mod=True
                msg_list=[self.forward_to_mod_text,self.final_text]
                if (self.report_reason,self.bully_type) in self.link_database:
                    msg_list.append(f'More resources to deal with what you are facing are available here ({self.link_database[(self.report_reason,self.bully_type)]})')
                return msg_list
            else:
                return ['I did not get that, please reply with yes/no']
            
            # return ["Sure the message will be deleted"]

        return []

    def report_complete(self):
        return self.state == State.REPORT_COMPLETE

    

    def forward_to_mod(self):
        return self.to_forward_to_mod
    


    

