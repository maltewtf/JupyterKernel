from queue import Queue
from threading import Thread
from enum import Enum

from ipykernel.kernelbase import Kernel

import IPython
import re
import subprocess
import tempfile
import shutil
from ctypes.util import find_library
import os
import os.path as path
import json
import shlex

import ctypes

def rm_nonempty_dir (d):
    for root, dirs, files in os.walk (d, topdown=False):
        for name in files:
            os.remove (os.path.join(root, name))
        for name in dirs:
            os.rmdir (os.path.join(root, name))
    os.rmdir (d)


class RealTimeSubprocess(subprocess.Popen):
    """
    A subprocess that allows to read its stdout and stderr in real time
    """

    def __init__(self, cmd, write_to_stdout, write_to_stderr, directory):
        """
        :param cmd: the command to execute
        :param write_to_stdout: a callable that will be called with chunks of data from stdout
        :param write_to_stderr: a callable that will be called with chunks of data from stderr
        """
        self._write_to_stdout = write_to_stdout
        self._write_to_stderr = write_to_stderr

        super().__init__(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0, cwd=directory)

        self._stdout_queue = Queue()
        self._stdout_thread = Thread(target=RealTimeSubprocess._enqueue_output, args=(self.stdout, self._stdout_queue))
        self._stdout_thread.daemon = True
        self._stdout_thread.start()

        self._stderr_queue = Queue()
        self._stderr_thread = Thread(target=RealTimeSubprocess._enqueue_output, args=(self.stderr, self._stderr_queue))
        self._stderr_thread.daemon = True
        self._stderr_thread.start()

    @staticmethod
    def _enqueue_output(stream, queue):
        """
        Add chunks of data from a stream to a queue until the stream is empty.
        """
        for line in iter(lambda: stream.read(4096), b''):
            queue.put(line)
        stream.close()

    def wait_for_threads(self):
        self._stdout_thread.join()
        self._stderr_thread.join()

    def write_contents(self):
        """
        Write the available content from stdin and stderr where specified when the instance was created
        :return:
        """

        def read_all_from_queue(queue):
            res = b''
            size = queue.qsize()
            while size != 0:
                res += queue.get_nowait()
                size -= 1
            return res

        stdout_contents = read_all_from_queue(self._stdout_queue)
        if stdout_contents:
            self._write_to_stdout(stdout_contents)
        stderr_contents = read_all_from_queue(self._stderr_queue)
        if stderr_contents:
            self._write_to_stderr(stderr_contents)


################################################################################
#
#
# For every 'type' of input, we define its very own Action class.
# If you want to add a new one, define a new subclass of Action,
# provide the methods explained below, and add an instance of this
# Action into the field "actions" in SacKernel!
#
# Any action needs to provide the following methods:
#    check_input(self, code)
#    process_input(self, code)
#    revert_input(self, code)
#
# check_input finds out whether the given action is applicable
# and it returns a record {'found', 'code'}, indicating
# if the action has been found, and providing the input for
# processing the action.
#
# process_input performs the action. It returns a record
# { 'failed', 'stdout', 'stderr' }; finally,
#
# revert_input resets the internal state tp the one before
# processsing the input. It does not return anything.
#
# We try to keep as much state as possible local to the actions.
# Everything that *needs* to be shared between actions, lives
# in the SaCKernel class, a pointer to which is stored in all
# Action instances.
# All actions that pertain to the actual Sac code need to be
# subclasses of the abstract action Sac!
#
class Action:
    def __init__(self, kernel):
        self.kernel = kernel

    def check_input(self, code):
        return {'found': False, 'code': code}

    def process_input(self, code):
        return {'failed': False, 'stdout':"", 'stderr':""}

    def revert_input (self, code):
        pass

    def check_magic (self, magic, code):
        code = code.strip ()
        if code.startswith (magic):
            return {'found': True, 'code': code[len (magic):]}
        else:
            return {'found': False, 'code': code}



#
# %help
#
class Help(Action):
    def check_input(self, code):
        return self.check_magic ('%help', code)

    def process_input(self, code):
        return {'failed':False, 'stdout':"""\
Currently the following commands are available:
    %print      -- print the current program including
                   imports, functions and statements in the main.
    %flags      -- print flags that are used when running sac2c.
    %setflags <flags>
                -- reset sac2c falgs to <flags>
""", 'stderr':""}



#
# %print
#
class Print(Action):
    def check_input(self, code):
        return self.check_magic ('%print', code)

    def process_input(self, code):
        return {'failed':False,
                'stdout': self.kernel.mk_sacprg ("    /* StdIO::print ( your expression here ); */\n"),
                'stderr': ""}



