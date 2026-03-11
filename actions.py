import re

class Action:
    """
    compiler check return codes:
    1 = expression
    2 = statement
    3 = function
    4 = typedef
    5 = import
    6 = use
    """
    def __init__(self):
        self.lines : list[str] = []
        self.entries : dict[str, str] = {}

    def push(self, code):
        # this is overly general and I am not sure if the inheritance approach is good here
        # -> this uses the dict as if it was a set, yet it can still be used as a dict by the subclasses
        self.entries[code] = code

    def to_str(self):
        return '\n'.join(self.entries.values())
    

class Expression(Action):
    # one time execution
    def __init__(self):
        super().__init__()
        self.code = ''

    def push(self, code):
        self.code = code

    def to_str(self):
        return self.code

    def clear(self):
        self.code = ''


class Statement(Action):
    # keep cumulative
    def __init__(self):
        super().__init__()
        self.assignments: set[str] = set()
        self.code = ''

    def push(self, code):
        self.code = code
        self.assignments = extract_assigned_variables(code)

    def add_definition(self, variable, value):
        self.entries[variable] = value

    def to_str(self):
        return self.code

    def get_assignments_str(self):
        return """printf(";");\n    """.join([f"""printf("{i}="); print_serialized({i});""" for i in self.assignments])

    def get_definitions_str(self):
        return "\n".join([f"{i} = {self.entries[i]};" for i in self.entries])

    def clear(self):
        self.assignments = []
        self.code = ''


class Function(Action):
    # keep overwrite
    def __init__(self):
        super().__init__()

    def push(self, code):
        self.entries[extract_function_indentifier(code)] = code

class Typedef(Action):
    # keep overwrite
    def __init__(self):
        super().__init__()

class Import(Action):
    # keep overwrite
    def __init__(self):
        super().__init__()

class Use(Action):
    # keep overwrite
    def __init__(self):
        super().__init__()


def extract_function_indentifier(code: str) -> str:
    """ 
    placeholder function! To be replaced with sac2c implementation
    returns identifier of function(s) entered. assumes sac2c classifies code as function 
    """
    return code.split()[1]


def extract_assigned_variables(code: str) -> list[str]:
    """ placeholder function! To be replaced with sac2c implementation """
    cleaned = re.sub(r"==+", "", extract_code(code))
    divisions = cleaned.split("=")
    variables = [re.split(r"[/\W/]+", var.strip())[-1] for var in divisions[:-1]]
    return variables

def extract_code(code: str):
    """ removes string literals """
    return "".join([s for i, s in enumerate(re.split(r""""|'""", code)) if i % 2 == 0])

sac_action_map = {
    -1: None,
    1: Expression,
    2: Statement,
    3: Function,
    4: Typedef,
    5: Import,
    6: Use
    }
