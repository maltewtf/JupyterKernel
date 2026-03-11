import shlex
from objects import Result
# from kernel import SacKernel

class Magic:
    def __init__(self, kernel):
        self.kernel = kernel
        self.prefix = 'MISSING PREFIX'
        self.help_str = 'MISSING DESCRIPTION'
        self.help_args = ''

    def is_magic(self, code: str) -> bool:
        return code.startswith(self.prefix)

    def process_input(self, _):
        return Result()

    def revert_input(self, _):
        # what was this method used for??
        pass

    def get_help(self) -> str:
        return f'{f"{self.prefix} {self.help_args}".ljust(25)} -- {self.help_str}'

#
# %help
#
class Help(Magic):
    def __init__(self, kernel):
        super().__init__(kernel)
        self.prefix = '%help'
        self.help_str = 'list available magics and their function.'
        self.available_magics: list[Magic] = []

    def set_available_magics(self, magics):
        self.available_magics = magics
    
    def process_input(self, _):
        return Result(f'Currently the following commands are available:\n  {"\n  ".join([magic.get_help() for magic in self.available_magics])}')

#
# %print
#
class Print(Magic):
    def __init__(self, kernel):
        super().__init__(kernel)
        self.prefix = '%print'
        self.help_str = 'print the current program including imports, functions and statements.'

    def process_input(self, _):
        return Result(self.kernel.mk_sacprg())
#
# %flags
#
class Flags(Magic):
    def __init__(self, kernel):
        super().__init__(kernel)
        self.prefix = '%flags'
        self.help_str = 'print flags that are used when running sac2c.'

    def process_input(self, _):
        return Result(' '.join(self.kernel.sac2c_flags))

#
# %setflags
#
class Setflags(Magic):
    def __init__(self, kernel):
        super().__init__(kernel)
        self.prefix = '%setflags'
        self.help_str = 'set sac2c falgs to <flags>.'
        self.help_args = '<flags>'

    def process_input(self, code):
        self.kernel.sac2c_flags = shlex.split(code)
        return Result()
    
def check_magics(code, magics) -> Magic | None:
    for magic in magics:
        if magic.is_magic(code):
            return magic

def execute_magic(code, magic):
    magic_result = magic.process_input(code)
    stdout = magic_result['stdout']
    stderr = magic_result['stderr']
    return stdout, stderr
