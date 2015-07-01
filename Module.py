class Command: # An executable command.
    def __init__(self, name, execute, help_data='', privileged=False):
        self.name = name
        self.execute = execute
        self.help_data = help_data or "Command exists, but no help entry found."
        self.privileged = privileged
        
    

class Module: # Contains a list of Commands.
    def __init__(self, commands, bot):
        self.bot = bot
        self.commands = commands
        
    def command(self, name, args, msg, event):
        matches = self.find_commands(name)
        if matches:
            command = matches[0]
            if not command.privileged or msg is None or event.user.id in self.bot.owner_ids:
                return command.execute(args, msg, event)
            else:
                return "You don't have the privilege to execute this command."
        else:    
            return ''

    def get_help(self, name):
        matches = self.find_commands(name)
        if matches:
            return matches[0].help_data
        else:
            return ''
    
    def find_commands(self, name):
        return filter(lambda x: x.name == name, self.commands)
    
    def list_commands(self):
        cmd_list = []
        for command in self.commands:
            cmd_list.append(command.name)
        return cmd_list


class MetaModule: # Contains a list of Modules.
    def __init__(self, modules, bot):
        self.modules = []
        self.bot = bot
        for module in modules:
            self.modules.append(MetaModule.load_module(module))
        
    def command(self, name, args, msg, event):
        response = False
        for module in self.modules:
            response = module.command(name, args, msg, event)
            if response:
                break
        return response
        
    def get_help(self, name):
        response = False
        for module in self.modules:
            response = module.get_help(name)
            if response:
                break
        return response

    @staticmethod
    def load_module(file_):
        try:
            module_file = __import__(file_)
        except ImportError:
            raise ModuleDoesNotExistException("Module: '" + file_ + '"Could not be found.')
        return module_file.module
    
    def list_commands(self):
        cmd_list = []
        for module in self.modules:
            cmd_list.extend(module.list_commands())
        return cmd_list
        

class ModuleDoesNotExistException(Exception):
    pass
