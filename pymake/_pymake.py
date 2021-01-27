"""
pymake helpers
"""
from __future__ import absolute_import
# import compatibility functions and utilities
from ._utils import ConfigParser, StringIO, shlex
import io
import re
from subprocess import check_call

__author__ = {"github.com/": ["casperdcl", "lrq3000"]}
__all__ = ['PymakeTypeError', 'PymakeKeyError',
           'parse_makefile_aliases', 'execute_makefile_commands']


RE_MAKE_CMD = re.compile(r'^\t(@\+?)(make)?')
RE_MACRO_DEF = re.compile(r"^(\S+)\s*\:?\=\s*(.*?)$")
RE_MACRO = re.compile(r"\$\(\s*\S+\s*\)")
RE_COMMENT = re.compile("#.*$")


class PymakeTypeError(TypeError):
    pass


class PymakeKeyError(KeyError):
    pass


def parse_makefile_aliases(filepath):
    '''
    Parse a makefile to find commands and substitute variables. Expects a
    makefile with only aliases and a line return between each command.

    Returns
    -------
    commands  : dict
        Maps each alias to a list of commands.
    default_alias  : str
    '''

    with io.open(filepath, mode='r') as fd:
        ini_lines = fd.read().replace('\r\n', '\n').replace('\\\n', '')
        ini_lines = (RE_MAKE_CMD.sub('\t', i) for i in ini_lines.split('\n'))
    # fake section to resemble valid *.ini
    ini_lines = ['[root]'] + list(ini_lines)
    # replace comments with dummy contents so as to remove all reserved exprs
    ini_lines = [RE_COMMENT.sub("# removed comment", line)
                 for line in ini_lines]

    # Substitute macros
    macros = dict(found for l in ini_lines
                  for found in RE_MACRO_DEF.findall(l) if found)
    ini_str = '\n'.join(ini_lines)
    # allow finite amount of nesting
    for _ in range(99):
        for (m, expr) in getattr(macros, 'iteritems', macros.items)():
            ini_str = re.sub(r"\$\(%s\)" % m, expr, ini_str)
        if not RE_MACRO.search(ini_str):
            # Strip macro definitions for rest of parsing
            ini_str = '\n'.join(l for l in ini_str.splitlines()
                                if not RE_MACRO_DEF.search(l))
            break
    else:
        raise PymakeKeyError("No substitution for macros: " +
                             str(set(RE_MACRO.findall(ini_str))))

    ini_fp = StringIO.StringIO(ini_str)
    config = ConfigParser.RawConfigParser()
    config.readfp(ini_fp)
    aliases = config.options('root')

    # Extract commands for each alias
    commands = {}
    default_alias = ''
    for alias in aliases:
        if alias.lower() in ['.phony']:
            continue
        if not default_alias:
            default_alias = alias
        commands[alias] = config.get('root', alias).lstrip('\n').split('\n')

    # Command substitution (depth-first).
    # If this is not possible because an alias points to another alias,
    # then stop and put the current alias back in the queue to be
    # processed again later (bottom-up).

    aliases_todo = list(commands.keys())
    commands_new = {}
    while aliases_todo:
        alias = aliases_todo.pop()
        commands_new[alias] = []
        for cmd in commands[alias]:
            # Ignore self-referencing (alias points to itself)
            if cmd == alias:
                pass
            elif cmd in aliases:
                # Append substituted full commands
                if cmd in commands_new:
                    commands_new[alias].extend(commands_new[cmd])
                # Delay substituting another alias until it is substituted
                else:
                    del commands_new[alias]
                    aliases_todo.insert(0, alias)
                    break
            # Full command (no aliases)
            else:
                commands_new[alias].append(cmd)
    commands = commands_new
    # Prepending prefix to avoid conflicts with standard setup.py commands
    # for alias in list(commands.keys()):
    #     commands['make_'+alias] = commands.pop(alias)
    return commands, default_alias


def execute_makefile_commands(
        commands, alias, silent=False, just_print=False, ignore_errors=False):
    """
    Execution Handler

    Parameters
    ----------
    commands  : dict
        Maps each alias to a list of commands.
    alias  : str

    Bool Options (default-false)
    ----------------------------
    silent, just_print, ignore_errors
    """
    cmds = commands[alias]

    if just_print:
        print('\n'.join(cmds))
        return

    for cmd in cmds:
        # Parse string in a shell-like fashion
        # (incl quoted strings and comments)
        parsed_cmd = shlex.split(cmd, comments=True)
        # Execute command if not empty/comment
        if parsed_cmd:
            if not silent:
                print(cmd)
            # Launch the command and wait to finish (synchronized call)
            try:
                check_call(parsed_cmd)
            except:
                if not ignore_errors:
                    raise
