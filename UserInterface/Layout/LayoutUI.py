# LayoutUI.py

import sys
import os
import subprocess  # For running external scripts

# Get the root directory of the project (one level up from UserInterFace/Layout)
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from PyQt5.QtWidgets import (
    QApplication, QWidget, QPushButton, QVBoxLayout,
    QTextEdit, QHBoxLayout, QDesktopWidget
)
from PyQt5.QtCore import Qt

class ButtonWindow(QWidget):
    def __init__(self, log_window):
        super().__init__()
        self.log_window = log_window  # Store reference to the log window
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("Controls")
        self.setGeometry(100, 100, 200, 400)  # Smaller window for buttons
        self.setWindowFlags(Qt.Window | Qt.CustomizeWindowHint | Qt.WindowTitleHint)
        
        # Remove the red border by clearing or not setting the stylesheet
        self.setStyleSheet("")
        
        layout = QVBoxLayout()
        
        self.btn_play = QPushButton("Play")
        self.btn_stop = QPushButton("Stop")
        self.btn_settings = QPushButton("Settings")
        self.btn_close = QPushButton("Close")

        # Connect the Play button to run AutoFish.py
        self.btn_play.clicked.connect(self.start_auto_fish)

        # Connect close button to close both windows
        self.btn_close.clicked.connect(self.close_both_windows)

        layout.addWidget(self.btn_play)
        layout.addWidget(self.btn_stop)
        layout.addWidget(self.btn_settings)
        layout.addWidget(self.btn_close)
        layout.addStretch()  # Push buttons to the top

        self.setLayout(layout)

    def start_auto_fish(self):
        # Path to the Python interpreter in your virtual environment
        python_path = r'C:\Users\mikel\Documents\4klabs\FishingTrainer\.venv\Scripts\python.exe'
        # Correct path to the AutoFish.py script within the Core folder
        auto_fish_path = r'C:\Users\mikel\Documents\4klabs\FishingTrainer\Core\AutoFish.py'

        # Add the Config directory to sys.path to ensure Settings.py can be imported
        config_path = os.path.join(project_root, 'Config')
        if config_path not in sys.path:
            sys.path.insert(0, config_path)
        
        # Run the script using the virtual environment's Python
        subprocess.Popen([python_path, auto_fish_path])
        
        # Optionally, log this action
        self.log_window.log_text.append("AutoFish started!")

    def close_both_windows(self):
        # Close both windows
        self.close()
        self.log_window.close()

class LogWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("Message Log")
        self.setGeometry(350, 100, 600, 400)  # Larger window for log
        self.setWindowFlags(Qt.Window | Qt.CustomizeWindowHint | Qt.WindowTitleHint)
        
        # Remove the red border by clearing or not setting the stylesheet
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
    button_window.move(screen.width() // 2 - button_window.width() - 10, screen.height() // 2 - button_window.height() // 2)
    log_window.move(screen.width() // 2 + 10, screen.height() // 2 - log_window.height() // 2)

    sys.exit(app.exec_())

if __name__ == '__main__':
    main()