from PyQt4.QtCore import QThread, SIGNAL, QRunnable, QObject, pyqtSignal
import bz2
import os
import shutil

class BzipThread(QThread):

    def __init__(self, input_file, output_file, output_dir):
        QThread.__init__(self)
        self.input_file = input_file
        self.output_file = output_file
        self.output_dir = output_dir

    def __del__(self):
        self.wait()

    def run(self):

        self.emit(SIGNAL('thread_started(PyQt_PyObject)'), "Compressing " + os.path.basename(self.input_file))

        if not os.path.isdir(self.output_dir):
            os.makedirs(self.output_dir)

        with open(self.input_file, "rb") as source:
            # TODO Need to check into what exceptions this can throw
            with bz2.open(self.output_file, "wb", compresslevel=5) as destination:
                destination.write(source.read())

class ThreadSignals(QObject):
    thread_started = pyqtSignal(str)
    thread_finished = pyqtSignal(str)

class BzipRunner(QRunnable):

    def __init__(self, input_file, output_file, output_dir):
        super(BzipRunner, self).__init__()
        self.input_file = input_file
        self.output_file = output_file
        self.output_dir = output_dir
        self.signals = ThreadSignals()

    def run(self):

        self.signals.thread_started.emit("Compressing: " + os.path.basename(self.input_file))

        if not os.path.isdir(self.output_dir):
            os.makedirs(self.output_dir)

        with open(self.input_file, "rb") as source:
            # TODO Need to check into what exceptions this can throw
            with bz2.open(self.output_file, "wb", compresslevel=5) as destination:
                destination.write(source.read())

        self.signals.thread_finished.emit("done")

class NonBzipRunner(QRunnable):

    def __init__(self, input_file, output_file, output_dir):
        super(NonBzipRunner, self).__init__()
        self.input_file = input_file
        self.output_file = output_file
        self.output_dir = output_dir
        self.signals = ThreadSignals()

    def run(self):

        self.signals.thread_started.emit("Moving: " + os.path.basename(self.input_file))

        try:
            shutil.copy2(self.input_file, self.output_file)
        except IOError as e:
            print("[x] Failed To Sync: " + self.input_file)
            print("[x] Error: " + e)

        self.signals.thread_finished.emit("done")

class StartSyncThreads(QThread):

    def __init__(self, files_to_sync, bzip):
        QThread.__init__(self)
        self.files_to_sync = files_to_sync
        self.bzip = bzip

    def __del__(self):
        self.wait()

    def run(self):
        pass


class UpdateActiveThreads(QThread):

    def __init__(self, pool):
        QThread.__init__(self)
        self.pool = pool

    def __del__(self):
        self.wait()

    def run(self):

        while self.pool.activeThreadCount() > 0:
            self.emit(SIGNAL('update_active_thread(PyQt_PyObject)'), self.pool.activeThreadCount())
            self.sleep(0.2)

        self.emit(SIGNAL('sync_completed'))


class ProcessSourceDir(QThread):

    def __init__(self, input_dir, output_dir, bzip, pool, exclude_list):
        QThread.__init__(self)
        self.input_directory = input_dir
        self.output_dir = output_dir
        self.bzip_enabled = bzip
        self.exclude_list = exclude_list
        self.files_to_sync = []
        self.pool = pool

    def __del__(self):
        self.wait()

    def run(self):

        for curdir, dirs, files in os.walk(self.input_directory):

            for f in files:
                input_file = os.path.join(curdir, f).lower()

                output_dir, output_file, relative_game_path = self.generate_output_paths(input_file)

                if self.check_exclude_list(relative_game_path):
                    continue

                if not os.path.isdir(output_dir):
                    os.makedirs(output_dir)

                if os.path.isfile(output_file):
                    if not os.path.getmtime(input_file) > os.path.getmtime(output_file):
                        continue
                    else:
                        os.remove(output_file)
                        self.emit(SIGNAL('newer_file_detected(PyQt_PyObject)'), os.path.split(input_file))

                self.files_to_sync.append({"input": input_file, "output": output_file, "output_dir": output_dir})

                self.emit(SIGNAL('file_queued(PyQt_PyObject)'), input_file)

        if len(self.files_to_sync) > 0:
            self.emit(SIGNAL('update_fastdl_manifest(PyQt_PyObject)'), self.files_to_sync)
            self.build_thread_pool()
        self.emit(SIGNAL('set_progress_max(PyQt_PyObject)'), len(self.files_to_sync))
        self.update_active_threads()

    def build_thread_pool(self):
        print("Building thread pool")
        for file in self.files_to_sync:
            if self.bzip_enabled:
                sync_thread = BzipRunner(file["input"], file["output"], file["output_dir"])
            else:
                sync_thread = NonBzipRunner(file["input"], file["output"], file["output_dir"])
            sync_thread.setAutoDelete(True)
            sync_thread.signals.thread_started.connect(self.sync_thread_started)
            sync_thread.signals.thread_finished.connect(self.sync_thread_finished)
            self.pool.start(sync_thread)

    def sync_thread_started(self, message):
        self.emit(SIGNAL('sync_thread_started(PyQt_PyObject)'), message)

    def sync_thread_finished(self, message=""):
        self.emit(SIGNAL('sync_thread_finished(PyQt_PyObject)'), message)

    def update_active_threads(self):
        while self.pool.activeThreadCount() > 0:
            self.emit(SIGNAL('update_active_thread(PyQt_PyObject)'), self.pool.activeThreadCount())
            self.sleep(0.2)

        self.emit(SIGNAL('sync_completed'))

    def generate_output_paths(self, input_file):
        """
        Generate the relative and full output paths.  Return the output directory, the absolute output path and
        relative game directory
        :param input_file:
        :return:
        """

        relative_game_path = input_file.replace(self.input_directory + "\\", "") # Strip everything except game directories

        temp = os.path.join(self.output_dir, relative_game_path)
        output_dir = os.path.dirname(temp)
        output_file = os.path.join(output_dir, os.path.basename(input_file))

        if self.bzip_enabled:
            output_file += ".bz2"

        return output_dir, output_file, relative_game_path

    def check_exclude_list(self, to_be_checked):
        """
        Check if given file, or relative path is in exclude list.  If it's a file we also check it's extension against
        exclude list
        """
        name, ext, relative_dir = "", "", ""

        # Check if it's a directory or file
        if os.path.splitext(to_be_checked)[1]:
            name, ext = os.path.splitext(os.path.split(to_be_checked)[1])
            relative_dir = os.path.dirname(to_be_checked)

        if to_be_checked in self.exclude_list:
            return True

        if relative_dir and relative_dir in self.exclude_list:
            return True

        if ext and ext in self.exclude_list:
            return True

        return False
