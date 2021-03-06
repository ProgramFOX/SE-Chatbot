import getpass
import re
import logging.handlers
import sys
import time

from ChatExchange.chatexchange.client import Client
from ChatExchange.chatexchange.browser import LoginError
from ChatExchange.chatexchange.events import MessagePosted, MessageEdited
from ChatExchange.chatexchange.messages import Message
from fixedfont import fixed_font_to_normal, is_fixed_font
from Config import Config
import ModuleManifest
from Module import MetaModule
from ConsoleCommandHandler import ConsoleCommandHandler
import SaveIO
from SaveIO import DuplicateDirectoryException


class Chatbot:
    def __init__(self):
        self.room = None
        self.client = None
        self.privileged_users = []
        self.owners = []
        self.owner_name = ""
        self.chatbot_name = ""
        self.enabled = True
        self.suspended_until = -1
        self.running = True
        self.site = ""
        self.owner_ids = []
        self.privileged_user_ids = []
        self.save_subdirs = ['main']
        self.modules = MetaModule(ModuleManifest.module_file_names, self, 'all')
        try:
            SaveIO.set_subdirs(self.save_subdirs)
        except DuplicateDirectoryException as e:
            if "-q" not in sys.argv:
                print("[Chatbot] WARNING: there are modules with the same save directory: " + str(e))
        SaveIO.create_if_not_exists(SaveIO.data_dir)
        del self.save_subdirs
        duplicates = self.get_duplicate_commands()
        if duplicates and "-q" not in sys.argv:
            print('[Chatbot] WARNING: there are commands with the same name: ' + str(duplicates))

    def main(self, config_data, additional_general_config):
        if "owners" in Config.General:
            self.owners = Config.General["owners"]
        else:
            sys.exit("[Chatbot] FATAL: no owners found. Please update Config.py.")
        if "privileged_users" in config_data:
            self.privileged_users = config_data["privileged_users"]
        if "github" in Config.General:
            self.github = Config.General["github"]
        else:
            self.github = "https://github.com/ProgramFOX/SE-Chatbot"
        if "owner_name" in Config.General:
            self.owner_name = Config.General["owner_name"]
        else:
            sys.exit("[Chatbot] FATAL: no owner name found. Please update Config.py.")
        if "chatbot_name" in Config.General:
            self.chatbot_name = Config.General["chatbot_name"]
        else:
            sys.exit("[Chatbot] FATAL: no chatbot name found. Please update Config.py.")
        # self.setup_logging() # if you want to have logging, un-comment this line

        if "site" in config_data:
            self.site = config_data["site"]
            print("Site: %s" % self.site)
        else:
            self.site = input("Site: ")
        for o in self.owners:
            if self.site in o:
                self.owner_ids.append(o[self.site])
        if len(self.owner_ids) < 1:
            sys.exit("[Chatbot] FATAL: no owners found for this site: %s." % self.site)
        for p in self.privileged_users:
            if self.site in p:
                self.privileged_user_ids.append(p[self.site])
        if "room" in config_data:
            room_number = config_data["room"]
            print("Room number: %i" % room_number)
        else:
            room_number = int(input("Room number: "))
        if "prefix" in config_data:
            self.prefix = config_data["prefix"]
        else:
            self.prefix = '>>'
        print("Prefix: %s" % self.prefix)
        if "email" in Config.General:
            email = Config.General["email"]
        elif "email" in additional_general_config:
            email = additional_general_config["email"]
        else:
            email = input("Email address: ")

        self.client = Client(self.site)

        # Setting the timeout down to 5 fixes random SSL errors when terminating.
        # The bot's timeout on exit is 5; the request timeout is 30 by default. Requests overrun the
        # bot timeout, get force-closed, and cause errors.
        self.client._br.request_timeout = 5.0

        try:
            if "password" in Config.General:  # I would not recommend to store the password in Config.py
                password = Config.General["password"]
                self.client.login(email, password)
            elif "password" in additional_general_config:
                password = additional_general_config["password"]
                self.client.login(email, password)
            else:
                for attempts in range(3):
                    try:
                        password = getpass.getpass("Password: ")
                        self.client.login(email, password)
                        break
                    except LoginError:
                        if attempts < 2:
                            print("Incorrect password.")
                        else:
                            raise
        except LoginError:
            sys.exit("[Chatbot] FATAL: Incorrect password, shutting down.")

        self.room = self.client.get_room(room_number)
        self.room.join()
        if "message" not in additional_general_config:
            bot_message = "Bot started."
        else:
            bot_message = additional_general_config["message"]
        if bot_message is not None:
            self.room.send_message(bot_message)

        on_loads = self.modules.get_on_load_methods()
        for on_load in on_loads:
            on_load(self)

        self.room.watch_socket(self.on_event)

        while self.running:
            inputted = input("<< ")
            if inputted.strip() == "":
                continue
            if inputted.startswith("$") and len(inputted) > 2:
                command_in = inputted[2:]
                cmd_handler = ConsoleCommandHandler(self, inputted[1] == "+", self.prefix + command_in)
                event_mock = type('MockEvent', (), {})()
                user_mock = type('', (), {})()
                user_mock.id = -1
                event_mock.user = user_mock
                event_mock.message = cmd_handler
                command_out = self.command(command_in, cmd_handler, event_mock, 0)
                if command_out is not False and command_out is not None:
                    cmd_handler.reply(command_out)
            else:
                self.room.send_message(inputted)

    def get_duplicate_commands(self):
        checked_cmds = []
        dupe_cmds = []
        all_cmds = self.modules.list_commands()
        for command in all_cmds:
            if command.name not in checked_cmds:
                checked_cmds.append(command.name)
            else:
                if command.name not in dupe_cmds:
                    dupe_cmds.append(command.name)
        return dupe_cmds

    def setup_logging(self):  # logging method taken from ChatExchange/examples/chat.py
        logger = logging.getLogger(__name__)
        logging.basicConfig(level=logging.INFO)
        logger.setLevel(logging.DEBUG)

        # In addition to the basic stderr logging configured globally
        # above, we'll use a log file for chatexchange.client.
        wrapper_logger = logging.getLogger('chatexchange.client')
        wrapper_handler = logging.handlers.TimedRotatingFileHandler(
            filename='client.log',
            when='midnight', delay=True, utc=True, backupCount=7,
        )
        wrapper_handler.setFormatter(logging.Formatter(
            "%(asctime)s: %(levelname)s: %(threadName)s: %(message)s"
        ))
        wrapper_logger.addHandler(wrapper_handler)

    def check_existence_and_chars(self, cmd_name, content):
        cmd_list = self.modules.list_commands()
        allowed = -1
        disallowed = -1
        for cmd in cmd_list:
            if cmd.name == cmd_name or (cmd.aliases is not None and cmd_name in cmd.aliases):
                allowed = cmd.allowed_chars
                disallowed = cmd.disallowed_chars
                break
        if allowed == -1:
            return False, False
        for c in content:
            if disallowed is not None and c in disallowed:
                return True, False
            if allowed is not None and c not in allowed:
                return True, False
        return True, True

    def requires_special_arg_parsing(self, cmd_name):
        cmd_list = self.modules.list_commands()
        for cmd in cmd_list:
            if cmd.name == cmd_name:
                return cmd.special_arg_parsing is not None
        return False

    def do_special_arg_parsing(self, cmd_name, full_cmd):
        cmd_list = self.modules.list_commands()
        for cmd in cmd_list:
            if cmd.name == cmd_name and cmd.special_arg_parsing is not None:
                return cmd.special_arg_parsing(full_cmd)
        return False

    def on_event(self, event, client):
        if ((not self.enabled or self.suspended_until > time.time()) and event.user.id not in self.owner_ids) \
                or not self.running:
            return

        watchers = self.modules.get_event_watchers()
        for w in watchers:
            w(event, client, self)
        
        if not (isinstance(event, MessagePosted) or isinstance(event, MessageEdited) or str(type(event)).find('Chatbot.MockEvent') > -1):
            return

        if event.user.id == self.client.get_me().id:
            return

        if isinstance(event, MessageEdited):
            message = Message(event.message.id, client)
        else:
            message = event.message
        content_source = message.content_source
        content = content_source

        fixed_font = is_fixed_font(content)
        if fixed_font:
            fixed_font = True
            content = fixed_font_to_normal(content)
        content = re.sub(r"^%s\s+" % self.prefix, self.prefix, content)
        content = re.sub("(^[^ \r\n]+)(\r?\n)", r"\1 ", content)
        if not fixed_font:
            stripped_content = re.sub(r"\s+", " ", content)
            stripped_content = stripped_content.strip()
        else:
            stripped_content = content
        parts = stripped_content.split(" ")
        if not parts[0].startswith(self.prefix):
            return

        cmd_args = stripped_content[len(self.prefix):]
        if self.requires_special_arg_parsing(cmd_args.split(" ")[0]):
            cmd_args = content[len(self.prefix):]
        output = self.command(cmd_args, message, event, 0)
        if output is not False and output is not None:
            output_with_reply = ":%i %s" % (message.id, output)
            if len(output_with_reply) > 500 and "\n" not in output_with_reply:
                message.reply("Output would be longer than 500 characters (the limit for single-line messages), so only the first 500 characters are posted now.")
                message.reply(output[:500 - (len(message.id) + 2)])
            else:
                message.reply(output, False)

    def command(self, cmd, msg, event, start):
        cmd_args = cmd.split(' ')
        cmd_name = cmd_args[0].lower()
        args = cmd_args[1:]
        exists, allowed = self.check_existence_and_chars(cmd_name, ' '.join(args))
        if not exists:
            return "Command not found."
        if not allowed:
            return "Command contains invalid characters."
        if self.requires_special_arg_parsing(cmd_name):
            args = self.do_special_arg_parsing(cmd_name, cmd)
            if args is False:
                return "Argument parsing failed."
        return self.modules.command(cmd_name, args, msg, event)

    def bot_stopping(self):
        on_stops = self.modules.get_on_stop_methods()
        for on_stop in on_stops:
            on_stop(self)
