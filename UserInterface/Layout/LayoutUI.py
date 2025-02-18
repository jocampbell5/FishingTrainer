# LayoutUI.py


import sys
import os

# Get the root directory of the project (one level up from UserInterFace/Layout)
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from PyQt5.QtWidgets import (
    QApplication, QWidget, QPushButton, QVBoxLayout,
    QTextEdit, QHBoxLayout, QSplitter
)
from PyQt5.QtCore import Qt

class FishingTrainerUI(QWidget):
    def __init__(self):
        super().__init__()
        self.init_ui()
        
    def init_ui(self):
        self.setWindowTitle("Fishing Trainer")
        self.setGeometry(100, 100, 800, 600)  # Ensure the window is not too small
        
        # Remove window decorations
        self.setWindowFlags(Qt.FramelessWindowHint)
        
        # Create a horizontal splitter for adjustable box sizes
        splitter = QSplitter(Qt.Horizontal)
        
        # --- Left Box: Controls ---
        left_box = QWidget()
        left_box.setStyleSheet("background-color: #2E2E2E;")  # Light black / dark grey background
        left_layout = QVBoxLayout()
        left_box.setLayout(left_layout)
        
        # Create buttons
        self.btn_play = QPushButton("Play")
        self.btn_stop = QPushButton("Stop")
        self.btn_settings = QPushButton("Settings")
        self.btn_close = QPushButton("Close")

        # Add buttons to the left layout
        left_layout.addWidget(self.btn_play)
        left_layout.addWidget(self.btn_stop)
        left_layout.addWidget(self.btn_settings)
        left_layout.addWidget(self.btn_close)
        left_layout.addStretch()  # Push buttons to the top

        # Connect the close button to close the window
        self.btn_close.clicked.connect(self.close)
        
        # --- Right Box: Message Log ---
        self.log_text = QTextEdit()
        self.log_text.setStyleSheet("background-color: #2E2E2E; color: white;")
        self.log_text.setReadOnly(True)
        self.log_text.setPlaceholderText("Message log will appear here...")
        
        # Add the two boxes to the splitter
        splitter.addWidget(left_box)
        splitter.addWidget(self.log_text)
        splitter.setSizes([200, 600])  # Initial sizes for left and right boxes
        
        # Main layout for the window
        main_layout = QHBoxLayout()
        main_layout.addWidget(splitter)
        self.setLayout(main_layout)

# ---- This part should be at the bottom of the file ----
if __name__ == '__main__':
    app = QApplication(sys.argv)  # Create the application instance
    window = FishingTrainerUI()   # Create the UI window
    window.show()                 # Show the UI window
    sys.exit(app.exec_())         # Run the application event loop