#
# %flags
#
class Flags(Action):
    def check_input(self, code):
        return self.check_magic ('%flags', code)

    def process_input(self, code):
        return {'failed':False, 'stdout':' '.join (self.kernel.sac2c_flags),
                'stderr':""}




#
# %setflags
#
class Setflags(Action):
    def check_input(self, code):
        return self.check_magic ('%setflags', code)

    def process_input(self, code):
        self.kernel.sac2c_flags = shlex.split (code)
        return {'failed':False, 'stdout':"", 'stderr':""}




#
# sac - this is a super class for all sac-related action classes
#
class Sac(Action):
    def check_input(self, code):
        if (self.kernel.sac_check == None):
            self.kernel.sac_check = self.kernel.run_sac2c_parser (code)

        if (self.kernel.sac_check['status'] == 'fail'):
            return {'found': False, 'code': ""}
        else:
            return {'found': self.check_sac_action (code), 'code': code}

    def update_state (self, code):
        pass

    def revert_state (self, code):
        pass

    def mk_sac_prg ():
        return ""

    def process_input(self, code):
        self.update_state (code)
        prg = self.kernel.mk_sacprg ("")
        res = self.kernel.create_binary (prg)
        if (not (res['failed'])):
            res = self.kernel.run_binary ()
        return res

    def revert_input (self, code):
        self.revert_state (code)

    # generic helper functions for dictionaries:

    def push_symb_dict (self, mydict, code):
        key = self.kernel.sac_check['symbol']
        if (key in mydict):
            res = mydict[key]
        else:
            res = None
        mydict[key] = code
        return res

    def pop_symb_dict (self, mydict, code):
        key = self.kernel.sac_check['symbol']
        if (code == None):
            del mydict[key]
        else:
            mydict[key] = code

#
# Sac - expression
#
class SacExpr(Sac):
    def __init__(self, kernel):
        super().__init__ (kernel)
        self.expr = None

    def check_sac_action (self, code):
        return (self.kernel.sac_check['ret'] == 1)

    def update_state (self, code):
        self.expr = code

    def revert_state (self, code):
        self.expr = None

    def mk_sacprg (self, goal):
        if (self.expr == None):
            return goal
        else:
            return "\n    StdIO::print ({});\n".format (self.expr)



#
# Sac - statement
#
class SacStmt(Sac):
    def __init__(self, kernel):
        super().__init__ (kernel)
        self.stmts = []

    def check_sac_action (self, code):
        return (self.kernel.sac_check['ret'] == 2)

    def update_state (self, code):
        self.stmts.append ("    "+code.replace ("\n", "\n    ")+"\n")

    def revert_state (self, code):
        self.stmts.pop ()

    def mk_sacprg (self, goal):
        return "\nint main () {\n" + "".join (self.stmts)


#
# Sac - function
#
class SacFun(Sac):
    def __init__(self, kernel):
        super().__init__ (kernel)
        self.funs = dict ()
        self.old_def = None

    def check_sac_action (self, code):
        return (self.kernel.sac_check['ret'] == 3)

    def update_state(self, code):
        self.old_def = self.push_symb_dict (self.funs, code)

    def revert_state (self, code):
        self.pop_symb_dict (self.funs, self.old_def)

    def mk_sacprg (self, goal):
        return "\n// functions\n" + "\n".join (self.funs.values ()) +"\n"


#
# Sac - typedef
#
class SacType(Sac):
    def __init__(self, kernel):
        super().__init__ (kernel)
        self.typedefs = dict ()
        self.old_def = None

    def check_sac_action (self, code):
        return (self.kernel.sac_check['ret'] == 4)

    def update_state(self, code):
        self.old_def = self.push_symb_dict (self.typedefs, code)

    def revert_state (self, code):
        self.pop_symb_dict (self.typedefs, self.old_def)

    def mk_sacprg (self, goal):
        return "\n// typedefs\n" + "\n".join (self.typedefs.values ()) +"\n"



#
# Sac - import
#
class SacImport(Sac):
    def __init__(self, kernel):
        super().__init__ (kernel)
        self.imports = dict ()
        self.old_def = None

    def check_sac_action (self, code):
        return (self.kernel.sac_check['ret'] == 5)

    def update_state(self, code):
        self.old_def = self.push_symb_dict (self.imports, code)

    def revert_state (self, code):
        self.pop_symb_dict (self.imports, self.old_def)

    def mk_sacprg (self, goal):
        return "\n// imports\n" + "\n".join (self.imports.values ()) +"\n"



