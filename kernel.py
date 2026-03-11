from queue import Queue
from threading import Thread
from ipykernel.kernelbase import Kernel as JupyterKernel
import subprocess
import tempfile
import shutil
from ctypes.util import find_library
import os
import json
import ctypes
from textwrap import dedent
from objects import Status, Result

from actions import *
from magics import Magic

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

#
# Here, the actual kernel implementation starts
#
class SacKernel(JupyterKernel):
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

        self.actions : dict[type[Action], Action] = {Action: Action() for Action in sac_action_map.values() if Action}
        self.magics : dict[type[Action], Magic] = {(m := Magic(self)).prefix: m for Magic in Magic.__subclasses__()}

        # set available magics so that the %help magic can list their definitions
        self.magics["%help"].set_available_magics(self.magics.values())

        self.files = []
        self.stdout = ""
        self.stderr = ""
        self.binary = None
        self.sac_check = None
        self.separator = "--- internal variables ---"

        # Make sure to do checks on array bounds as well
        self.sac2c_flags =  ['-v0', '-O0', '-noprelude', '-noinl', '-maxspec', '0', '-check', 'tc']

        # get sac2c_p binary
        os.environ["PATH"] += "/usr/local/bin"
        self.sac2c_bin = shutil.which('sac2c')
        if not self.sac2c_bin:
            raise RuntimeError("Unable to find sac2c binary!")

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
                raise RuntimeError("Unable to load sac2c shared library!")

        self.sac2c_so = None

        for sac_lib_path in sac_lib_paths.split(':'):
            sac2c_so = os.path.join(sac_lib_path, sac2c_so_name)
            if os.path.exists(sac2c_so):
                self.sac2c_so = sac2c_so
                break

        if self.sac2c_so is None:
            raise RuntimeError("Unable to load sac2c shared library!")

        # get shared object
        self.sac2c_so_handle = ctypes.CDLL(self.sac2c_so, mode=(1|ctypes.RTLD_GLOBAL))

        # init sac2c jupyter interface
        self.sac2c_so_handle.jupyter_init()
        self.sac2c_so_handle.CTFinitialize()
        self.sac2c_so_handle.jupyter_parse_from_string.restype = ctypes.c_void_p
        self.sac2c_so_handle.jupyter_free.argtypes = ctypes.c_void_p,
        self.sac2c_so_handle.jupyter_free.res_rtype = ctypes.c_void_p

        # Create the directory where all the compilation/execution will be happening
        self.tmpdir = tempfile.mkdtemp(prefix="jup-sac")

        # Array is included by default
        self.actions[Use].push("use Array: all;")

    def cleanup_files(self):
        """Remove all the temporary files created by the kernel"""
        for file in self.files:
            os.remove(file)

        # Remove the directory
        rm_nonempty_dir(self.tmpdir)

        # Call some cleanup functions in sac2c library.
        self.sac2c_so_handle.jupyter_finalize()

    def run_sac2c_parser(self, prog):
        s = ctypes.c_char_p(prog.encode('utf-8'))
        ret_ptr = self.sac2c_so_handle.jupyter_parse_from_string(s, -1) #len(self.imports))
        ret_s = ctypes.cast(ret_ptr, ctypes.c_char_p).value
        self.sac2c_so_handle.jupyter_free(ret_ptr)
        j = {"status": "fail", "stderr": "cannot parse json: {}".format(ret_s)}
        try:
            j = json.loads(ret_s)
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

    def append_stdout(self, txt):
        self.stdout += txt

    def append_stderr(self, txt):
        self.stderr += txt

    def create_jupyter_subprocess(self, cmd):
        self.stdout = ""
        self.stderr = ""
        return RealTimeSubprocess(cmd,
                                  lambda contents: self.append_stdout(contents.decode()),
                                  lambda contents: self.append_stderr(contents.decode()),
                                  self.tmpdir)

    def mk_sacprg(self):
        """
        returns a string of the SaC code snippet.
        
        "StdIO: print" is included by default as it is used for printing expressions.
        """
        program = f"""\
            // use
            use Jupyter: all;
            use StdIO: all;
            {escape(self.actions[Use].to_str())}
            
            // imports
            {escape(self.actions[Import].to_str())}

            // typedefs
            {escape(self.actions[Typedef].to_str())}

            // functions
            {escape(self.actions[Function].to_str())}

            int main() {{
                // definitions
                {escape(indent_tail(self.actions[Statement].get_definitions_str()))}

                // statements
                {escape(indent_tail(self.actions[Statement].to_str()))}

                // expression
                {f"StdIO::print({self.actions[Expression].to_str()});" if len(self.actions[Expression].to_str()) else ''}
                
                // assignments
                printf("{self.separator}");
                {escape(indent_tail(self.actions[Statement].get_assignments_str()))}
                return 0;
            }}
            """
        
        # expressions and statemets need to discard their cache
        self.actions[Expression].clear()
        self.actions[Statement].clear()

        return unescape(dedent(program))

    def compile_with_sac2c(self, source_filename, binary_filename, extra_flags=[]):
        # Flags are of type list of strings.
        args = [self.sac2c_bin] \
            + ['-o', binary_filename] \
            + self.sac2c_flags \
            + extra_flags \
            + [source_filename] \

        return self.create_jupyter_subprocess(args)

    def create_binary(self, prg) -> Result:
        with self.new_temp_file(suffix='.sac') as source_file:
            source_file.write(prg)
            source_file.flush()
            with self.new_temp_file(suffix='.exe') as binary_file:
                p = self.compile_with_sac2c(source_file.name, binary_file.name, ["-L", f"{os.getcwd()}/lib", f"-T", f"{os.getcwd()}/lib"])
                while p.poll() is None:
                    p.write_contents() 
                p.write_contents()
                if (p.returncode != 0):  # Compilation failed
                    return Result(self.stdout, f"{self.stderr}[SaC kernel] sac2c exited with code {p.returncode}, the executable will not be executed", True)
                else:
                    self.binary = binary_file.name
                    return Result(self.stdout, self.stderr)

    def run_binary(self) -> Result:
        proc = self.create_jupyter_subprocess([self.binary])
        while proc.poll() is None:
            proc.write_contents()

        proc.wait_for_threads()
        proc.write_contents()

        if (proc.returncode != 0):  # Compilation failed
            return Result(self.stdout, f"{self.stderr}[SaC kernel] Executable exited with code {proc.returncode}", True)
        else:
            return Result(self.stdout, self.stderr)

    def do_execute(self, code, silent, store_history=True, user_expressions=None, allow_stdin=False):
        parser_response = self.run_sac2c_parser(code)
        action_class = sac_action_map[parser_response['ret']]
        magic = self.magics.get(code.split(" ")[0])

        if action_class:
            self.actions[action_class].push(code)
            status = self.execute_sac()
        elif magic:
            status = self.execute_magic(code, magic)
        else:
            self._write_to_stderr(f"[SaC kernel] Code could not be classified!\n{parser_response['stderr']}")
            status = Status.ERROR
        
        return {'status': status, 'execution_count': self.execution_count, 'payload': [], 'user_expressions': {}}
    
    def execute_sac(self):
        program = self.mk_sacprg()
        create_result = self.create_binary(program)
        stdout = create_result.stdout
        stderr = create_result.stderr

        if not create_result.failed:
            definitions = ''
            status = Status.OK
            run_result = self.run_binary()

            text_out = run_result.stdout.split(self.separator)
            stdout = text_out[0]
            stderr = run_result.stderr

            if len(text_out) == 2:
                definitions = text_out[1]
                if '=' in extract_code(definitions): # TODO: not pretty... fix
                    for definition in definitions.split(';'):
                        variable, value = definition.split('=', 1)
                        self.actions[Statement].add_definition(variable, value)

            elif len(text_out) != 1:
                raise Exception('Invalid return string!')

        else:
            status = Status.ERROR

        self.show_output(stdout, stderr)
        return status

    def execute_magic(self, code, magic):
        magic_result = magic.process_input(code)
        self.show_output(magic_result.stdout, magic_result.stderr)
        return Status.OK

    def show_output(self, stdout, stderr):
        if stdout:
            self._write_to_stdout(stdout)
        if stderr:
            self._write_to_stderr(stderr)

    def do_shutdown(self, restart):
        """Cleanup the created source code files and executables when shutting down the kernel"""
        self.cleanup_files()

def rm_nonempty_dir(d):
    for root, dirs, files in os.walk(d, topdown=False):
        for name in files:
            os.remove(os.path.join(root, name))
        for name in dirs:
            os.rmdir(os.path.join(root, name))
    os.rmdir(d)

def indent_tail(text, depth=4):
    return ("\n" + " " * depth).join(text.split("\n"))

def escape(text):
    return text.replace("\n", "\\n")

def unescape(text):
    return text.replace("\\n", "\n")


if __name__ == "__main__":
    from ipykernel.kernelapp import IPKernelApp
    IPKernelApp.launch_instance(kernel_class=SacKernel)
