from PyQt4 import QtGui
from PyQt4.QtCore import QMutex, SIGNAL, QThreadPool
import sys
import design
import os

from FastDLThreadClasses import BzipRunner, UpdateActiveThreads, NonBzipRunner, ProcessSourceDir

# TODO Set exlcude list on auto detected game
# TODO selected_game_changed gets called twice on init for some reason

class FastDLSyncGui(QtGui.QMainWindow, design.Ui_MainWindow):
    def __init__(self):

        super(self.__class__, self).__init__()
        self.setupUi(self)

        self.supported_games = ["garrysmod", "csgo", "tf"]
        self.set_support_games()

        self.source_file_count = 0
        self.fastdl_manifest = []
        self.exclude_list = []
        self.total_files_to_sync = 0
        self.files_to_sync = []
        self.sync_threads = []
        self.pool = QThreadPool()

        self.failed_file_sync = []
        self.thread_lock = QMutex()
        self.pool.setMaxThreadCount(self.syncThreads.value())

        self.text_virtical_scroll = self.mainTextWindow.verticalScrollBar()

        self.input_directory = self.sourceDirDisplay.text()
        self.output_dir = self.destDirDisplay.text()

        # Button Handles
        self.sourceDirBtn.clicked.connect(self.btn_select_source_folder)
        self.destDirBtn.clicked.connect(self.btn_select_dest_folder)
        self.runSync.clicked.connect(self.run_sync)
        self.excludeListBtn.clicked.connect(self.btn_exclude_list_btn_click)

        self.selectedGameCombo.currentIndexChanged.connect(self.selected_game_changed)
        self.syncThreads.valueChanged.connect(self.sync_threads_changed)

        self.set_exlude_list(self.excludeListDisplay.text())

    def sync_threads_changed(self):
        """
        Run when the user changes the number of sync threads to use in the GUI
        """
        self.pool.setMaxThreadCount(self.syncThreads.value())


    def btn_select_source_folder(self, source=None):
        """
        Run when sourceDirBtn is clicked.

        Once the directory is selected when check the directory for any games that we support.  This is done by searching
        for a directory name that matches any supported games.  As an example, a CSGO server will contain a csgo directory.

        Once we detect a support game we set selectedGameCombo to the detected game

        """

        if not source:
            source = QtGui.QFileDialog.getExistingDirectory(self,"Pick a source folder")
        print("Source " + source)

        # Make sure the selected directory contains a server of a game type we support
        for curdir, dirs, files in os.walk(source):
            for dir in dirs:
                for game in self.supported_games:
                    if dir == game:

                        self.write_to_gui_console("Found " + game + " In Current Directing.  Setting Source Path")
                        self.selectedGameCombo.setCurrentIndex(self.selectedGameCombo.findText(game))
                        self.sourceDirDisplay.setText(os.path.join(source.lower(), game))
                        self.input_directory = source.lower()
                        self.selected_game_changed()
                        return

            break

        self.write_to_gui_console('<span style="front-weight:bold; color:red;">No Supported Games Found In Selected Directory</span>')
        self.sourceDirDisplay.setText("")
        self.input_directory = ""

    def btn_select_dest_folder(self):
        """
        Called when destDirBtn is clicked to set a destination folder.  We display a file browser to select the directory
        """

        destination = QtGui.QFileDialog.getExistingDirectory(self,"Pick a destination folder")
        self.destDirDisplay.setText(destination)
        self.output_dir = destination
        self.write_to_gui_console("FastDL Directory Changed To: " + destination)

        QtGui.QMessageBox.critical(self, "WARNING", "WARNING: Make sure this is the correct output directory. Running a sync will "
                                         "delete files that don't match the sync type.  \n\n Example: If you don't select"
                                         " Bzip we will scan this directory and delete all non-bzip files.  This means "
                                         "if you put in a your C Drive it will delete everything!", QtGui.QMessageBox.Ok)

    def set_support_games(self):
        """
        On init set the list of supported games.  Also checks for supported games in CWD and sets the selected game
        dropdown to the detected game
        :return:
        """

        if not self.supported_games:
            self.selectedGameCombo.addItem("None Available")
            return

        self.selectedGameCombo.addItems(self.supported_games)

        for game in self.supported_games:
            if self.detect_game_in_source(game):
                self.selected_game_changed()
                break

    def detect_game_in_source(self, game, directory=os.getcwd()):
        """
        Check if the selected directory contains a game that we support.

        This is detected by the existence of a directory named the same value as the game selected in the dropdown.
        """

        if os.path.isdir(os.path.join(directory, game)):
            self.write_to_gui_console("Found " + game + " In Current Directing.  Setting Source Path")
            self.selectedGameCombo.setCurrentIndex(self.selectedGameCombo.findText(game))
            self.btn_select_source_folder(os.path.join(directory, game))
            return True
        return False


    def selected_game_changed(self):
        """
        Called when switching between supported games in the drop down.

        When the game is switched for check for a pre-defined exlude file located within CWD\exlcudes.  File should be
        named "game-name.txt"
        """

        self.write_to_gui_console("Setting Selected Game To " + self.selectedGameCombo.currentText())

        exclude_file = os.path.join(os.getcwd(), "excludes", self.selectedGameCombo.currentText() + ".txt")
        if os.path.isfile(exclude_file):
            self.write_to_gui_console("Found Existing Exlude List For " + self.selectedGameCombo.currentText())
            self.excludeListDisplay.setText(exclude_file)
            self.set_exlude_list(exclude_file=exclude_file)

    def btn_exclude_list_btn_click(self):
        exclude = QtGui.QFileDialog.getOpenFileName(self,"Select Exclude List", filter="*.txt")
        if exclude:
            self.excludeListDisplay.setText(exclude)
            self.set_exlude_list(exclude_file=exclude)


    def set_exlude_list(self, exclude_file=None):
        """
        Build this list of files to exclude from the sync.
        """

        if not exclude_file:
            return

        self.excludeListDisplay.setText(exclude_file)

        if not os.path.isfile(exclude_file):
            self.write_to_gui_console("Provided Exlude List Is Not a Valid File: " + exclude_file)
            return

        self.exclude_list = []
        with open(exclude_file, "r") as f:
            for i in f:
                self.exclude_list.append(i.strip("\n"))

        self.write_to_gui_console(str(len(self.exclude_list)) + " Files Added To Exclude List")


    def run_sync(self):
        """
        This is called when the user click the Sync Now button in the GUI.

        """

        self.progressBar.reset()
        self.cleanup_opposite_sync_type()
        self.process_fastdl_manifest()
        self.start_sync()



    def write_fastdl_manifest(self):
        """
        Once the sync has completed.  It takes the list manifest list we build during the sync and writes it to file.

        """
        with open(os.path.join(self.input_directory, "fastdownload.txt"), "w+") as file:
            for line in self.fastdl_manifest:
                file.write(line + "\n")
        self.fastdl_manifest = []

    def update_fastdl_manifest(self, synced_files):
        """
        Update the the list of files we have synced so we can write manifest at the end of sync.
        """
        for file in synced_files:
            if not file["input"] in self.fastdl_manifest:
                self.fastdl_manifest.append(file["input"])

    def process_fastdl_manifest(self):
        """
        Check the existing manifest to see if any files have been removed from server.  If they have, check the fastdl
        folder and see if they exist.  If they do, delete them.
        :return:
        """
        manifest_file = os.path.join(self.sourceDirDisplay.text(), "fastdownload.txt")
        self.write_to_gui_console("Checking For Manifest File: " + manifest_file)
        if os.path.isfile(manifest_file):
            self.write_to_gui_console("Processing Existing FastDL Manifest")
            with open(manifest_file, "r") as manifest:
                for line in manifest:
                    input_file = line.strip("\n").lower()
                    output_dir, output_file, relative_game_path = self.generate_output_paths(input_file)

                    if os.path.isfile(input_file):
                        self.fastdl_manifest.append(input_file)
                    else:
                        self.write_to_gui_console("<strong>Located File That That Has Been Removed.  Deleting From FastDL. " + input_file + "</strong>")
                        if os.path.isfile(output_file):
                            os.remove(output_file)
                        if os.path.isfile(output_file + ".bz2"):
                            os.remove(output_file + ".bz2")

    def start_sync(self):
        """
        This starts the main thread that handles the syncing processing.

        All directory scanning and sync file list building is done in a seperate thread to leave the GUI active.
        :return:
        """

        self.runSync.setDisabled(True)

        self.main_sync_thread = ProcessSourceDir(self.input_directory, self.output_dir, self.bZipEnable.isChecked(), self.pool, self.exclude_list)
        self.connect(self.main_sync_thread, SIGNAL("sync_thread_started(PyQt_PyObject)"), self.sig_sync_thread_started)
        self.connect(self.main_sync_thread, SIGNAL("sync_thread_finished(PyQt_PyObject)"), self.sig_sync_thread_finished)
        self.connect(self.main_sync_thread, SIGNAL("newer_file_detected(PyQt_PyObject)"), self.sig_new_file_detected)
        self.connect(self.main_sync_thread, SIGNAL("file_queued(PyQt_PyObject)"), self.sig_sync_file_queued)
        self.connect(self.main_sync_thread, SIGNAL("update_fastdl_manifest(PyQt_PyObject)"), self.update_fastdl_manifest)
        self.connect(self.main_sync_thread, SIGNAL("update_active_thread(PyQt_PyObject)"), self.update_active_threads)
        self.connect(self.main_sync_thread, SIGNAL("sync_completed"), self.sig_sync_completed)
        self.connect(self.main_sync_thread, SIGNAL("set_progress_max(PyQt_PyObject)"), self.sig_set_progress_bar_max)
        self.main_sync_thread.start()


    def sig_set_progress_bar_max(self, max=0):
        """
        Updates the max value of the progress bar to match the number of files we will be syncing
        """
        self.total_files_to_sync = max
        if max > 0:
            self.progressBar.setMaximum(max)
        else:
            self.progressBar.setMaximum(1)

    def sig_new_file_detected(self, file):
        self.write_to_gui_console("Newer File Detected: " + file)

    def sig_sync_file_queued(self, file):
        self.write_to_gui_console("File Queued For Sync: " + file)

    def sig_sync_completed(self):
        self.write_fastdl_manifest()
        self.progressBar.setValue(self.progressBar.maximum())
        self.activeThreads.setText("0")
        self.write_to_gui_console('<span style="font-weight:bold;color:green;">Sync Has Completed')
        self.write_to_gui_console("<span style='font-weight:bold;color:green;'>Total Files Synced: " + str(self.total_files_to_sync) + "</span>")
        self.runSync.setDisabled(False)

    def update_active_threads(self, count):
        self.activeThreads.setText(str(count))

    def sig_sync_thread_started(self, message):
        self.write_to_gui_console(message)

    def sig_sync_thread_finished(self, temp):
        self.thread_lock.lock()
        self.progressBar.setValue(self.progressBar.value() + 1)
        self.thread_lock.unlock()

    def cleanup_opposite_sync_type(self):
        """
        Cleanup Previously sync files that do not match the current sync type (Bzip on/off)

        If the user selects to Bzip the files all files with .bz2 ext are deleted.

        This is a potentially destructive method.  If fed a random directory without Bzip enabled it will delete everything
        """

        if self.bZipEnable.isChecked():
            self.write_to_gui_console("Bzip Selected.  Cleanup Up Existing Raw Files")
        else:
            self.write_to_gui_console("Bzip Not Selected.  Cleanup Up Existing Bzip Files")

        if not os.path.isdir(self.output_dir):
            return

        for curdir, dirs, files in os.walk(self.output_dir):

            for f in files:
                name, ext = os.path.splitext(f)
                if ext:
                    # TODO catch exception here
                    if self.bZipEnable.isChecked():
                        if not ext == ".bz2":
                            self.write_to_gui_console("Deleting: " + os.path.join(curdir, f))
                            os.remove(os.path.join(curdir, f))
                    else:
                        if ext == ".bz2":
                            self.write_to_gui_console("Deleting: " + os.path.join(curdir, f))
                            os.remove(os.path.join(curdir, f))

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

        if self.bZipEnable.isChecked():
            output_file += ".bz2"

        return output_dir, output_file, relative_game_path

    def write_to_gui_console(self, line):
        """
        Convenience method for writing to the GUI's output text box
        """
        self.mainTextWindow.append(line)
        self.mainTextWindow.ensureCursorVisible()



def main():
    app = QtGui.QApplication(sys.argv)
    form = FastDLSyncGui()
    form.show()
    app.exec_()

if __name__ == '__main__':              # if we're running file directly and not importing it
    main()