#
# Sac - use
#
class SacUse(Sac):
    def __init__(self, kernel):
        super().__init__ (kernel)
        self.uses = dict ()
        self.old_def = None

    def check_sac_action (self, code):
        return (self.kernel.sac_check['ret'] == 6)

    def update_state(self, code):
        self.old_def = self.push_symb_dict (self.uses, code)

    def revert_state (self, code):
        self.pop_symb_dict (self.uses, self.old_def)

    def mk_sacprg (self, goal):
        return "\n// uses\n" + "\n".join (self.uses.values ()) +"\n"





#
# Here, the actual kernel implementation starts
#

class SacKernel(Kernel):
    implementation = 'jupyter_sac_kernel'
    implementation_version = '0.3'
    language = 'sac'
    language_version = '1.3.3'
    language_info = {'name': 'sac',
                     'mimetype': 'text/plain',
                     'file_extension': '.sac'}
    banner = "SaC kernel.\n" \
             "Uses sac2c, to incrementaly compile the notebook.\n"
    def __init__(self, *args, **kwargs):
        super(SacKernel, self).__init__(*args, **kwargs)
        self.actions = [Help (self), Print (self), Flags (self), Setflags (self),
                        SacUse (self), SacImport (self), SacType (self),
                        SacFun (self), SacStmt (self), SacExpr (self)]
        self.files = []
        self.stdout = ""
        self.stderr = ""
        self.binary = None
        self.sac_check = None
        # Make sure to do checks on array bounds as well
        self.sac2c_flags =  ['-v0', '-O0', '-noprelude', '-noinl', '-maxspec', '0', '-check', 'ps', '-st-below', '-st-compact']

        # get sac2c_p binary
        os.environ["PATH"] += "/usr/local/bin"
        self.sac2c_bin = shutil.which ('sac2c')
        if not self.sac2c_bin:
            raise RuntimeError ("Unable to find sac2c binary!")

        # find global lib directory (different depending on sac2c version)
        sac_path_proc = subprocess.run([self.sac2c_bin, "-plibsac2c"], capture_output=True, text=True)
        sac_lib_paths = sac_path_proc.stdout.strip(" \n")
        if "LD_LIBRARY_PATH" in os.environ:
            os.environ["LD_LIBRARY_PATH"] += sac_lib_paths
        else:
            os.environ["LD_LIBRARY_PATH"] = sac_lib_paths
        if "DYLD_LIBRARY_PATH" in os.environ:
            os.environ["DYLD_LIBRARY_PATH"] += sac_lib_paths
        else:
            os.environ["DYLD_LIBRARY_PATH"] = sac_lib_paths

        sac2c_so_name = find_library('sac2c_p')
        if not sac2c_so_name:
            sac2c_so_name = find_library('sac2c_d')
            if not sac2c_so_name:
                raise RuntimeError ("Unable to load sac2c shared library!")

        self.sac2c_so = None

        for sac_lib_path in sac_lib_paths.split(':'):
            sac2c_so = path.join(sac_lib_path, sac2c_so_name)
            if path.exists(sac2c_so):
                self.sac2c_so = sac2c_so
                break

        if self.sac2c_so is None:
            raise RuntimeError ("Unable to load sac2c shared library!")

        # get shared object
        self.sac2c_so_handle = ctypes.CDLL (self.sac2c_so, mode=(1|ctypes.RTLD_GLOBAL))

        # init sac2c jupyter interface
        self.sac2c_so_handle.jupyter_init ()
        self.sac2c_so_handle.CTFinitialize ()
        self.sac2c_so_handle.jupyter_parse_from_string.restype = ctypes.c_void_p
        self.sac2c_so_handle.jupyter_free.argtypes = ctypes.c_void_p,
        self.sac2c_so_handle.jupyter_free.res_rtype = ctypes.c_void_p

        # Creatae the directory where all the compilation/execution will be happening.
        self.tmpdir = tempfile.mkdtemp (prefix="jup-sac")

        # Array is included by default. We execute the `use` declaration here
        # to ensure that the SaC module cache has been initialized.
        self.do_execute("use Array: all;", False)

    def cleanup_files(self):
        """Remove all the temporary files created by the kernel"""
        for file in self.files:
            os.remove(file)

        # Remove the directory
        rm_nonempty_dir (self.tmpdir)

        # Call some cleanup functions in sac2c library.
        self.sac2c_so_handle.jupyter_finalize ()

    def run_sac2c_parser (self, prog):
        s = ctypes.c_char_p (prog.encode ('utf-8'))
        ret_ptr = self.sac2c_so_handle.jupyter_parse_from_string (s, -1) #len (self.imports))
        ret_s = ctypes.cast (ret_ptr, ctypes.c_char_p).value
        self.sac2c_so_handle.jupyter_free (ret_ptr)
        j = {"status": "fail", "stderr": "cannot parse json: {}".format (ret_s)}
        try:
            j = json.loads (ret_s)
        except:
            pass
        return j

    def new_temp_file(self, **kwargs):
        """Create a new temp file to be deleted when the kernel shuts down"""
        # We don't want the file to be deleted when closed, but only when the kernel stops
        kwargs['delete'] = False
        kwargs['mode'] = 'w'
        kwargs['dir'] = self.tmpdir
        file = tempfile.NamedTemporaryFile(**kwargs)
        self.files.append(file.name)
        return file

    def _write_to_stdout(self, contents):
        self.send_response(self.iopub_socket, 'stream', {'name': 'stdout', 'text': contents})

    def _write_to_stderr(self, contents):
        self.send_response(self.iopub_socket, 'stream', {'name': 'stderr', 'text': contents})

    def append_stdout (self, txt):
        self.stdout += txt

    def append_stderr (self, txt):
        self.stderr += txt

    def create_jupyter_subprocess(self, cmd):
        self.stdout = ""
        self.stderr = ""
        return RealTimeSubprocess(cmd,
                                  lambda contents: self.append_stdout (contents.decode()),
                                  lambda contents: self.append_stderr (contents.decode()),
                                  self.tmpdir)

    def mk_sacprg (self, goal):
        prg = ""
        for action in self.actions:
            if (issubclass (type(action), Sac)):
                prg += action.mk_sacprg (goal)
        prg += "    return 0;\n}"
        return prg;

    def compile_with_sac2c(self, source_filename, binary_filename, extra_flags=[]):
        # Flags are of type list of strings.
        sac2cflags = self.sac2c_flags + extra_flags
        args = [self.sac2c_bin] + ['-o', binary_filename] + sac2cflags + [source_filename]
        return self.create_jupyter_subprocess(args)

    def create_binary (self, prg):
        with self.new_temp_file(suffix='.sac') as source_file:
            source_file.write(prg)
            source_file.flush()
            with self.new_temp_file(suffix='.exe') as binary_file:
                p = self.compile_with_sac2c (source_file.name, binary_file.name)
                while p.poll() is None:
                    p.write_contents()
                p.write_contents()
                if (p.returncode != 0):  # Compilation failed
                    return {'failed': True, 'stdout': self.stdout,
                            'stderr': self.stderr +
                                      "[SaC kernel] sac2c exited with code {}, the executable will not be executed".format(
                                        p.returncode)}
                else:
                    self.binary = binary_file.name
                    return {'failed':False, 'stdout': self.stdout, 'stderr': self.stderr }

    def run_binary (self):
        p = self.create_jupyter_subprocess([self.binary])
        while p.poll() is None:
            p.write_contents()

        p.wait_for_threads()
        p.write_contents()

        if (p.returncode != 0):  # Compilation failed
            return {'failed': True, 'stdout': self.stdout,
                    'stderr': self.stderr +
                              "[SaC kernel] Executable exited with code {}".format(
                                p.returncode)}
        else:
            return {'failed':False, 'stdout': self.stdout, 'stderr': self.stderr }

    def do_execute(self, code, silent, store_history=True,
                   user_expressions=None, allow_stdin=False):

        if not silent:
            for action in self.actions:
                cres = action.check_input (code)
                if (cres['found']):
                    status = 'ok'
                    res = action.process_input (cres['code'])
                    if (res['failed']):
                        action.revert_input (code)
                        status = 'error'
                    elif (type(action).__name__ == 'SacExpr'):
                        action.revert_input (code)
                    if (res['stdout'] != ""):
                        self._write_to_stdout (res['stdout'])
                    if (res['stderr'] != ""):
                        self._write_to_stderr (res['stderr'])
                    break
            if ( not cres['found']): #we know that the Sac check has failed!
                status = 'error'
                self._write_to_stderr ("[SaC kernel] This is not an expression/statements/function or use/import/typedef\n"
                                       + self.sac_check['stderr'])
            self.sac_check = None

        return {'status': status, 'execution_count': self.execution_count, 'payload': [], 'user_expressions': {}}

    def do_shutdown(self, restart):
        """Cleanup the created source code files and executables when shutting down the kernel"""
        self.cleanup_files()


if __name__ == "__main__":
    from ipykernel.kernelapp import IPKernelApp
    IPKernelApp.launch_instance(kernel_class=SacKernel)
