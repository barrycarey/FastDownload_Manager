from distutils.core import setup
import py2exe


setup(windows=[{"script":"FastDL_Sync_Gui.py"}], options={"py2exe":{"includes":["sip"]}}, zipfile=None)