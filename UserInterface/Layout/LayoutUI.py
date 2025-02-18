import sys
import os
import subprocess  # For running external scripts

# Correctly set the project root (two levels up from LayoutUI.py)
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from PyQt5.QtWidgets import (
    QApplication, QWidget, QPushButton, QVBoxLayout,
    QTextEdit, QHBoxLayout, QDesktopWidget
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal

class OutputReaderThread(QThread):
    new_text = pyqtSignal(str)

    def __init__(self, pipe):
        super().__init__()
        self.pipe = pipe

    def run(self):
        # Read lines until the pipe is closed.
        for line in iter(self.pipe.readline, ""):
            if line:
                self.new_text.emit(line.rstrip())
        self.pipe.close()

class ButtonWindow(QWidget):
    def __init__(self, log_window):
        super().__init__()
        self.log_window = log_window  # Reference to the log window
        self.auto_fish_process = None  # Holds the AutoFish.py process when running
        self.stdout_thread = None
        self.stderr_thread = None
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("Controls")
        self.setGeometry(100, 100, 220, 300)
        self.setWindowFlags(Qt.Window | Qt.CustomizeWindowHint | Qt.WindowTitleHint)
        self.setStyleSheet("")
        
        layout = QVBoxLayout()
        
        self.btn_play = QPushButton("Play")
        self.btn_pause = QPushButton("Pause")  # This button toggles Pause/Resume
        self.btn_stop = QPushButton("Stop")      # This button stops the fishing program
        self.btn_settings = QPushButton("Settings")
        self.btn_close = QPushButton("Close")

        # Connect buttons to functions
        self.btn_play.clicked.connect(self.start_auto_fish)
        self.btn_pause.clicked.connect(self.toggle_pause)
        self.btn_stop.clicked.connect(self.stop_auto_fish)
        self.btn_settings.clicked.connect(self.show_settings)
        self.btn_close.clicked.connect(self.close_both_windows)

        # Add buttons to layout
        layout.addWidget(self.btn_play)
        layout.addWidget(self.btn_pause)
        layout.addWidget(self.btn_stop)
        layout.addWidget(self.btn_settings)
        layout.addWidget(self.btn_close)
        layout.addStretch()  # Push buttons to the top

        self.setLayout(layout)

    def start_auto_fish(self):
        """Start the AutoFish.py process if not already running."""
        if self.auto_fish_process is None or self.auto_fish_process.poll() is not None:
            # Path to the Python interpreter in your virtual environment
            python_path = os.path.join(project_root, '.venv', 'Scripts', 'python.exe')
            # Correct path to the AutoFish.py script within the Core folder
            auto_fish_path = os.path.join(project_root, 'Core', 'AutoFish.py')
            
            # Remove any existing pause flag (in case it was left from a previous session)
            pause_file = os.path.join(project_root, 'pause_flag.txt')
            if os.path.exists(pause_file):
                os.remove(pause_file)
                self.btn_pause.setText("Pause")

            # Start the AutoFish process with pipes for stdout and stderr.
            # The "-u" flag forces unbuffered mode.
            self.auto_fish_process = subprocess.Popen(
                [python_path, "-u", auto_fish_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,                # Same as universal_newlines=True
                encoding="utf-8",         # Force UTF-8 decoding
                errors="replace",         # Replace undecodable characters
                bufsize=1
            )
            self.log_window.log_text.append("AutoFish started!")

            # Start threads to capture output from stdout and stderr.
            self.stdout_thread = OutputReaderThread(self.auto_fish_process.stdout)
            self.stdout_thread.new_text.connect(self.log_window.log_text.append)
            self.stdout_thread.start()

            self.stderr_thread = OutputReaderThread(self.auto_fish_process.stderr)
            self.stderr_thread.new_text.connect(self.log_window.log_text.append)
            self.stderr_thread.start()
        else:
            self.log_window.log_text.append("AutoFish is already running.")


    def toggle_pause(self):
        """
        Toggle the fishing bot between pause and resume.
        This works by creating or removing a pause flag file.
        """
        pause_file = os.path.join(project_root, 'pause_flag.txt')
        if os.path.exists(pause_file):
            # Resume the fishing bot
            os.remove(pause_file)
            self.log_window.log_text.append("Resuming fishing...")
            self.btn_pause.setText("Pause")
        else:
            # Pause the fishing bot
            with open(pause_file, "w") as f:
                f.write("paused")
            self.log_window.log_text.append("Fishing paused.")
            self.btn_pause.setText("Resume")

    def stop_auto_fish(self):
        """
        Stop the AutoFish process without closing the UI.
        This terminates the AutoFish process (if running) so the fishing program stops.
        """
        if self.auto_fish_process is not None and self.auto_fish_process.poll() is None:
            self.auto_fish_process.terminate()  # Terminate the fishing program
            self.log_window.log_text.append("AutoFish stopped!")
            self.auto_fish_process = None
            # Optionally, wait for the threads to finish.
            if self.stdout_thread is not None:
                self.stdout_thread.wait()
            if self.stderr_thread is not None:
                self.stderr_thread.wait()
            # Reset the pause button text in case it was in 'Resume' mode.
            self.btn_pause.setText("Pause")
        else:
            self.log_window.log_text.append("AutoFish is not running.")

    def show_settings(self):
        # Placeholder for settings functionality.
        self.log_window.log_text.append("Settings clicked.")

    def close_both_windows(self):
        # Optionally, also stop the AutoFish process before closing.
        self.stop_auto_fish()
        self.close()
        self.log_window.close()

class LogWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("Message Log")
        self.setGeometry(350, 100, 600, 400)
        self.setWindowFlags(Qt.Window | Qt.CustomizeWindowHint | Qt.WindowTitleHint)
        self.setStyleSheet("")
        
        layout = QVBoxLayout()
        
        self.log_text = QTextEdit()
        self.log_text.setStyleSheet("background-color: #2E2E2E; color: white;")
        self.log_text.setReadOnly(True)
        self.log_text.setPlaceholderText("Message log will appear here...")
        
        layout.addWidget(self.log_text)
        self.setLayout(layout)

def main():
    app = QApplication(sys.argv)
    
    log_window = LogWindow()
    button_window = ButtonWindow(log_window)

    # Show windows
    button_window.show()
    log_window.show()

    # Position the windows side by side
    screen = QDesktopWidget().screenGeometry()
    button_window.move(screen.width() // 2 - button_window.width() - 10,
                       screen.height() // 2 - button_window.height() // 2)
    log_window.move(screen.width() // 2 + 10,
                    screen.height() // 2 - log_window.height() // 2)

    sys.exit(app.exec_())

if __name__ == '__main__':
    main()
