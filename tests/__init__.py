import os
import sys

# The bot modules import each other flat (utils, message_reactions, repositories, ...),
# so the source folder is put on the path instead of turning it into a package.
SOURCE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
if SOURCE_PATH not in sys.path:
    sys.path.insert(0, SOURCE_PATH)
